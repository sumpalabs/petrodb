"""Petrobras 3W transform-phase orchestrator.

Stages the pinned upstream tag, parses `dataset.ini`, and builds the
`event_types` lookup table inside the intermediate DuckDB. Subsequent
issues (#20 — instances, #21 — wells, #22 — observations) extend this
file with their builders; the staging + ini-parse steps are shared.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from scripts.transform.petrobras_3w import event_types_builder, upstream_stager
from scripts.transform.petrobras_3w.upstream_stager import DatasetIni


def run(db_path: Path, staging_dir: Path) -> DatasetIni:
    """Run the transform pipeline.

    Returns the parsed `DatasetIni` so the export phase can reuse its
    sensor-column glossary without re-parsing.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    upstream_stager.stage(staging_dir)
    dataset_ini = upstream_stager.parse_dataset_ini(staging_dir)

    with duckdb.connect(str(db_path)) as con:
        event_types_builder.build(con, dataset_ini)

    return dataset_ini
