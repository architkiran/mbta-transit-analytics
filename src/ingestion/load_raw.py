"""Load one MBTA headways CSV into raw.headways, exactly as delivered.

Usage:
    python -m src.ingestion.load_raw data/raw/headways_2026/Headways_2026/2026-01_Headways.csv

Guarantees:
- Idempotent: a file is identified by the SHA-256 of its contents. Loading the
  same file twice is a no-op; a corrected file with the same name is loaded.
- All-or-nothing: the whole file loads in one transaction, or nothing does.
- Faithful: every value is kept as text, including the literal "NA".
- Contract-checked: the header must match the 14 expected columns exactly.
- Verified: rows in the table must equal rows read from the file.
"""
import argparse
import hashlib
import io
import logging
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from src.config import PG_URL

log = logging.getLogger("load_raw")

TARGET_TABLE = "raw.headways"
CHUNK_ROWS = 200_000
EXPECTED_COLUMNS = [
    "service_date",
    "route_id",
    "trunk_route_id",
    "branch_route_id",
    "trip_id",
    "direction_id",
    "direction",
    "parent_station",
    "stop_id",
    "stop_name",
    "stop_departure_datetime",
    "stop_departure_sec",
    "headway_trunk_seconds",
    "headway_branch_seconds",
]


def sha256_of(path: Path) -> str:
    """Fingerprint a file's contents, reading 1 MB at a time to keep memory flat."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_file(engine: Engine, path: Path) -> int:
    """Load one CSV into the raw table. Returns rows loaded (0 if already loaded)."""
    digest = sha256_of(path)

    with engine.begin() as conn:  # one transaction: commit at the end, rollback on any error
        already = conn.execute(
            text("SELECT ingested_at FROM audit.ingested_files WHERE file_sha256 = :d"),
            {"d": digest},
        ).first()
        if already:
            log.info("Skipping %s: identical file already loaded at %s", path.name, already[0])
            return 0

        batch_id = str(uuid.uuid4())
        columns = ", ".join(EXPECTED_COLUMNS + ["_batch_id", "_source_file"])
        copy_sql = f"COPY {TARGET_TABLE} ({columns}) FROM STDIN WITH (FORMAT csv)"

        # dtype=str + na_filter=False: read every value as the exact text in the file.
        reader = pd.read_csv(path, dtype=str, na_filter=False, chunksize=CHUNK_ROWS)

        pg = conn.connection.driver_connection  # the underlying psycopg connection
        total = 0
        with pg.cursor() as cur:
            for chunk in reader:
                if list(chunk.columns) != EXPECTED_COLUMNS:
                    raise ValueError(
                        f"{path.name}: header does not match the expected columns.\n"
                        f"  expected: {EXPECTED_COLUMNS}\n  found:    {list(chunk.columns)}"
                    )
                chunk["_batch_id"] = batch_id
                chunk["_source_file"] = path.name

                buf = io.StringIO()
                chunk.to_csv(buf, index=False, header=False)
                with cur.copy(copy_sql) as copy:  # COPY: Postgres's bulk-load path
                    copy.write(buf.getvalue())

                total += len(chunk)
                log.info("%s: %s rows copied", path.name, f"{total:,}")

        loaded = conn.execute(
            text(f"SELECT count(*) FROM {TARGET_TABLE} WHERE _batch_id = :b"),
            {"b": batch_id},
        ).scalar_one()
        if loaded != total:
            raise RuntimeError(f"Row count mismatch: read {total:,}, table has {loaded:,}")

        conn.execute(
            text(
                "INSERT INTO audit.ingested_files "
                "(file_sha256, file_name, target_table, row_count, batch_id) "
                "VALUES (:d, :f, :t, :n, :b)"
            ),
            {"d": digest, "f": path.name, "t": TARGET_TABLE, "n": total, "b": batch_id},
        )

    log.info("Loaded %s: %s rows, batch %s", path.name, f"{total:,}", batch_id)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Load MBTA headways CSVs into raw.headways")
    parser.add_argument("files", nargs="+", type=Path, help="CSV file(s) to load")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = create_engine(PG_URL)
    for path in args.files:
        if not path.is_file():
            raise SystemExit(f"File not found: {path}")
        load_file(engine, path)


if __name__ == "__main__":
    main()
