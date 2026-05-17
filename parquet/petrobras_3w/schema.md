# Petrobras 3W — Dataset Schema

Sourced from [`petrobras/3W`](https://github.com/petrobras/3W.git), pinned at git tag `v.1.70.0` (upstream dataset version `2.0.0`). Column identifiers — including the upstream sensor columns with hyphens (`P-PDG`, `ABER-CKGL`, `ESTADO-SDV-GL`, …) — are preserved verbatim; consumers must double-quote those identifiers in SQL. All explanatory prose below is in English.

## Tables

### `event_types`

Static lookup of upstream event classes (`0..9`). Mirrors the `[NAMES]` / per-class `LABEL`/`DESCRIPTION`/`TRANSIENT` sections from upstream `dataset.ini`, plus the two derived columns `transient_code` and `has_normal_prefix` that materialize the NORMAL → TRANSIENT → STEADY arc semantics so consumers do not have to re-derive them from per-observation `class` codes.

**Columns:**

| Column | Type | Nullable | PK | Source | Description |
|--------|------|----------|----|--------|-------------|
| `event_class` | INTEGER | No | ✓ | file body | Integer event class (0 = NORMAL; 1..9 = anomaly categories). On `event_types` this is the primary key; on `instances` it is a foreign key back to `event_types.event_class`. |
| `name` | VARCHAR | Yes |  | file body | Internal name (PascalCase with underscores, e.g. `HYDRATE_IN_PRODUCTION_LINE`). Mirrors upstream's `NAMES` list. |
| `description` | VARCHAR | Yes |  | file body | Human-readable description (e.g. `Hydrate in Production Line`). Mirrors upstream's per-class `DESCRIPTION`. |
| `has_transient` | BOOLEAN | Yes |  | file body | `true` for classes that carry a `TRANSIENT` precursor phase in their `class` column (1, 2, 5, 6, 7, 8, 9). `false` for `NORMAL` (0) and the two events upstream marks `TRANSIENT=False` (3 = Severe Slugging, 4 = Flow Instability). |
| `transient_code` | INTEGER | Yes |  | file body | Per-observation label seen during the transient phase: `event_class + 100` when `has_transient = true`, NULL otherwise. Decodes raw `class` codes such as 101, 105, 108 in the observations time-series. |
| `has_normal_prefix` | BOOLEAN | Yes |  | file body | `true` when instances of this class include a `class = 0` (NORMAL) precursor before the labelled event. Correlates with `has_transient` — events 0, 3, 4 carry only the steady class. |

---

### `wells`

Real-Well master, one row per distinct `well_id` derived from Instances with `well_kind = 'real'` (40 rows at the current upstream pin). Upstream anonymises every physical-well attribute (no basin, field, depth, or location), so the master is an identity-plus-statistics table: count of Instances, total 1-Hz Observations, and the time span across which the Well appears in the corpus. Simulated and drawn Instances have NULL `well_id` and contribute nothing here.

**Columns:**

| Column | Type | Nullable | PK | Source | Description |
|--------|------|----------|----|--------|-------------|
| `well_id` | INTEGER | No | ✓ | file body | Anonymised physical-well integer ID. On `wells` this is the primary key (one row per real Well). On `instances` it is parsed from the `WELL-NNNNN` prefix of `instance_id` and is NULL when `well_kind != 'real'` — a foreign key back to `wells.well_id`. |
| `n_instances` | BIGINT | Yes |  | file body | Number of Instances in the corpus drawn from this real Well. Equal to `COUNT(*) FROM instances WHERE well_kind = 'real' AND well_id = wells.well_id`. |
| `first_ts` | TIMESTAMP | Yes |  | file body | Earliest Instance `start_ts` for the Well. The Well's first appearance in the corpus. |
| `last_ts` | TIMESTAMP | Yes |  | file body | Latest Instance `end_ts` for the Well. The Well's last appearance in the corpus. |
| `n_observations` | BIGINT | Yes |  | file body | Total count of 1-Hz Observations contributed by this Well across all of its Instances. Equal to `SUM(n_rows) FROM instances WHERE well_kind = 'real' AND well_id = wells.well_id`. |

---

### `instances`

One row per upstream Instance file (~2,228 rows). Identifies the Instance (`instance_id`), its provenance (`well_kind`, `well_id`, `source_file`), the operational regime it is framed around (`event_class`), and pre-aggregated per-Instance statistics (`start_ts`, `end_ts`, `duration_s`, `n_rows`, plus four `n_rows_*` counts that partition `n_rows` by `class` value). Corpus-wide balance and labelled-mass queries can run purely against this catalog without scanning the Observations time-series. `source_url` points at the published Observations file for the Instance (the URL pattern is fixed by ADR-0001).

**Columns:**

| Column | Type | Nullable | PK | Source | Description |
|--------|------|----------|----|--------|-------------|
| `instance_id` | VARCHAR | No | ✓ | file body | Primary key. The upstream source filename without `.parquet` (e.g. `WELL-00019_20120601165020`, `SIMULATED_00012`, `DRAWN_00003`). Stable across refreshes. |
| `well_kind` | VARCHAR | Yes |  | file body | Provenance of the Instance: `real` (from a physical Petrobras well), `simulated` (synthetic, generated upstream), or `drawn` (hand-crafted series). `well_id` is non-NULL only when `well_kind = 'real'`. |
| `well_id` | INTEGER | Yes |  | file body | Anonymised physical-well integer ID. On `wells` this is the primary key (one row per real Well). On `instances` it is parsed from the `WELL-NNNNN` prefix of `instance_id` and is NULL when `well_kind != 'real'` — a foreign key back to `wells.well_id`. |
| `event_class` | INTEGER | Yes |  | file body | Integer event class (0 = NORMAL; 1..9 = anomaly categories). On `event_types` this is the primary key; on `instances` it is a foreign key back to `event_types.event_class`. |
| `start_ts` | TIMESTAMP | Yes |  | file body | First `timestamp` value in the upstream Instance file. |
| `end_ts` | TIMESTAMP | Yes |  | file body | Last `timestamp` value in the upstream Instance file. |
| `duration_s` | BIGINT | Yes |  | file body | `end_ts - start_ts` in seconds. Derived from the per-Instance aggregates so consumers do not have to recompute it. |
| `n_rows` | BIGINT | Yes |  | file body | Number of 1-Hz observations in the upstream Instance file. Range across the corpus: ~21k (~6h) to ~243k (~3 days). |
| `n_rows_warmup_null` | DOUBLE | Yes |  | file body | Count of rows where `class IS NULL` — the warmup prefix seen on real-Well Instances (typically ~1 hour) where upstream chose not to assign a label. |
| `n_rows_normal` | DOUBLE | Yes |  | file body | Count of rows where `class = 0` and the Instance's `event_class` is not itself 0 — i.e. the NORMAL precursor before an anomaly. Event 0's `class = 0` rows are its labelled regime itself and are counted under `n_rows_steady` instead, so the four `n_rows_*` columns always partition `n_rows` without overlap. |
| `n_rows_transient` | DOUBLE | Yes |  | file body | Count of rows where `class = event_class + 100` (the developing phase before steady state). NULL when the row's `event_class` has `has_transient = false` in `event_types` (events 0, 3, 4) — the transient phase does not exist by design, distinct from a zero-row count. |
| `n_rows_steady` | DOUBLE | Yes |  | file body | Count of rows where `class = event_class` (the labelled operational regime at steady state). |
| `source_file` | VARCHAR | Yes |  | file body | Upstream parquet filename including `.parquet` extension, for cross-reference with the upstream repository. |
| `source_url` | VARCHAR | Yes |  | file body | URL of the published Observations file for this Instance (`observations/event_class=N/<instance_id>.parquet`). The URL pattern is fixed by ADR-0001 so it can be materialised here before the Observations files exist. |

**Foreign keys:**

- `event_class` → `event_types.event_class`
- `well_id` → `wells.well_id`

---

### `observations`

Per-Instance 1-Hz sensor time-series. Hive-partitioned by `event_class` into `observations/event_class=N/<instance_id>.parquet` — one file per Instance, ~2,228 files in total. Each file preserves the upstream sensor columns verbatim (including hyphens: `P-PDG`, `ABER-CKGL`, `ESTADO-SDV-GL`, …), plus `class`, `state`, and `timestamp`. Three constant columns identify provenance per row: `instance_id`, `well_id`, `well_kind` (RLE-encoded, negligible storage). `event_class` is provided by the hive partition and is NOT stored in the file body. A `_files.json` manifest at the partition root lists every published file's relative path for consumers that prefer enumeration over wildcards.

**Columns:**

| Column | Type | Nullable | PK | Source | Description |
|--------|------|----------|----|--------|-------------|
| `event_class` | INTEGER | No |  | hive partition | Integer event class (0 = NORMAL; 1..9 = anomaly categories). On `event_types` this is the primary key; on `instances` it is a foreign key back to `event_types.event_class`. |
| `timestamp` | TIMESTAMP | No | ✓ | file body | Wall-clock timestamp of the 1-Hz observation. Strictly monotonic within an Instance file at exactly 1-second cadence. |
| `class` | INTEGER | Yes |  | file body | Per-observation regime label: `NULL` during the warmup prefix of a real-Well Instance, `0` for the NORMAL precursor before an anomaly, `event_class` for the labelled steady regime, or `event_class + 100` for the TRANSIENT phase (only on events where `event_types.has_transient = true`). Events 3 and 4 ship only the steady code — no transient and no NORMAL precursor. |
| `state` | INTEGER | Yes |  | file body | Upstream-provided well operational status. Preserved verbatim from the source file; semantics are documented in upstream's `dataset.ini`. |
| `ABER-CKGL` | DOUBLE | Yes |  | file body | Opening of the GLCK (gas lift choke) [%%] |
| `ABER-CKP` | DOUBLE | Yes |  | file body | Opening of the PCK (production choke) [%%] |
| `ESTADO-DHSV` | DOUBLE | Yes |  | file body | State of the DHSV (downhole safety valve) [0, 0.5, or 1] |
| `ESTADO-M1` | DOUBLE | Yes |  | file body | State of the PMV (production master valve) [0, 0.5, or 1] |
| `ESTADO-M2` | DOUBLE | Yes |  | file body | State of the AMV (annulus master valve) [0, 0.5, or 1] |
| `ESTADO-PXO` | DOUBLE | Yes |  | file body | State of the PXO (pig-crossover) valve [0, 0.5, or 1] |
| `ESTADO-SDV-GL` | DOUBLE | Yes |  | file body | State of the gas lift SDV (shutdown valve) [0, 0.5, or 1] |
| `ESTADO-SDV-P` | DOUBLE | Yes |  | file body | State of the production SDV (shutdown valve) [0, 0.5, or 1] |
| `ESTADO-W1` | DOUBLE | Yes |  | file body | State of the PWV (production wing valve) [0, 0.5, or 1] |
| `ESTADO-W2` | DOUBLE | Yes |  | file body | State of the AWV (annulus wing valve) [0, 0.5, or 1] |
| `ESTADO-XO` | DOUBLE | Yes |  | file body | State of the XO (crossover) valve [0, 0.5, or 1] |
| `P-ANULAR` | DOUBLE | Yes |  | file body | Pressure in the well annulus [Pa] |
| `P-JUS-BS` | DOUBLE | Yes |  | file body | Downstream pressure of the SP (service pump) [Pa] |
| `P-JUS-CKGL` | DOUBLE | Yes |  | file body | Downstream pressure of the GLCK (gas lift choke) [Pa] |
| `P-JUS-CKP` | DOUBLE | Yes |  | file body | Downstream pressure of the PCK (production choke) [Pa] |
| `P-MON-CKGL` | DOUBLE | Yes |  | file body | Upstream pressure of the GLCK (gas lift choke) [Pa] |
| `P-MON-CKP` | DOUBLE | Yes |  | file body | Upstream pressure of the PCK (production choke) [Pa] |
| `P-MON-SDV-P` | DOUBLE | Yes |  | file body | Upstream pressure of the production SDV (shutdown valve) [Pa] |
| `P-PDG` | DOUBLE | Yes |  | file body | Downhole pressure at the PDG (permanent downhole gauge) [Pa] |
| `PT-P` | DOUBLE | Yes |  | file body | Subsea Xmas-tree pressure downstream of the PWV (production wing valve) in the production line [Pa] |
| `P-TPT` | DOUBLE | Yes |  | file body | Subsea Xmas-tree pressure at the TPT (temperature and pressure transducer) [Pa] |
| `QBS` | DOUBLE | Yes |  | file body | Flow rate at the SP (service pump) [m3/s] |
| `QGL` | DOUBLE | Yes |  | file body | Gas lift flow rate [m3/s] |
| `T-JUS-CKP` | DOUBLE | Yes |  | file body | Downstream temperature of the PCK (production choke) [oC] |
| `T-MON-CKP` | DOUBLE | Yes |  | file body | Upstream temperature of the PCK (production choke) [oC] |
| `T-PDG` | DOUBLE | Yes |  | file body | Downhole temperature at the PDG (permanent downhole gauge) [oC] |
| `T-TPT` | DOUBLE | Yes |  | file body | Subsea Xmas-tree temperature at the TPT (temperature and pressure transducer) [oC] |
| `instance_id` | VARCHAR | No | ✓ | file body | Primary key. The upstream source filename without `.parquet` (e.g. `WELL-00019_20120601165020`, `SIMULATED_00012`, `DRAWN_00003`). Stable across refreshes. |
| `well_id` | INTEGER | Yes |  | file body | Anonymised physical-well integer ID. On `wells` this is the primary key (one row per real Well). On `instances` it is parsed from the `WELL-NNNNN` prefix of `instance_id` and is NULL when `well_kind != 'real'` — a foreign key back to `wells.well_id`. |
| `well_kind` | VARCHAR | Yes |  | file body | Provenance of the Instance: `real` (from a physical Petrobras well), `simulated` (synthetic, generated upstream), or `drawn` (hand-crafted series). `well_id` is non-NULL only when `well_kind = 'real'`. |

**Foreign keys:**

- `instance_id` → `instances.instance_id`
- `event_class` → `event_types.event_class`
- `well_id` → `wells.well_id`

---

## Sensor-column glossary (Observations time-series)

Mirrored verbatim from upstream `dataset.ini`'s `PARQUET_FILE_PROPERTIES` section. These columns appear in every `observations/event_class=N/<instance_id>.parquet` file body; the glossary is repeated here in a single table for quick reference.

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
