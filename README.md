# PetroData Repository

Open petroleum datasets in Parquet format for data science and machine learning applications.

## Datasets

### Volve Production Data
Production metrics from the Equinor Volve oil field (2007-2016):
- **7 wells** with daily and monthly production records
- **15,634 daily measurements** - pressure, temperature, oil/gas/water volumes
- **526 monthly aggregates** - production volumes in Sm3

### FORCE 2020 Well Logs
Well log data from 108 wells in the Norwegian Continental Shelf:
- **29 columns** of petrophysical measurements per well
- **Log curves**: Gamma Ray (GR), Density (RHOB), Porosity (NPHI), Resistivity, Sonic
- **Lithofacies classifications** for machine learning applications

<!-- argentina:begin -->

### Argentina Production Data
Monthly oil and gas production for ~85,418 wells in Argentina (2006–present),
sourced from the Secretaría de Energía public datasets:
- **wells.parquet** — static well master (~85K rows, Spanish column names)
- **well_operator_history.parquet** — slowly-changing operator transfers
- **well_events.parquet** — operational state transitions
- **monthly_production/** — hive-partitioned by `anio`, ~17.6M rows total

Aggregate 2023 production by basin, joining `wells` to the partitioned
monthly time series:

```python
import duckdb

result = duckdb.sql("""
    SELECT w.cuenca,
           SUM(m.prod_pet) AS oil_m3,
           SUM(m.prod_gas) AS gas_mm3
    FROM 'https://dev-petrodb.ocortez.com/argentina/wells.parquet' w
    JOIN read_parquet(
      'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet',
      hive_partitioning = true
    ) m USING (idpozo)
    WHERE m.anio = 2023
    GROUP BY w.cuenca
    ORDER BY oil_m3 DESC
""").df()
```

Full per-column English docs (Spanish column identifiers preserved), the
four-bucket rationale, and three more canonical query patterns live in
[`parquet/argentina/README.md`](parquet/argentina/README.md).

<!-- argentina:end -->

<!-- petrobras_3w:begin -->

### Petrobras 3W Dataset
Labelled 1-Hz sensor-data windows from the Petrobras 3W dataset, sliced
into per-Instance Parquet files. Pinned at upstream git tag `v.1.70.0`
(dataset version `2.0.0`). This release publishes the
event-class lookup, the real-Well master, the full Instance catalog, and
the per-Instance Observations time-series (hive-partitioned by event class).

Measure the labelled-data balance across the corpus from the catalog alone
(no Observations scan needed):

```python
import duckdb

base = 'https://dev-petrodb.ocortez.com/petrobras_3w'
result = duckdb.sql(f"""
    SELECT
        et.event_class,
        et.description,
        COUNT(*)             AS n_instances,
        SUM(i.n_rows)        AS n_observations
    FROM '{base}/instances.parquet' i
    JOIN '{base}/event_types.parquet' et
        ON et.event_class = i.event_class
    GROUP BY et.event_class, et.description
    ORDER BY et.event_class
""").df()
```

Full per-column English docs (including the 27-sensor glossary mirrored
from upstream `dataset.ini`) live in
[`parquet/petrobras_3w/README.md`](parquet/petrobras_3w/README.md). Upstream
source: <https://github.com/petrobras/3W.git> (CC BY 4.0).

<!-- petrobras_3w:end -->

## Access Data

Browse and download files at: **https://dev-petrodb.ocortez.com**

## Quick Start

Query directly with DuckDB (no download required):

```python
import duckdb

conn = duckdb.connect()

# Query Volve production data
volve = conn.execute("""
    SELECT
        w.wellbore_name,
        SUM(d.oil_volume) as total_oil,
        SUM(d.gas_volume) as total_gas
    FROM 'https://dev-petrodb.ocortez.com/volve/daily_production.parquet' d
    JOIN 'https://dev-petrodb.ocortez.com/volve/wells.parquet' w
        ON d.npd_wellbore_code = w.npd_wellbore_code
    GROUP BY w.wellbore_name
    ORDER BY total_oil DESC
""").fetchdf()

# Query Force 2020 well logs
force = conn.execute("""
    SELECT
        WELL,
        AVG(GR) as avg_gamma_ray,
        AVG(RHOB) as avg_density,
        COUNT(*) as samples
    FROM 'https://dev-petrodb.ocortez.com/force_2020/wells/15-9-13.parquet'
    GROUP BY WELL
""").fetchdf()

# Query all 108 wells at once with wildcard
all_wells = conn.execute("""
    SELECT WELL, FORMATION, COUNT(*) as samples
    FROM 'https://dev-petrodb.ocortez.com/force_2020/wells/*.parquet'
    WHERE FORMATION IS NOT NULL
    GROUP BY WELL, FORMATION
    ORDER BY WELL, samples DESC
""").fetchdf()
```

Or download files locally and query:

```python
import duckdb

conn = duckdb.connect()

# Query local Volve files
result = conn.execute("""
    SELECT * FROM 'parquet/volve/daily_production.parquet'
    WHERE date BETWEEN '2008-01-01' AND '2008-12-31'
""").fetchdf()

# Query local Force 2020 files
well_data = conn.execute("""
    SELECT * FROM 'parquet/force_2020/wells/15-9-13.parquet'
    WHERE DEPTH_MD > 3000
""").fetchdf()
```

## Project Structure

```
parquet/
├── volve/                    # Volve production data
│   ├── daily_production.parquet
│   ├── monthly_production.parquet
│   ├── wells.parquet
│   └── schema.json
└── force_2020/               # FORCE 2020 well logs
    └── wells/                # 108 well files
        ├── 15-9-13.parquet
        ├── 34-10-16_R.parquet
        └── ... (106 more)
```

## Acknowledgments

- **Equinor** - Volve field dataset
- **FORCE (Norwegian Oil and Gas Association)** and **Xeek** - FORCE 2020 ML Competition dataset

Both datasets are provided for research and educational purposes.

## License

See original license terms:
- Volve: https://cdn.equinor.com/files/h61q9gi9/global/de6532f6134b9a953f6c41bac47a0c055a3712d3.pdf
- FORCE 2020: https://xeek.ai/challenges/force-well-logs
