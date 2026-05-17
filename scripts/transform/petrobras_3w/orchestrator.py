"""Petrobras 3W transform-phase orchestrator.

Stages the pinned upstream tag, parses `dataset.ini`, builds the
`event_types` lookup, aggregates every staged instance file into the
`instances` catalog, and derives the `wells` master from those real-Well
instances. The remaining slice (#22 — observations) extends this file
with the per-Instance Observations writer; staging + ini-parse + the
catalog tables are shared.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from scripts.transform.petrobras_3w import (
    event_types_builder,
    instances_builder,
    upstream_stager,
    wells_builder,
)
from scripts.transform.petrobras_3w.upstream_stager import DatasetIni


def run(db_path: Path, staging_dir: Path) -> DatasetIni:
    """Run the transform pipeline.

    Returns the parsed `DatasetIni` so the export phase can reuse its
    sensor-column glossary without re-parsing.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    staging_dir = Path(staging_dir)
    upstream_stager.stage(staging_dir)
    dataset_ini = upstream_stager.parse_dataset_ini(staging_dir)

    with duckdb.connect(str(db_path)) as con:
        event_types_builder.build(con, dataset_ini)
        instances_builder.build(con, staging_dir)
        wells_builder.build(con)

    return dataset_ini
