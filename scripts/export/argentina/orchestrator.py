"""Argentina export-phase orchestrator.

Validates the intermediate DB unconditionally, then writes the four
published Parquets: `wells.parquet`, `well_operator_history.parquet`,
`well_events.parquet`, and the hive-partitioned `monthly_production`
tree (with a `_files.json` manifest). Finally, idempotently surfaces
the dataset on the static site via `website_integrator`.
"""

import json
from pathlib import Path

import duckdb

from scripts.export.argentina import (
    parquet_writer,
    schema_doc_generator,
    validator,
    website_integrator,
)


def run(
    db_path: Path,
    output_dir: Path,
    website_root: Path | None = None,
) -> None:
    """Run the export pipeline.

    `website_root` is the repo root containing `README.md` and
    `parquet/index.html`. When provided, the static site is patched in
    place to surface the Argentina dataset; when `None`, the website
    integration step is skipped.
    """
    db_path = Path(db_path)
    output_dir = Path(output_dir)

    with duckdb.connect(str(db_path), read_only=True) as con:
        validator.validate(con)
        parquet_writer.write_wells(con, output_dir)
        parquet_writer.write_operator_history(con, output_dir)
        parquet_writer.write_well_events(con, output_dir)
        parquet_writer.write_monthly_production(con, output_dir)
        validator.validate_partitions(con, output_dir)
        schema_doc_generator.generate(con, output_dir)

    if website_root is not None:
        manifest = json.loads(
            (output_dir / "monthly_production" / "_files.json").read_text()
        )
        years = sorted(int(p.split("=", 1)[1].split("/", 1)[0]) for p in manifest)
        website_integrator.integrate(Path(website_root), years)
