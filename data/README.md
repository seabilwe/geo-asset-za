# Data

## What is real and what is synthetic

| Data | Source | Real? |
|---|---|---|
| Ward boundaries (City of Tshwane, 2026) | Municipal Demarcation Board | Real |
| Road segments, names and classes | OpenStreetMap | Real locations |
| Traffic signal junctions (OSM signal nodes grouped within 40 m) | OpenStreetMap | Real locations |
| 153 streetlights | OpenStreetMap | Real locations |
| Reservoirs, substations, power lines, parks, playgrounds, sports facilities, clinics, libraries, community centres, public toilets, recycling points | OpenStreetMap | Real locations |
| Stormwater channels | OpenStreetMap waterways | Real locations |
| Culverts | Where OpenStreetMap waterways cross roads | Derived from real data |
| 5,433 streetlights | Generated along the real roads at 30 to 45 m spacing | **Synthetic** |
| Water mains | Generated alongside the real roads | **Synthetic** |
| Fire hydrants | Generated every 180 m along the synthetic mains | **Synthetic** |
| All attributes: install dates, lamp types, pipe materials, capacities, condition, inspections, work orders, costs | Generated with a fixed random seed | **Synthetic** |

Nothing here describes the actual condition, maintenance or spending of any City of Tshwane asset. Facilities are
treated as municipal for the demonstration; their real operators were not checked. Contractor names in work
orders are fictitious.

## Files

- `reference/wards_tsh.geojson`: City of Tshwane wards, simplified to 5 m; wards 56, 82 and 92 flagged as the study area.
- `incoming/osm_*.csv`, `incoming/synthetic_*.csv`: one import batch per file, in the layout of `staging.incoming_assets`.
- `incoming/sample_with_errors.csv`: a batch with one deliberate error per validation rule, used by the tests.
- `source_metadata.json`: OpenStreetMap snapshot time, study wards and random seed.

## Rebuilding the source files

The files are committed so that the database builds without internet access. To rebuild them from fresh downloads:

1. MDB ward boundaries 2026 (shapefile) from the Municipal Demarcation Board, saved in `raw/`.
2. An Overpass API export of the study area (bounding box -25.800, 28.190, -25.730, 28.285) with
   `out body geom`, saved as `raw/osm_hatfield.json`. The query is in `etl/overpass_query.txt`.
3. `pip install geopandas` and run `python etl/build_source_data.py --osm raw/osm_hatfield.json --wards raw/MDB_Wards_2026.shp`.

## Licences

- OpenStreetMap data © OpenStreetMap contributors, available under the Open Database License (ODbL 1.0).
  The OpenStreetMap-derived files in this folder are a derivative database under the same licence.
- Ward boundaries © Municipal Demarcation Board, used with attribution under its terms of use.
- Synthetic data and code: MIT licence (see `LICENSE`).
