"""Shared fixture helpers for the Petrobras 3W pipeline tests.

The smoke test populates a fixture upstream tree (just `dataset.ini`)
into a per-test `tmp_path` and short-circuits the shallow-clone. The
transform pipeline reads per-Instance parquet files from
`<staging>/dataset/N/*.parquet`, so each test that exercises the
orchestrator needs a small set of those files alongside the ini.

`build_instance_parquets` materializes them in a deterministic, minimal
shape:

- 5 *primary* instances covering 5 event classes across the three
  `well_kind`s (real / simulated / drawn):
  - Event 0 (NORMAL, has_transient=false): single 10-row file, all class=0.
  - Event 1 (has_transient=true): NORMAL warmup-null + NORMAL + TRANSIENT
    (101) + STEADY (1) arc.
  - Event 3 (Severe Slugging, has_transient=false): steady-only file.
  - Event 8 (Hydrate in Production Line, simulated, has_transient=true):
    no warmup-null because well_kind != real; NORMAL + TRANSIENT (108) +
    STEADY (8).
  - Event 9 (Hydrate in Service Line, drawn, has_transient=true):
    TRANSIENT (109) + STEADY (9) — no NORMAL prefix.
- 37 *padding* real-Well event-0 fixtures (one 1-row file per well) so
  the total distinct real well count matches the upstream pin of 40
  (`00001..00016`, `00019..00042` — IDs 17 and 18 are absent upstream
  and stay absent here). The well-count is what `validator` rule 7
  pins on, and using the exact upstream gap means the happy-path tests
  exercise rule 7 against a realistic catalog.

Each file carries `timestamp`, `class`, `state`, plus one hyphenated
sensor column (`P-PDG`) so the Observations writer's column-name
fidelity (rule from CONTEXT.md: hyphens preserved) is exercised end-
to-end. The full 27-sensor production schema is broader; the writer
preserves whatever the source carries, so a single representative
hyphenated column is enough to assert the policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb

from scripts.transform.petrobras_3w.upstream_stager import parse_dataset_ini


@dataclass(frozen=True)
class _InstanceSpec:
    event_class: int
    filename: str
    classes: tuple[int | None, ...]


_PRIMARY_SPECS: tuple[_InstanceSpec, ...] = (
    _InstanceSpec(
        event_class=0,
        filename="WELL-00001_20120101000000.parquet",
        classes=(0,) * 10,
    ),
    _InstanceSpec(
        event_class=1,
        filename="WELL-00002_20120102000000.parquet",
        # 3 warmup-NULL + 4 NORMAL (0) + 2 TRANSIENT (101) + 3 STEADY (1)
        classes=(
            None,
            None,
            None,
            0,
            0,
            0,
            0,
            101,
            101,
            1,
            1,
            1,
        ),
    ),
    _InstanceSpec(
        event_class=3,
        filename="WELL-00003_20120103000000.parquet",
        classes=(3,) * 8,
    ),
    _InstanceSpec(
        event_class=8,
        filename="SIMULATED_00001.parquet",
        # 2 NORMAL (0) + 2 TRANSIENT (108) + 1 STEADY (8)
        classes=(0, 0, 108, 108, 8),
    ),
    _InstanceSpec(
        event_class=9,
        filename="DRAWN_00001.parquet",
        # 3 TRANSIENT (109) + 3 STEADY (9), no NORMAL prefix
        classes=(109, 109, 109, 9, 9, 9),
    ),
)

# Real-Well IDs that exist in the upstream pin (`v.1.70.0`, dataset
# version `2.0.0`) but are not covered by the five primary fixtures.
# Matches the upstream gap at IDs 17 and 18 exactly so the total count
# reproduces the pinned 40 distinct real wells (rule 7 in the validator).
_PADDING_REAL_WELL_IDS: tuple[int, ...] = (
    *range(4, 17),  # 00004 .. 00016
    *range(19, 43),  # 00019 .. 00042
)


def _padding_specs() -> tuple[_InstanceSpec, ...]:
    """Single-row event-0 instances for the wells that the primary fixtures
    do not cover. Keeps the per-file row count at 1 so the validator's
    bucket accounting (rule from #20) and the wells aggregates stay
    straightforward to reason about in tests.
    """
    return tuple(
        _InstanceSpec(
            event_class=0,
            filename=f"WELL-{well_id:05d}_20120101000000.parquet",
            classes=(0,),
        )
        for well_id in _PADDING_REAL_WELL_IDS
    )


_INSTANCE_SPECS: tuple[_InstanceSpec, ...] = _PRIMARY_SPECS + _padding_specs()


def _sensor_columns(staging_dir: Path) -> tuple[str, ...]:
    """Return upstream's sensor columns in `PARQUET_FILE_PROPERTIES` order,
    excluding the ones the fixture writes explicitly (`timestamp`, `class`,
    `state`).
    """
    ini = parse_dataset_ini(staging_dir)
    return tuple(
        column
        for column in ini.sensor_descriptions
        if column not in {"timestamp", "class", "state"}
    )


def build_instance_parquets(staging_dir: Path) -> None:
    """Write the minimal per-Instance parquet fixtures under `<staging>/dataset/N/`.

    Idempotent: re-running with an existing tree overwrites in place. Uses
    DuckDB so the fixture format matches what `read_parquet` will see in
    the pipeline (timestamp column written as a TIMESTAMP).

    Carries all 27 upstream sensor columns from `dataset.ini`'s
    `PARQUET_FILE_PROPERTIES`, so the reflected schema docs published from
    a fixture-driven run match production's column inventory. Most sensor
    values are constant placeholders; only `P-PDG` varies so the
    column-name fidelity policy and parity sensor-aggregate checks have
    distinguishable data to compare across upstream → catalog → published.
    """
    dataset_root = Path(staging_dir) / "dataset"
    sensor_cols = _sensor_columns(staging_dir)
    sensor_col_ddl = ",".join(f'    "{name}" DOUBLE' for name in sensor_cols)
    placeholders = ",".join(["?"] * (3 + len(sensor_cols)))
    con = duckdb.connect()
    try:
        for spec in _INSTANCE_SPECS:
            class_dir = dataset_root / str(spec.event_class)
            class_dir.mkdir(parents=True, exist_ok=True)
            target = class_dir / spec.filename
            con.execute("DROP TABLE IF EXISTS staging_rows")
            con.execute(
                "CREATE TEMP TABLE staging_rows ("
                '    "timestamp" TIMESTAMP,'
                '    "class"     INTEGER,'
                '    "state"     INTEGER,'
                f"{sensor_col_ddl}"
                ")"
            )
            rows = [
                (
                    f"2012-01-01 00:00:{i:02d}",
                    cls,
                    0,
                    *(
                        # `P-PDG` varies row-to-row so sensor aggregates
                        # diverge under any byte-level mutation in the
                        # parity tests; other sensors stay constant.
                        1.0e7 + i if name == "P-PDG" else 0.0
                        for name in sensor_cols
                    ),
                )
                for i, cls in enumerate(spec.classes)
            ]
            con.executemany(
                f"INSERT INTO staging_rows VALUES ({placeholders})",
                rows,
            )
            con.execute(
                f'COPY (SELECT * FROM staging_rows ORDER BY "timestamp") '
                f"TO '{target}' (FORMAT PARQUET)"
            )
    finally:
        con.close()
