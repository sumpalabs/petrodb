# Argentina — Dataset Schema

Monthly oil and gas well production for Argentina, organised into four tables by per-`idpozo` volatility. Column identifiers are preserved in Spanish exactly as the source publishes them; all explanatory prose below is in English.

## Four buckets, four tables

The schema splits by **change frequency** within each `idpozo`: static attributes, slowly-changing metadata, events, and a numeric time series. This avoids redundancy across the ~17.6 M monthly rows.

| Table | Bucket | Grain |
|-------|--------|-------|
| `wells` | Static master (< 0.3 % of wells change) | 1 row per `idpozo` |
| `well_operator_history` | Slowly-changing metadata (~67 % change) | 1 row per operator run |
| `well_events` | State events (~74 % change `tipoestado`) | 1 row per transition month |
| `monthly_production` | Monthly numeric series | 1 row per `(idpozo, fecha)` |

## Tables

### `wells`

Static well master. One row per `idpozo` (~85,418 wells, including ~113 orphans from `capitulo-iv` flagged with `has_production = false`).

**Columns:**

| Column | Type | Nullable | PK | Description |
|--------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Integer well identifier (wellbore × producing formation). Primary key of the model. |
| `sigla` | VARCHAR | Yes |  | Human-readable well code (e.g. `YPF.BLO.x-8`). Treated as a label, possibly mutable; not the PK. |
| `formprod` | VARCHAR | Yes |  | Producing formation of the well. Static attribute of `idpozo` (encoded in the ID). |
| `codigopropio` | VARCHAR | Yes |  | Internal code assigned by the operator in the `listado` registry. |
| `nombrepropio` | VARCHAR | Yes |  | Internal name assigned by the operator in the `listado` registry. |
| `area` | VARCHAR | Yes |  | Permit or concession area where the well is located. |
| `cod_area` | VARCHAR | Yes |  | Code of the permit/concession area. |
| `yacimiento` | VARCHAR | Yes |  | Field (yacimiento) where the well is located. |
| `cod_yacimiento` | VARCHAR | Yes |  | Code of the field (yacimiento). |
| `cuenca` | VARCHAR | Yes |  | Sedimentary basin. |
| `provincia` | VARCHAR | Yes |  | Argentine province where the well is located. |
| `idcuenca` | VARCHAR | Yes |  | Basin code. |
| `idprovincia` | VARCHAR | Yes |  | Province code. |
| `formacion` | VARCHAR | Yes |  | Geological formation reported for the well. |
| `cota` | DOUBLE | Yes |  | Surface elevation (m above sea level). |
| `profundidad` | DOUBLE | Yes |  | Final well depth (m). |
| `clasificacion` | VARCHAR | Yes |  | Regulatory well classification (e.g. `Petrolífero`, `Gasífero`). |
| `subclasificacion` | VARCHAR | Yes |  | Regulatory sub-classification. |
| `tipo_recurso` | VARCHAR | Yes |  | Resource type (e.g. `Convencional`, `No Convencional`). |
| `sub_tipo_recurso` | VARCHAR | Yes |  | Resource subtype (e.g. `Shale`, `Tight`). |
| `gasplus` | VARCHAR | Yes |  | Gas Plus programme indicator (capítulo IV source). |
| `proyecto` | VARCHAR | Yes |  | Project the well belongs to (carried over from the production source). |
| `empresa` | VARCHAR | Yes |  | Operator associated with the run (in `wells`: initial operator from the capítulo IV record; in `well_operator_history`: display name of the interval). |
| `coordenadax` | DOUBLE | Yes |  | Well X coordinate (in the system reported by the `listado` registry). |
| `coordenaday` | DOUBLE | Yes |  | Well Y coordinate (in the system reported by the `listado` registry). |
| `geom` | BLOB | Yes |  | Well geometry as WKB (BLOB). Decodable with `ST_GeomFromWKB(geom)` (the `spatial` extension). |
| `adjiv_fecha_inicio_perf` | DATE | Yes |  | Drilling start date (capítulo IV). |
| `adjiv_fecha_fin_perf` | DATE | Yes |  | Drilling end date (capítulo IV). |
| `adjiv_fecha_inicio_term` | DATE | Yes |  | Completion start date (capítulo IV). |
| `adjiv_fecha_fin_term` | DATE | Yes |  | Completion end date (capítulo IV). |
| `adjiv_fecha_inicio` | DATE | Yes |  | Start date reported in the `listado` registry. |
| `adjiv_fecha_fin` | DATE | Yes |  | End date reported in the `listado` registry. |
| `adjiv_fecha_abandono` | DATE | Yes |  | Well abandonment date, if applicable. |
| `adjiv_equipo_utilizar` | VARCHAR | Yes |  | Drilling rig used. |
| `adjiv_capacidad_perf` | DOUBLE | Yes |  | Drilling capacity of the rig. |
| `pet_inicial` | DOUBLE | Yes |  | Initial oil rate from the discovery test (m³/d). |
| `gas_inicial` | DOUBLE | Yes |  | Initial gas rate from the discovery test (Mm³/d). |
| `agua_inicial` | DOUBLE | Yes |  | Initial water rate from the discovery test (m³/d). |
| `iny_agua_inicial` | DOUBLE | Yes |  | Initial water injection reported in the test (m³/d). |
| `iny_gas_inicial` | DOUBLE | Yes |  | Initial gas injection reported in the test (Mm³/d). |
| `iny_otros_inicial` | DOUBLE | Yes |  | Initial injection of other fluids reported in the test. |
| `iny_co2_inicial` | DOUBLE | Yes |  | Initial CO₂ injection reported in the test. |
| `vida_util_inicial` | DOUBLE | Yes |  | Estimated useful life at the time of the initial test (months). |
| `has_production` | BOOLEAN | Yes |  | `true` if the `idpozo` ever appears in monthly production; `false` for capítulo IV orphan wells that never produced. |

---

### `well_operator_history`

Operator history per well (slowly-changing dimension). One row per contiguous run of `idempresa` per `idpozo`. Runs with a NULL `idempresa` are preserved as-is: the absence of an operator is information carried by the source.

**Columns:**

| Column | Type | Nullable | PK | Description |
|--------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Integer well identifier (wellbore × producing formation). Primary key of the model. |
| `idempresa` | VARCHAR | Yes |  | Alphanumeric operator code (`Z001`, `APEA`, …). Stored as VARCHAR. |
| `empresa` | VARCHAR | Yes |  | Operator associated with the run (in `wells`: initial operator from the capítulo IV record; in `well_operator_history`: display name of the interval). |
| `valid_from` | DATE | No | ✓ | First month of the contiguous operator run (DATE, first of month, inclusive). |
| `valid_to` | DATE | Yes |  | Last month of the contiguous operator run (DATE, first of month, inclusive). |

**Foreign keys:**

- `idpozo` → `wells.idpozo`

---

### `well_events`

Operational state events. One row per month in which any of `(tipoestado, tipoextraccion, tipopozo)` changed. The first row of every well is included as the transition into its starting state; single-month flips are not smoothed.

**Columns:**

| Column | Type | Nullable | PK | Description |
|--------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Integer well identifier (wellbore × producing formation). Primary key of the model. |
| `event_date` | DATE | No | ✓ | Month of the operational-state snapshot (DATE, first of month). |
| `tipoestado` | VARCHAR | Yes |  | Operational state of the well (e.g. `Extracción Efectiva`, `Parado Transitoriamente`). |
| `tipoextraccion` | VARCHAR | Yes |  | Extraction method (e.g. `Bombeo Mecánico`, `Surgente`). |
| `tipopozo` | VARCHAR | Yes |  | Well type by fluid (e.g. `Petrolífero`, `Gasífero`, `Inyector`). |

**Foreign keys:**

- `idpozo` → `wells.idpozo`

---

### `monthly_production`

Monthly time series of numeric measurements. One row per `(idpozo, fecha)` for every month in `[first_row, last_row]` per well (gaps are filled with NULL measurements). Hive-partitioned by `anio` (`monthly_production/anio=YYYY/data.parquet`) and internally sorted by `(idpozo, fecha)` so row-group statistics let single-well queries over `httpfs` prune.

**Columns:**

| Column | Type | Nullable | PK | Description |
|--------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Integer well identifier (wellbore × producing formation). Primary key of the model. |
| `fecha` | DATE | No | ✓ | Measurement month (DATE, first day of month, derived from the source's `anio`/`mes`). |
| `prod_pet` | DOUBLE | Yes |  | Monthly oil production (m³). |
| `prod_gas` | DOUBLE | Yes |  | Monthly gas production (Mm³). |
| `prod_agua` | DOUBLE | Yes |  | Monthly water production (m³). |
| `iny_agua` | DOUBLE | Yes |  | Monthly water injection (m³). |
| `iny_gas` | DOUBLE | Yes |  | Monthly gas injection (Mm³). |
| `iny_co2` | DOUBLE | Yes |  | Monthly CO₂ injection. |
| `iny_otro` | DOUBLE | Yes |  | Monthly injection of other fluids. |
| `tef` | DOUBLE | Yes |  | Effective production time for the month — *Tiempo Efectivo de Producción* (hours). |
| `vida_util` | DOUBLE | Yes |  | Declared useful life of the well in the month — *vida útil* (months). |

**Foreign keys:**

- `idpozo` → `wells.idpozo`

---

## Relationships

```
well_operator_history.idpozo → wells.idpozo
well_events.idpozo → wells.idpozo
monthly_production.idpozo → wells.idpozo
```

## Glossary of source codes

Some abbreviations inherited from the source are not obvious at first glance:

| Code | Meaning |
|------|---------|
| `tef` | Effective production time for the month — *Tiempo Efectivo de Producción* (hours). |
| `vida_util` | Declared useful life of the well in the month — *vida útil* (months). |
| `formprod` | Producing formation of the `idpozo`. Static attribute. |
| `idpozo` | Canonical identity: wellbore × producing formation. Primary key of the model. |
| `sigla` | Human-readable well code. Label, possibly mutable, not the PK. |
| `idempresa` | Alphanumeric operator code. **VARCHAR**, not INTEGER. |

## Dropped columns

The following source columns are administrative/audit fields and are not published:

- `geojson`
- `observaciones`
- `idusuario`
- `rectificado`
- `habilitado`
- `fechaingreso`
- `fecha_data`
