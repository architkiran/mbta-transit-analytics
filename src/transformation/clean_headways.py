"""Clean one service day of headways from raw.headways.

Usage (prints a data quality report, writes nothing):
    python -m src.transformation.clean_headways 2026-01-14

Rules applied (each backed by a finding in docs/data_profile.md):
- Text is trimmed; the literal "NA" and empty strings become null (Finding 2).
- Types are corrected: dates, integers, and IDs kept as strings.
- stop_departure_datetime: the trailing "Z" is ignored and the value is read
  as Eastern local time, NOT UTC (Finding 1).
- Rows that cannot represent their grain (service_date + trip_id + stop_id
  + route_id) are quarantined with a reason, never silently dropped.

Measured but NOT acted on yet (decided after reviewing real numbers):
- Implausible headway values (zero, negative, very long).
- Disagreement between stop_departure_datetime and stop_departure_sec.
"""
import argparse
import datetime as dt

import pandas as pd
from sqlalchemy import Engine, create_engine, text

from src.config import PG_URL
from src.ingestion.load_raw import EXPECTED_COLUMNS

# Grain: one departure of one trip on one route at one stop on one service day.
# The data dictionary claims service_date + trip_id + stop_id, but 3,095 Green Line
# rows share that key with a different route_id (data_profile Finding 10).
KEY = ["service_date", "trip_id", "stop_id", "route_id"]
INT_COLUMNS = ["direction_id", "stop_departure_sec", "headway_trunk_seconds", "headway_branch_seconds"]
HEADWAY_COLUMNS = ["headway_trunk_seconds", "headway_branch_seconds"]


def read_raw_day(engine: Engine, day: dt.date) -> pd.DataFrame:
    """Read one service day from the raw table (uses the service_date index)."""
    return pd.read_sql(
        text("SELECT * FROM raw.headways WHERE service_date = :d"),
        engine,
        params={"d": day.isoformat()},
    )


def _to_int(s: pd.Series) -> tuple[pd.Series, int]:
    """Text to nullable integer. Returns the column and how many values failed to parse."""
    num = pd.to_numeric(s, errors="coerce")
    num = num.where(num == num.round())  # 12.5 is not a valid count of seconds
    failed = int((s.notna() & num.isna()).sum())
    return num.astype("Int64"), failed


def clean_headways(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Return (clean rows, rejected rows with reason, data quality stats)."""
    stats: dict = {"rows_read": len(raw)}
    df = raw.copy()

    # 1. Normalize text: trim, then turn the source's "NA" marker and blanks into real nulls
    for c in EXPECTED_COLUMNS:
        df[c] = df[c].str.strip()
        df[c] = df[c].mask(df[c].isin(["NA", ""]))

    # 2. Correct types
    service_ts = pd.to_datetime(df["service_date"], format="%Y-%m-%d", errors="coerce")
    for c in INT_COLUMNS:
        df[c], stats[f"unparseable_{c}"] = _to_int(df[c])

    # The "Z" is a mislabel: these are Eastern wall-clock times (data_profile Finding 1)
    departure = pd.to_datetime(
        df["stop_departure_datetime"].str.removesuffix("Z"),
        format="%Y-%m-%dT%H:%M:%S",
        errors="coerce",
    )

    # 3. Quarantine rows that cannot represent their grain
    reason = pd.Series(pd.NA, index=df.index, dtype="string")
    reason = reason.mask(reason.isna() & (df[KEY].isna().any(axis=1) | service_ts.isna()), "missing_key")
    reason = reason.mask(reason.isna() & departure.isna(), "unparseable_departure")
    dup = df[KEY].duplicated(keep="first") & reason.isna()
    reason = reason.mask(dup, "duplicate_key")

    rejected = raw[reason.notna()].assign(reject_reason=reason[reason.notna()])
    keep = reason.isna()
    df, service_ts, departure = df[keep], service_ts[keep], departure[keep]

    # 4. Derived columns
    df = df.assign(
        service_date=service_ts.dt.date,
        departure_local=departure,
        hour_of_day=departure.dt.hour.astype("Int64"),
    )

    # 5. Measurements (reported, not acted on)
    expected = service_ts + pd.to_timedelta(df["stop_departure_sec"].astype("float64"), unit="s")
    stats["departure_sec_mismatch"] = int(
        (df["stop_departure_sec"].notna() & (departure != expected)).sum()
    )
    for c in HEADWAY_COLUMNS:
        h = df[c].dropna()
        stats[c] = {
            "non_null": len(h),
            "null": int(df[c].isna().sum()),
            "<= 0": int((h <= 0).sum()),
            "< 30s": int(((h > 0) & (h < 30)).sum()),
            "> 1h": int((h > 3600).sum()),
            "> 2h": int((h > 7200).sum()),
            "min": None if h.empty else int(h.min()),
            "median": None if h.empty else int(h.median()),
            "p99": None if h.empty else int(h.quantile(0.99)),
            "max": None if h.empty else int(h.max()),
        }

    stats["rows_clean"] = len(df)
    stats["rows_rejected"] = len(rejected)
    stats["rejected_by_reason"] = rejected["reject_reason"].value_counts().to_dict()

    columns = [
        "service_date", "route_id", "trunk_route_id", "branch_route_id", "trip_id",
        "direction_id", "direction", "parent_station", "stop_id", "stop_name",
        "departure_local", "hour_of_day", "stop_departure_sec",
        "headway_trunk_seconds", "headway_branch_seconds", "_batch_id", "_source_file",
    ]
    return df[columns].reset_index(drop=True), rejected, stats


def print_report(day: dt.date, stats: dict) -> None:
    print(f"\n=== Data quality report: {day} ===")
    print(f"rows read:     {stats['rows_read']:>8,}")
    print(f"rows clean:    {stats['rows_clean']:>8,}")
    print(f"rows rejected: {stats['rows_rejected']:>8,}  {stats['rejected_by_reason'] or ''}")
    for c in INT_COLUMNS:
        print(f"unparseable {c}: {stats[f'unparseable_{c}']}")
    print(f"departure datetime vs seconds mismatches: {stats['departure_sec_mismatch']:,}")
    for c in HEADWAY_COLUMNS:
        print(f"\n{c}:")
        for k, v in stats[c].items():
            print(f"  {k:>9}: {v if v is not None else '-'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean one service day and print a DQ report")
    parser.add_argument("dates", nargs="+", type=dt.date.fromisoformat, help="YYYY-MM-DD")
    args = parser.parse_args()

    engine = create_engine(PG_URL)
    for day in args.dates:
        raw = read_raw_day(engine, day)
        if raw.empty:
            print(f"\n=== {day}: no rows in raw.headways ===")
            continue
        _, _, stats = clean_headways(raw)
        print_report(day, stats)


if __name__ == "__main__":
    main()
