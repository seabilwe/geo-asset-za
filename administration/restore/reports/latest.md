# Restore test 2026-11-14 15:23 UTC

- Backup file: `geoasset_za_20261114_172315.dump` (backup log id 1)
- Restored into: `geoasset_za_restore_test` (dropped afterwards: True)
- Duration: 3.5 s
- Result: **PASSED**

| Check | Result | Detail |
|---|---|---|
| Checksum matches backup log | pass | sha256 29620acaafcb6f07… |
| pg_restore completed without errors | pass | 2.8 s |
| Row counts match for every table | pass | 28 tables, 266,201 rows |
| Same number of database objects | pass | tables 28, views 27, functions 13, triggers 21, indexes 61, policies 4 |
| Schema version matches | pass | V015 |
| Spatial data valid and GiST index used | pass | PostGIS 3.4.2, 0 invalid geometries |
| API headline figures match | pass | 11,879 assets, 136 open work orders |
