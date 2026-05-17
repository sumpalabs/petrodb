# Petrobras 3W — Dataset Schema

Sourced from [`petrobras/3W`](https://github.com/petrobras/3W.git), pinned at git tag `v.1.70.0` (upstream dataset version `2.0.0`). Column identifiers — including the upstream sensor columns with hyphens (`P-PDG`, `ABER-CKGL`, `ESTADO-SDV-GL`, …) — are preserved verbatim; consumers must double-quote those identifiers in SQL. All explanatory prose below is in English.

## Tables

### `event_types`

Static lookup of upstream event classes (`0..9`). Mirrors the `[NAMES]` / per-class `LABEL`/`DESCRIPTION`/`TRANSIENT` sections from upstream `dataset.ini`, plus the two derived columns `transient_code` and `has_normal_prefix` that materialize the NORMAL → TRANSIENT → STEADY arc semantics so consumers do not have to re-derive them from per-observation `class` codes.

**Columns:**

| Column | Type | Nullable | PK | Description |
|--------|------|----------|----|-------------|
| `event_class` | INTEGER | No | ✓ | Integer event class (0 = NORMAL; 1..9 = anomaly categories). Primary key. Matches upstream's `LABEL`. |
| `name` | VARCHAR | Yes |  | Internal name (PascalCase with underscores, e.g. `HYDRATE_IN_PRODUCTION_LINE`). Mirrors upstream's `NAMES` list. |
| `description` | VARCHAR | Yes |  | Human-readable description (e.g. `Hydrate in Production Line`). Mirrors upstream's per-class `DESCRIPTION`. |
| `has_transient` | BOOLEAN | Yes |  | `true` for classes that carry a `TRANSIENT` precursor phase in their `class` column (1, 2, 5, 6, 7, 8, 9). `false` for `NORMAL` (0) and the two events upstream marks `TRANSIENT=False` (3 = Severe Slugging, 4 = Flow Instability). |
| `transient_code` | INTEGER | Yes |  | Per-observation label seen during the transient phase: `event_class + 100` when `has_transient = true`, NULL otherwise. Decodes raw `class` codes such as 101, 105, 108 in the observations time-series. |
| `has_normal_prefix` | BOOLEAN | Yes |  | `true` when instances of this class include a `class = 0` (NORMAL) precursor before the labelled event. Correlates with `has_transient` — events 0, 3, 4 carry only the steady class. |

---

## Sensor-column glossary (Observations time-series)

Mirrored verbatim from upstream `dataset.ini`'s `PARQUET_FILE_PROPERTIES` section. These columns will appear in `observations/event_class=N/<instance_id>.parquet` once issue #22 lands; the glossary is published here so consumers can plan queries against the table layout in advance.

| Column | Description |
|--------|-------------|
| `timestamp` | Instant at which observation was generated |
| `ABER-CKGL` | Opening of the GLCK (gas lift choke) [%%] |
| `ABER-CKP` | Opening of the PCK (production choke) [%%] |
| `ESTADO-DHSV` | State of the DHSV (downhole safety valve) [0, 0.5, or 1] |
| `ESTADO-M1` | State of the PMV (production master valve) [0, 0.5, or 1] |
| `ESTADO-M2` | State of the AMV (annulus master valve) [0, 0.5, or 1] |
| `ESTADO-PXO` | State of the PXO (pig-crossover) valve [0, 0.5, or 1] |
| `ESTADO-SDV-GL` | State of the gas lift SDV (shutdown valve) [0, 0.5, or 1] |
| `ESTADO-SDV-P` | State of the production SDV (shutdown valve) [0, 0.5, or 1] |
| `ESTADO-W1` | State of the PWV (production wing valve) [0, 0.5, or 1] |
| `ESTADO-W2` | State of the AWV (annulus wing valve) [0, 0.5, or 1] |
| `ESTADO-XO` | State of the XO (crossover) valve [0, 0.5, or 1] |
| `P-ANULAR` | Pressure in the well annulus [Pa] |
| `P-JUS-BS` | Downstream pressure of the SP (service pump) [Pa] |
| `P-JUS-CKGL` | Downstream pressure of the GLCK (gas lift choke) [Pa] |
| `P-JUS-CKP` | Downstream pressure of the PCK (production choke) [Pa] |
| `P-MON-CKGL` | Upstream pressure of the GLCK (gas lift choke) [Pa] |
| `P-MON-CKP` | Upstream pressure of the PCK (production choke) [Pa] |
| `P-MON-SDV-P` | Upstream pressure of the production SDV (shutdown valve) [Pa] |
| `P-PDG` | Downhole pressure at the PDG (permanent downhole gauge) [Pa] |
| `PT-P` | Subsea Xmas-tree pressure downstream of the PWV (production wing valve) in the production line [Pa] |
| `P-TPT` | Subsea Xmas-tree pressure at the TPT (temperature and pressure transducer) [Pa] |
| `QBS` | Flow rate at the SP (service pump) [m3/s] |
| `QGL` | Gas lift flow rate [m3/s] |
| `T-JUS-CKP` | Downstream temperature of the PCK (production choke) [oC] |
| `T-MON-CKP` | Upstream temperature of the PCK (production choke) [oC] |
| `T-PDG` | Downhole temperature at the PDG (permanent downhole gauge) [oC] |
| `T-TPT` | Subsea Xmas-tree temperature at the TPT (temperature and pressure transducer) [oC] |
| `class` | Label of the observation |
| `state` | Well operational status |
