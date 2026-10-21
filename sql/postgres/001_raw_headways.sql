-- Raw landing zone: data exactly as it arrives, nothing rejected, nothing typed.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS audit;

-- One row per file loaded. The hash makes reloading the same file a no-op.
CREATE TABLE IF NOT EXISTS audit.ingested_files (
    file_sha256   CHAR(64)    PRIMARY KEY,
    file_name     TEXT        NOT NULL,
    target_table  TEXT        NOT NULL,
    row_count     BIGINT      NOT NULL,
    batch_id      UUID        NOT NULL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- All 14 source columns as TEXT, so a malformed value can never fail the load.
CREATE TABLE IF NOT EXISTS raw.headways (
    service_date             TEXT,
    route_id                 TEXT,
    trunk_route_id           TEXT,
    branch_route_id          TEXT,
    trip_id                  TEXT,
    direction_id             TEXT,
    direction                TEXT,
    parent_station           TEXT,
    stop_id                  TEXT,
    stop_name                TEXT,
    stop_departure_datetime  TEXT,
    stop_departure_sec       TEXT,
    headway_trunk_seconds    TEXT,
    headway_branch_seconds   TEXT,
    -- lineage: where each row came from
    _batch_id                UUID        NOT NULL,
    _source_file             TEXT        NOT NULL,
    _ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_raw_headways_service_date
    ON raw.headways (service_date);
