"""Drift guards for the published FORCE 2020 schema documentation.

The dataset has no transform pipeline — its Parquet files are committed
directly — so these tests validate that the committed docs
(`schema.{md,json,sql}`, `README.md`, `wells/_files.json`) stay consistent
with the live Parquet schema rather than re-running a pipeline. Regenerate
with ``uv run python -m scripts.export.force_2020.schema_doc_generator``.
"""

import json
from pathlib import Path

import duckdb
import pytest

from scripts.export.force_2020 import schema_doc_generator as gen

DATASET_DIR = Path("parquet/force_2020")
WELLS_DIR = DATASET_DIR / "wells"


@pytest.fixture(scope="module")
def well_files() -> list[Path]:
    files = sorted(WELLS_DIR.glob("*.parquet"))
    assert files, "no FORCE 2020 well parquet files found"
    return files


@pytest.fixture(scope="module")
def live_columns(well_files: list[Path]) -> list[tuple[str, str]]:
    con = duckdb.connect()
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{well_files[0].as_posix()}')"
    ).fetchall()
    con.close()
    return [(r[0], r[1]) for r in rows]


def test_manifest_matches_well_files(well_files: list[Path]) -> None:
    manifest = json.loads((WELLS_DIR / "_files.json").read_text())
    assert manifest == sorted(p.name for p in well_files)


def test_schema_json_columns_match_parquet(
    live_columns: list[tuple[str, str]],
) -> None:
    payload = json.loads((DATASET_DIR / "schema.json").read_text())
    documented = [
        (c["name"], c["type"]) for c in payload["tables"]["wells"]["columns"]
    ]
    assert documented == live_columns, "schema.json drifted from the parquet schema"
    assert payload["tables"]["wells"]["primary_key"] == ["WELL", "DEPTH_MD"]


def test_schema_sql_executes_and_matches(
    live_columns: list[tuple[str, str]],
) -> None:
    con = duckdb.connect()
    con.execute((DATASET_DIR / "schema.sql").read_text())
    ddl_cols = [
        r[0] for r in con.execute("DESCRIBE wells").fetchall()
    ]
    con.close()
    assert ddl_cols == [name for name, _ in live_columns]


def test_schema_md_documents_every_column(
    live_columns: list[tuple[str, str]],
) -> None:
    schema_md = (DATASET_DIR / "schema.md").read_text()
    for name, _ in live_columns:
        assert f"`{name}`" in schema_md, f"{name} missing from schema.md"


def test_lithology_table_matches_data(well_files: list[Path]) -> None:
    paths = [f.as_posix() for f in well_files]
    con = duckdb.connect()
    codes = {
        r[0]
        for r in con.execute(
            f"SELECT DISTINCT FORCE_2020_LITHOFACIES_LITHOLOGY "
            f"FROM read_parquet({paths})"
        ).fetchall()
    }
    con.close()
    assert codes == set(gen.LITHOLOGY_LABELS), (
        "lithology codes in the data differ from the documented mapping"
    )
    schema_md = (DATASET_DIR / "schema.md").read_text()
    for code in codes:
        assert str(code) in schema_md, f"lithology code {code} missing from schema.md"


def test_readme_has_manifest_based_access(live_columns: list[tuple[str, str]]) -> None:
    readme = (DATASET_DIR / "README.md").read_text()
    # ADR-0004: access docs use the manifest, never glob.
    assert "_files.json" in readme
    assert "read_parquet" in readme
    assert "*.parquet" not in readme, "README must not document glob-based access"
    # Leave-one-well-out CV is the documented modelling guidance.
    assert "leave-one-well" in readme.lower()
