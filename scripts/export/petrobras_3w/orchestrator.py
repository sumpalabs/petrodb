"""Petrobras 3W export-phase orchestrator.

Validates the intermediate DB unconditionally (and emits the pinned
upstream identity to the validation log), then writes the published
parquets, runs the post-write parity suite against the upstream staged
tree, writes the schema documentation, and idempotently surfaces the
dataset on the static site.

Two correctness gates run in sequence: the pre-write ``validator`` covers
structural invariants of the intermediate DB; the post-write ``parity``
suite proves the written bytes round-trip the upstream bytes 1:1. A
parity divergence aborts publish before the static-site tab is patched,
so a broken export never becomes visible to consumers.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from scripts.export.petrobras_3w import (
    parity,
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
    staging_dir: Path,
    website_root: Path | None = None,
) -> None:
    """Run the export pipeline.

    ``dataset_ini`` is the parsed projection of upstream `dataset.ini`,
    returned by `scripts.transform.petrobras_3w.orchestrator.run`. It
    carries the dataset semver (asserted against the pin) and the
    sensor-column glossary used in schema.md.

    ``staging_dir`` is the staged upstream tree. The Observations writer
    reads one parquet per Instance from `<staging_dir>/dataset/N/` so
    the catalog plus the source files together are sufficient to emit
    `observations/event_class=N/<instance_id>.parquet` without holding
    the full corpus in RAM. The same tree is the upstream source-of-
    truth for the post-write ``parity`` suite.

    ``website_root`` is the repo root containing `README.md` and
    `parquet/index.html`. When provided, the static site is patched in
    place to surface the Petrobras 3W dataset; when None, the website
    integration step is skipped. Both site-patching paths run only after
    ``parity.check`` returns, so a divergence keeps the existing site
    intact.
    """
    db_path = Path(db_path)
    output_dir = Path(output_dir)
    staging_dir = Path(staging_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        validator.validate(con, dataset_ini)
        parquet_writer.write_event_types(con, output_dir)
        parquet_writer.write_instances(con, output_dir)
        parquet_writer.write_wells(con, output_dir)
        parquet_writer.write_observations(con, output_dir, staging_dir)

    parity.check(staging_dir, output_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        schema_doc_generator.generate(con, output_dir, dataset_ini)

    if website_root is not None:
        website_integrator.integrate(Path(website_root))
