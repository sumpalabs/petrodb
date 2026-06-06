# FORCE 2020 — Dataset Schema

Wireline and LWD well logs from 108 Norwegian North Sea wells, with an interpreted lithology label per sample. Sourced from the [FORCE 2020 Machine Predicted Lithology challenge](https://github.com/bolgebrygg/Force-2020-Machine-Learning-competition). Column identifiers are preserved verbatim from the source (uppercase log mnemonics such as `GR`, `RHOB`, `NPHI`); the reserved word `GROUP` must be double-quoted in SQL. All explanatory prose below is in English.

## Tables

### `wells`

One row per ~0.15 m log sample (1,307,297 rows across 108 wells). Published as one Parquet file per well under `wells/<well>.parquet` — a flat multi-parquet table per [ADR-0004](../../docs/adr/0004-multi-parquet-table-convention.md): no Hive partition key, with file discovery via `wells/_files.json`. The primary key is `(WELL, DEPTH_MD)`.

A few raw curves (notably `SP`, `ROPA`, `RXO`) carry upstream sentinel placeholders such as `-999`, `-999.25`, and `-999.9` for missing samples. These are preserved verbatim from the source; treat them as NULL rather than as measured values.

**Columns:**

| Column | Type | Unit | Nullable | PK | Description |
|--------|------|------|----------|----|-------------|
| `WELL` | VARCHAR | — | No | ✓ | Well identifier in NPD notation (e.g. `15/9-13`). With `DEPTH_MD` forms the primary key. The per-well Parquet file is named after this value with `/` → `-` and spaces → `_` (`15/9-13` → `15-9-13.parquet`); per ADR-0004 the leaf filename carries no query semantics. |
| `DEPTH_MD` | DOUBLE | m | No | ✓ | Measured depth along the wellbore — the log sample index, on a regular ~0.15 m step. Strictly increasing within a well; with `WELL` forms the primary key. |
| `X_LOC` | DOUBLE | m | Yes |  | Easting of the sample in the survey projection (UTM zone 31N, ED50; Norwegian North Sea). |
| `Y_LOC` | DOUBLE | m | Yes |  | Northing of the sample in the survey projection (UTM zone 31N, ED50). |
| `Z_LOC` | DOUBLE | m | Yes |  | True vertical depth subsea (TVDSS) of the sample; negative downward below mean sea level. |
| `GROUP` | VARCHAR | — | Yes |  | Lithostratigraphic group at the sample depth, in NPD nomenclature (e.g. `HORDALAND GP.`, `SHETLAND GP.`). 14 distinct groups. |
| `FORMATION` | VARCHAR | — | Yes |  | Lithostratigraphic formation at the sample depth, in NPD nomenclature (e.g. `Draupne Fm.`, `Balder Fm.`). 69 distinct formations; a finer subdivision of `GROUP`. |
| `CALI` | DOUBLE | in | Yes |  | Caliper — measured borehole diameter. |
| `RSHA` | DOUBLE | ohm·m | Yes |  | Shallow-reading resistivity (flushed/invaded zone). |
| `RMED` | DOUBLE | ohm·m | Yes |  | Medium-reading resistivity (transition zone). |
| `RDEP` | DOUBLE | ohm·m | Yes |  | Deep-reading resistivity (virgin/uninvaded zone) — the primary true resistivity (Rt) curve for water-saturation analysis. |
| `RHOB` | DOUBLE | g/cm³ | Yes |  | Bulk density from the formation density tool. |
| `GR` | DOUBLE | gAPI | Yes |  | Total gamma ray — the principal shaliness and lithology indicator. |
| `SGR` | DOUBLE | gAPI | Yes |  | Spectral (total) gamma ray from the spectral GR tool. Sparsely recorded (~5% of samples). |
| `NPHI` | DOUBLE | v/v | Yes |  | Neutron porosity (limestone-calibrated, fractional). Read against `RHOB` for the density–neutron crossover. |
| `PEF` | DOUBLE | b/e | Yes |  | Photoelectric absorption factor — a mineralogy/lithology indicator. |
| `DTC` | DOUBLE | µs/ft | Yes |  | Compressional-wave slowness (delta-T compressional) from the sonic tool. Used for porosity and synthetic seismic ties. |
| `SP` | DOUBLE | mV | Yes |  | Spontaneous potential. |
| `BS` | DOUBLE | in | Yes |  | Bit size — nominal hole diameter drilled; the reference gauge for caliper washout (`DCAL`). |
| `ROP` | DOUBLE | m/h | Yes |  | Rate of penetration recorded while drilling. |
| `DTS` | DOUBLE | µs/ft | Yes |  | Shear-wave slowness (delta-T shear). Sparsely recorded (~17% of samples); paired with `DTC` for geomechanics and Vp/Vs. |
| `DCAL` | DOUBLE | in | Yes |  | Differential caliper (`CALI − BS`): positive indicates washout, negative indicates mudcake or hole swelling. |
| `DRHO` | DOUBLE | g/cm³ | Yes |  | Density correction curve from the density tool — a borehole-quality flag for `RHOB`. |
| `MUDWEIGHT` | DOUBLE | g/cm³ | Yes |  | Drilling-mud density (specific gravity). |
| `RMIC` | DOUBLE | ohm·m | Yes |  | Micro-resistivity (microlog-class flushed-zone reading). |
| `ROPA` | DOUBLE | m/h | Yes |  | Averaged rate of penetration. |
| `RXO` | DOUBLE | ohm·m | Yes |  | Flushed-zone resistivity (Rxo); read against `RDEP` to gauge invasion and movable hydrocarbons. |
| `FORCE_2020_LITHOFACIES_LITHOLOGY` | BIGINT | code | Yes |  | Interpreted lithology label — the prediction target of the FORCE 2020 contest. Twelve classes encoded as integer keys; see the lithology code table below. |
| `dataset` | VARCHAR | — | Yes |  | Competition split the row belongs to: `train` or `test`. |

**Primary key:** `(WELL, DEPTH_MD)`

---

## Lithology code table

`FORCE_2020_LITHOFACIES_LITHOLOGY` encodes the interpreted lithology as an integer key. The twelve classes and their corpus sample counts:

| Code | Lithology | Samples |
|------|-----------|---------|
| 30000 | Sandstone | 192,985 |
| 65000 | Shale | 804,778 |
| 65030 | Sandstone/Shale | 168,013 |
| 70000 | Limestone | 61,118 |
| 70032 | Chalk | 11,138 |
| 74000 | Dolomite | 2,104 |
| 80000 | Marl | 36,635 |
| 86000 | Anhydrite | 1,210 |
| 88000 | Halite | 8,213 |
| 90000 | Coal | 4,510 |
| 93000 | Basement | 103 |
| 99000 | Tuff | 16,490 |

