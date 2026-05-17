"""Petrobras 3W export-phase orchestrator.

Validates the intermediate DB unconditionally (and emits the pinned
upstream identity to the validation log), then writes the published
parquets, the schema documentation, and idempotently surfaces the
dataset on the static site.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from scripts.export.petrobras_3w import (
    parquet_writer,
    schema_doc_generator,
    validator,
    website_integrator,
)
from scripts.transform.petrobras_3w.upstream_stager import DatasetIni


def run(
    db_path: Path,
    output_dir: Path,
    dataset_ini: DatasetIni,
    website_root: Path | None = None,
) -> None:
    """Run the export pipeline.

    ``dataset_ini`` is the parsed projection of upstream `dataset.ini`,
    returned by `scripts.transform.petrobras_3w.orchestrator.run`. It
    carries the dataset semver (asserted against the pin) and the
    sensor-column glossary used in schema.md.

    ``website_root`` is the repo root containing `README.md` and
    `parquet/index.html`. When provided, the static site is patched in
    place to surface the Petrobras 3W dataset; when None, the website
    integration step is skipped.
    """
    db_path = Path(db_path)
    output_dir = Path(output_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        validator.validate(con, dataset_ini)
        parquet_writer.write_event_types(con, output_dir)
        parquet_writer.write_instances(con, output_dir)
        parquet_writer.write_wells(con, output_dir)
        schema_doc_generator.generate(con, output_dir, dataset_ini)

    if website_root is not None:
        website_integrator.integrate(Path(website_root))
