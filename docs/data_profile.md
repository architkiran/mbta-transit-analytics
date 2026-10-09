# Data Profile: MBTA Rapid Transit Headways 2026

## Source
- **Dataset:** MBTA Rapid Transit Headways 2026 (MBTA / MassDOT Open Data, via MassGIS Data Hub)
- **Download URL:** https://www.arcgis.com/sharing/rest/content/items/fffd5e8ff7f042deb7834f3badf49e58/data
- **License:** CC0
- **Downloaded:** 2026-09-27
- **Export date (file timestamps inside zip):** 2026-09-05
- **Upstream source:** MBTA LAMP (Lightweight Application for Measuring Performance)
- **Update pattern:** Dataset is still being updated during 2026; new months are expected to be added.

## Files
One CSV per month, inside `Headways_2026.zip` → `Headways_2026/`.

| File | Size | Rows (excl. header) | Days | Rows/day |
|---|---|---|---|---|
| 2026-01_Headways.csv | 120 MB | 1,113,360 | 31 | ~35,900 |
| 2026-02_Headways.csv | 107 MB | 999,535 | 28 | ~35,700 |
| 2026-03_Headways.csv | 125 MB | 1,171,451 | 31 | ~37,800 |
| 2026-04_Headways.csv | 122 MB | 1,151,211 | 30 | ~38,400 |
| 2026-05_Headways.csv | 119 MB | 1,116,893 | 31 | ~36,000 |
| 2026-06_Headways.csv | 122 MB | 1,145,849 | 30 | ~38,200 |
| 2026-07_Headways.csv | 124 MB | 1,155,775 | 31 | ~37,300 |
| 2026-08_Headways.csv | 104 MB | 977,365 | 31 | ~31,500 |
| **Total** | **~943 MB** | **8,831,439** | | |

Coverage: 2026-01-01 through 2026-08-31.

## Schema
**Grain:** one row per `service_date` + `trip_id` + `stop_id` (one train departing one stop on one day).

| Column | Observed format | Notes |
|---|---|---|
| service_date | `2026-01-01` | ISO date |
| route_id | `Green-B` | Branch-level route |
| trunk_route_id | `Green` | Line-level: Blue, Green, Mattapan, Orange, Red |
| branch_route_id | `Green-B` | NULL for lines without branches |
| trip_id | `73223815` | Identifier, store as string |
| direction_id | `1` | 0 or 1 |
| direction | `East` | Human-readable direction |
| parent_station | `place-babck` | Station-level ID |
| stop_id | `170136` | Platform-level ID, store as string |
| stop_name | `Babcock Street` | |
| stop_departure_datetime | `2026-01-01T05:42:03Z` | See Finding 1 |
| stop_departure_sec | `20523` | Seconds after midnight of service_date |
| headway_trunk_seconds | integer or `NA` | See Finding 3 |
| headway_branch_seconds | integer or `NA` | See Finding 3 |

All files have exactly 14 columns on every row (verified for January: 0 malformed rows).

## Findings

### 1. Timestamps are labeled UTC but are Eastern local time
`stop_departure_datetime` ends in `Z` (UTC marker), but its clock time matches `stop_departure_sec` with no offset:
`20523 sec = 05:42:03`, and the datetime reads `05:42:03Z`. If the value were truly UTC, the local time would be 00:42 (EST), and the first Green-B trip of the day would fall at a time that belongs to the previous service day.

**Handling:** ignore the `Z`, treat the value as Eastern local time. Never parse this column with `utc=True`. Use `stop_departure_sec` as the cross-check.

### 2. Nulls are the literal string `NA`
Missing values appear as the text `NA`, not empty fields. Pandas converts this by default; Postgres and BigQuery do not.

**Handling:** convert `NA` to NULL explicitly in the cleaning step. The raw layer keeps it as-is.

### 3. Headways missing for Jan 1 to 4, 2026 (data gap) plus first departures (expected)
In January, about 13% of `headway_trunk_seconds` values were `NA` on every line (Orange 12.6%, Green 12.4%, Blue 13.7%, Red 13.6%, Mattapan 12.2%). Investigation showed this was two separate causes mixed together:

- **Data gap:** 100% of rows on 2026-01-01 through 2026-01-04 have `NA` headways (133,109 rows). A scan of all 8 monthly files found no other dates with more than 5% NA, so the gap is a one-off. Cause unknown.
- **Expected behavior:** on all other days, about 1% of rows are `NA`, because the first departure of the day at each stop has no previous train. This shows up as elevated NA rates at 4 to 5 AM.

How this was narrowed down (each test ruled out one hypothesis):
1. By stop (Red Line): NA rate was 13.5 to 14.3% at every stop, so it was not caused by specific stops.
2. By hour (Red Line): NA rate was 12 to 14% from 6 AM to midnight, so it was not caused by time of day.
3. By date (all lines): Jan 1 to 4 at 100%, all other days near 1%. Confirmed.

**Decision:** keep all rows. Headways stay NULL for Jan 1 to 4, and headway metrics exclude those dates. The rows remain valid for trip counts and service volume.
**Future improvement:** derive headways from `stop_departure_sec`, validate against LAMP values on dates where both exist, then backfill Jan 1 to 4.

### 4. Strong weekday / weekend pattern
In August, weekdays run about 40,000 rows/day and weekends about 20,000. Weekend service is roughly half of weekday service.

**Handling:** `dim_date` must include `is_weekend`. Weekday and weekend metrics should be reported separately.

### 5. August volume drop explained by planned shutdowns (real events, not bad data)
All 31 days of August are present, so the file is not truncated. Row counts dropped on specific days:
- **Aug 10 to 14 (weekdays):** about 27,000 rows/day vs. about 40,000 normal.
- Per-line comparison, Tue Aug 4 vs Tue Aug 11:

  | Line | Aug 4 | Aug 11 |
  |---|---|---|
  | Blue | 3,841 | 3,848 |
  | Green | 21,563 | 7,481 |
  | Mattapan | 1,543 | 1,587 |
  | Orange | 7,921 | 7,646 |
  | Red | 6,480 | 6,710 |

  Green alone accounts for the drop. **Confirmed** against news coverage: Green Line service was suspended on large portions of all four branches Aug 8 to 16, 2026, for signal upgrades and C branch accessibility work. A weekend Green Line suspension also occurred Aug 1 to 2.
- **Aug 20 to 28 (weekdays):** about 35,000 rows/day. **Likely** the Orange Line closure (Back Bay to Oak Grove, Aug 20 to 30). Not yet verified per line.
- Weekends Aug 22 to 23 and Aug 29 to 30 are higher (about 27,000 to 28,000) than earlier August weekends (about 20,000). **Unexplained (OPEN).**

**Handling:** keep all rows. Planned shutdowns are real service conditions and must not be cleaned away. Candidate feature: a hand-curated `dim_service_disruption` table (line, start date, end date, reason) so analysis can compare reliability with and without planned disruptions.

### 6. Row counts are not proportional to importance
Green produces about 21,000 rows on a normal weekday vs. about 6,500 for Red, because it has four branches and many more stops (one row per train per stop).

**Handling:** aggregate per line before comparing lines. Never average across all rows as a "system" metric.

### 7. Mattapan appears as its own line
`trunk_route_id = Mattapan` (trolley line), about 1,500 rows/day.

**Handling:** include/exclude decision deferred.

### 8. Terminal stations are nearly absent for trips starting there
Alewife southbound (the start of southbound Red Line trips) has only 23 rows in all of January, compared with thousands at every other stop. LAMP defines departures using movement from the previous stop, so a trip's first stop mostly gets no departure record.

**Handling:** station-level analysis must not interpret missing terminal departures as missing service.

### 9. Low-service days in late January (OPEN)
- 2026-01-19 (MLK Day, Monday): 31,918 rows, low for a weekday. Likely holiday schedule.
- 2026-01-25 (Sunday): 22,664 rows. 2026-01-26 (Monday): 19,279 rows, below a normal Sunday.
- 2026-01-27 to 01-31: 30,000 to 35,000 rows vs. about 42,000 on normal weekdays.

**Handling:** keep all rows. Cause to verify (possibly a winter storm). Candidate entry for the disruptions table.

## Open Questions
1. Does the late-August weekday dip come from the Orange Line closure? (Check per-line counts for Aug 20 to 28.)
2. Why are the last two August weekends higher than earlier ones?
3. What caused the low service on Jan 25 to 31?
4. Include Mattapan in analysis or not?

## Resolved
- Headway NAs: Jan 1 to 4 data gap plus expected first-departure NAs. See Finding 3.

## Commands Used
```bash
# Files and sizes
ls -lh data/raw/headways_2026/Headways_2026

# Raw first rows
head -5 data/raw/headways_2026/Headways_2026/2026-01_Headways.csv

# Row counts per file
wc -l data/raw/headways_2026/Headways_2026/*.csv

# Rows per day, August
cut -d, -f1 data/raw/headways_2026/Headways_2026/2026-08_Headways.csv | sort | uniq -c

# Rows per line, Aug 4 vs Aug 11
awk -F, '$1=="2026-08-04" || $1=="2026-08-11" {print $1, $3}' data/raw/headways_2026/Headways_2026/2026-08_Headways.csv | sort | uniq -c

# NA rate by line (plus column-count check), January
awk -F, 'NR>1 {if (NF != 14) bad++; total[$3]++; if ($13 == "NA") na[$3]++} END {for (line in total) printf "%-10s %9d rows %9d NA  %5.1f%%\n", line, total[line], na[line], 100*na[line]/total[line]; print "rows without exactly 14 columns:", bad+0}' data/raw/headways_2026/Headways_2026/2026-01_Headways.csv

# NA rate by stop (Red), January
awk -F, 'NR>1 && $3=="Red" {k = $10 " | " $7; t[k]++; if ($13 == "NA") n[k]++} END {for (k in t) printf "%5.1f%%  %6d / %6d  %s\n", 100*n[k]/t[k], n[k], t[k], k}' data/raw/headways_2026/Headways_2026/2026-01_Headways.csv | sort -rn | head -20

# NA rate by hour (Red), January
awk -F, 'NR>1 && $3=="Red" {h = int($12 / 3600); t[h]++; if ($13 == "NA") n[h]++} END {for (h in t) printf "%2d  %5.1f%%  %6d / %6d\n", h, 100*n[h]/t[h], n[h], t[h]}' data/raw/headways_2026/Headways_2026/2026-01_Headways.csv | sort -n

# NA rate by date, January
awk -F, 'NR>1 {t[$1]++; if ($13 == "NA") n[$1]++} END {for (d in t) printf "%s  %5.1f%%  %6d / %6d\n", d, 100*n[d]/t[d], n[d], t[d]}' data/raw/headways_2026/Headways_2026/2026-01_Headways.csv | sort

# Dates with >5% NA headways, all months
awk -F, 'FNR>1 {t[$1]++; if ($13 == "NA") n[$1]++} END {for (d in t) if (n[d]/t[d] > 0.05) printf "%s  %5.1f%%  %6d / %6d\n", d, 100*n[d]/t[d], n[d], t[d]}' data/raw/headways_2026/Headways_2026/*.csv | sort
```
