"""Write Petrobras 3W destination tables to Parquet via pure DuckDB SQL.

This slice emits `event_types.parquet` (#19), `instances.parquet`
(#20), `wells.parquet` (#21), and the hive-partitioned `observations/`
tree plus its `_files.json` manifest (#22).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import duckdb

# Soft-warn when a single Observations parquet exceeds this size — rule 9
# from CONTEXT.md's pre-publish validation list. Keeps individual files
# under Cloudflare's edge-cache file-size target so the static site stays
# zero-cost. A warning rather than a hard failure: oversize files publish,
# but the operator gets a heads-up.
OBSERVATIONS_FILE_SIZE_SOFT_LIMIT_MB = 50


def write_event_types(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "event_types.parquet"
    con.execute(
        f"COPY (SELECT * FROM event_types ORDER BY event_class) "
        f"TO '{target}' (FORMAT PARQUET)"
    )


def write_instances(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "instances.parquet"
    con.execute(
        f"COPY (SELECT * FROM instances ORDER BY event_class, instance_id) "
        f"TO '{target}' (FORMAT PARQUET)"
    )


def write_wells(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "wells.parquet"
    con.execute(
        f"COPY (SELECT * FROM wells ORDER BY well_id) TO '{target}' (FORMAT PARQUET)"
    )


def write_observations(
    con: duckdb.DuckDBPyConnection,
    output_dir: Path,
    staging_dir: Path,
    logger: logging.Logger | None = None,
) -> None:
    """Write per-Instance Observations parquets + a `_files.json` manifest.

    Layout (ADR-0001):
        observations/event_class=N/<instance_id>.parquet     # one per Instance
        observations/_files.json                              # manifest

    Each file preserves the upstream columns verbatim (27 hyphenated
    sensor columns + `class` + `state` + `timestamp`) and adds three
    constant columns derived from the Instance catalog: `instance_id`,
    `well_id`, `well_kind`. `event_class` is provided by the hive
    partition, not stored in the file body.

    We iterate the catalog and run one COPY per Instance against the
    matching staged upstream file rather than going through the
    `observations` view. The view's WHERE-by-`instance_id` would re-scan
    every staged file on every iteration (O(n²)); targeting the source
    file directly keeps the write linear in the number of Instances.

    Soft-warns (rule 9 from CONTEXT.md) when any written file exceeds
    `OBSERVATIONS_FILE_SIZE_SOFT_LIMIT_MB` — does not abort publish.
    """
    output_dir = Path(output_dir)
    staging_dir = Path(staging_dir)
    logger = logger or logging.getLogger("petrobras_3w.export")

    obs_root = output_dir / "observations"
    obs_root.mkdir(parents=True, exist_ok=True)

    instances = con.execute(
        """
        SELECT instance_id, event_class, well_id, well_kind, source_file
        FROM instances
        ORDER BY event_class, instance_id
        """
    ).fetchall()

    relative_paths: list[str] = []
    for instance_id, event_class, well_id, well_kind, source_file in instances:
        partition_dir = obs_root / f"event_class={event_class}"
        partition_dir.mkdir(parents=True, exist_ok=True)
        target = partition_dir / f"{instance_id}.parquet"
        source_path = staging_dir / "dataset" / str(event_class) / source_file

        well_id_sql = "NULL" if well_id is None else str(well_id)

        # The constants are appended as scalar literals. DuckDB's parquet
        # writer RLE-encodes the resulting all-equal column for us, so
        # the storage cost is negligible. `event_class` is deliberately
        # omitted from the file body — it travels via the hive partition.
        con.execute(
            f"""
            COPY (
                SELECT
                    *,
                    '{instance_id}' AS instance_id,
                    {well_id_sql}    AS well_id,
                    '{well_kind}'    AS well_kind
                FROM read_parquet('{source_path}')
            ) TO '{target}' (FORMAT PARQUET)
            """
        )

        size_bytes = target.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        if size_mb > OBSERVATIONS_FILE_SIZE_SOFT_LIMIT_MB:
            logger.warning(
                "observations file exceeds soft size limit: %s (%.1f MB > %d MB)",
                target.relative_to(output_dir),
                size_mb,
                OBSERVATIONS_FILE_SIZE_SOFT_LIMIT_MB,
            )

        relative_paths.append(f"event_class={event_class}/{instance_id}.parquet")

    manifest_path = obs_root / "_files.json"
    manifest_path.write_text(json.dumps(relative_paths, indent=2) + "\n")
