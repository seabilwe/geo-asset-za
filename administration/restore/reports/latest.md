# Restore test 2026-11-14 15:09 UTC

- Backup file: `geoasset_za_20261114_170914.dump` (backup log id 1)
- Restored into: `geoasset_za_restore_test` (dropped afterwards: True)
- Duration: 3.4 s
- Result: **PASSED**

| Check | Result | Detail |
|---|---|---|
| Checksum matches backup log | pass | sha256 42a28ed7e216d703… |
| pg_restore completed without errors | pass | 2.7 s |
| Row counts match for every table | pass | 28 tables, 247,502 rows |
| Same number of database objects | pass | tables 28, views 25, functions 13, triggers 21, indexes 61, policies 4 |
| Schema version matches | pass | V013 |
| Spatial data valid and GiST index used | pass | PostGIS 3.4.2, 0 invalid geometries |
| API headline figures match | pass | 11,879 assets, 119 open work orders |
