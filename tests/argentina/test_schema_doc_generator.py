"""Unit tests for the Argentina schema-doc generator.

The generator reflects column lists/types from the published Parquets
and emits four artifacts (`schema.json`, `schema.sql`, `schema.md`,
`README.md`). The tests build a tiny published-tree fixture (one row
per table, one monthly_production partition) and verify that:

- All four artifacts are written and well-formed.
- Reflected column lists match the parquet schema (no drift).
- English column descriptions and the four-bucket rationale appear
  in `schema.md`; Spanish column identifiers are preserved verbatim.
- The opaque-code glossary covers `tef` and `vida_util`.
- Foreign keys, primary keys, and dropped admin columns are documented.
- The README contains all four canonical query examples (single-well,
  year-range, basin-aggregate, manifest/`generate_series`).
- The generator is idempotent (re-running produces byte-identical files).
- The DDL emitted by `schema.sql` executes against a fresh DuckDB.
"""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from scripts.export.argentina import parquet_writer, schema_doc_generator


def _stage_published_tree(tmp_path: Path) -> Path:
    """Write a minimal but realistic published-tree fixture.

    One `idpozo` per table; `monthly_production` has two months in a
    single partition. Schemas mirror the production builders exactly.
    """
    out_dir = tmp_path / "argentina"
    con = duckdb.connect(str(tmp_path / "scratch.duckdb"))
    con.execute(
        """
        CREATE TABLE wells AS
        SELECT
            1::INTEGER AS idpozo,
            'YPF.X-1'::VARCHAR AS sigla,
            'Vaca Muerta'::VARCHAR AS formprod,
            'Neuquina'::VARCHAR AS cuenca,
            'Neuquen'::VARCHAR AS provincia,
            unhex('0101000020E61000000000000000405140000000000000C040') AS geom,
            true AS has_production
        """
    )
    con.execute(
        """
        CREATE TABLE well_operator_history AS
        SELECT
            1::INTEGER AS idpozo,
            'Z001'::VARCHAR AS idempresa,
            'YPF S.A.'::VARCHAR AS empresa,
            DATE '2020-01-01' AS valid_from,
            DATE '2021-12-01' AS valid_to
        """
    )
    con.execute(
        """
        CREATE TABLE well_events AS
        SELECT
            1::INTEGER AS idpozo,
            DATE '2020-01-01' AS event_date,
            'Extracción Efectiva'::VARCHAR AS tipoestado,
            'Bombeo Mecánico'::VARCHAR AS tipoextraccion,
            'Petrolífero'::VARCHAR AS tipopozo
        """
    )
    con.execute(
        """
        CREATE TABLE monthly_production AS
        SELECT * FROM (VALUES
            (1, DATE '2020-01-01', 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0),
            (1, DATE '2020-02-01', 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
        ) AS t(idpozo, fecha, prod_pet, prod_gas, prod_agua,
               iny_agua, iny_gas, iny_co2, iny_otro, tef, vida_util)
        """
    )
    parquet_writer.write_wells(con, out_dir)
    parquet_writer.write_operator_history(con, out_dir)
    parquet_writer.write_well_events(con, out_dir)
    parquet_writer.write_monthly_production(con, out_dir)
    con.close()
    return out_dir


@pytest.fixture
def published_tree(tmp_path: Path) -> Path:
    return _stage_published_tree(tmp_path)


@pytest.fixture
def reader_con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    yield con
    con.close()


def test_generate_writes_all_four_artifacts(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    schema_doc_generator.generate(reader_con, published_tree)
    for name in ("schema.json", "schema.sql", "schema.md", "README.md"):
        assert (published_tree / name).exists(), f"{name} was not written"


def test_schema_json_is_valid_and_documents_all_four_tables(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    schema_doc_generator.generate(reader_con, published_tree)
    payload = json.loads((published_tree / "schema.json").read_text())
    assert payload["dataset"] == "argentina"
    assert set(payload["tables"]) == {
        "wells",
        "well_operator_history",
        "well_events",
        "monthly_production",
    }
    for meta in payload["tables"].values():
        assert meta["columns"]
        assert meta["primary_key"]


def test_schema_json_columns_reflected_from_parquet(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    """The reflected column list must match the parquet's actual schema."""
    schema_doc_generator.generate(reader_con, published_tree)
    payload = json.loads((published_tree / "schema.json").read_text())

    wells_cols = {c["name"]: c for c in payload["tables"]["wells"]["columns"]}
    assert set(wells_cols) == {
        "idpozo",
        "sigla",
        "formprod",
        "cuenca",
        "provincia",
        "geom",
        "has_production",
    }
    assert wells_cols["idpozo"]["primary_key"] is True
    assert wells_cols["idpozo"]["not_null"] is True
    assert wells_cols["geom"]["type"] == "BLOB"


def test_schema_json_pk_and_fk_declarations(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    schema_doc_generator.generate(reader_con, published_tree)
    payload = json.loads((published_tree / "schema.json").read_text())

    assert payload["tables"]["monthly_production"]["primary_key"] == ["idpozo", "fecha"]
    fks = payload["tables"]["monthly_production"]["foreign_keys"]
    assert fks == [
        {"column": "idpozo", "references_table": "wells", "references_column": "idpozo"}
    ]
    assert payload["tables"]["wells"]["foreign_keys"] == []


def test_schema_md_covers_all_required_sections(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    schema_doc_generator.generate(reader_con, published_tree)
    body = (published_tree / "schema.md").read_text()
    # Spanish column identifiers preserved verbatim (the contract)
    assert "idpozo" in body
    assert "cuenca" in body
    # Glossary covers the opaque codes
    assert "Glossary" in body
    assert "tef" in body and "vida_util" in body
    # Four-bucket rationale appears (English)
    assert "Four buckets" in body or "four tables" in body.lower()
    # Dropped admin/audit columns are listed by name
    for col in ("observaciones", "idusuario", "rectificado", "habilitado"):
        assert col in body
    # Each table has a description
    for table in (
        "wells",
        "well_operator_history",
        "well_events",
        "monthly_production",
    ):
        assert f"`{table}`" in body


def test_schema_md_prose_is_english(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    """Section headings and prose must be English, not the previous Spanish."""
    schema_doc_generator.generate(reader_con, published_tree)
    body = (published_tree / "schema.md").read_text()
    # New English headings present
    assert "Dataset Schema" in body
    assert "## Tables" in body
    assert "## Relationships" in body
    assert "## Dropped columns" in body
    # Old Spanish headings absent
    for spanish_heading in (
        "Esquema del dataset",
        "Cuatro buckets, cuatro tablas",
        "Tablas",
        "Relaciones",
        "Glosario de códigos",
        "Columnas eliminadas",
        "Claves foráneas",
    ):
        assert spanish_heading not in body, (
            f"Spanish heading should be translated: {spanish_heading!r}"
        )


def test_schema_md_documents_every_published_column(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    """Every column in every published parquet must appear in schema.md."""
    schema_doc_generator.generate(reader_con, published_tree)
    body = (published_tree / "schema.md").read_text()

    for parquet_path in (
        published_tree / "wells.parquet",
        published_tree / "well_operator_history.parquet",
        published_tree / "well_events.parquet",
    ):
        cols = reader_con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{parquet_path}')"
        ).fetchall()
        for row in cols:
            assert f"`{row[0]}`" in body, (
                f"column {row[0]} from {parquet_path.name} missing from schema.md"
            )


def test_readme_contains_four_canonical_query_examples(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    schema_doc_generator.generate(reader_con, published_tree)
    body = (published_tree / "README.md").read_text()
    # Pattern hints unique to each canonical example
    assert "WHERE idpozo = 12345" in body  # single-well
    assert "BETWEEN 2018 AND 2022" in body  # year-range
    assert "GROUP BY w.cuenca" in body  # basin aggregate
    assert "generate_series" in body  # manifest URL-template
    assert "_files.json" in body  # manifest reference


def test_readme_lists_dropped_admin_columns_and_identifier_note(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    schema_doc_generator.generate(reader_con, published_tree)
    body = (published_tree / "README.md").read_text()
    for col in (
        "observaciones",
        "idusuario",
        "rectificado",
        "habilitado",
        "fechaingreso",
        "fecha_data",
        "geojson",
    ):
        assert col in body, f"dropped column {col} not noted in README"
    # The README must call out that column identifiers stay Spanish (the
    # explicit contract from issue #13), with the prose itself in English.
    assert "Spanish" in body


def test_readme_prose_is_english(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    """The README's section headings and prose must be English."""
    schema_doc_generator.generate(reader_con, published_tree)
    body = (published_tree / "README.md").read_text()
    # New English headings
    assert "## Published files" in body
    assert "## Dropped columns" in body
    assert "## Full schema" in body
    # Old Spanish headings absent
    for spanish_heading in (
        "## Archivos publicados",
        "## Columnas eliminadas",
        "## Acceso vía DuckDB",
        "## Esquema completo",
        "Pozo único",
        "Rango de años",
        "Agregado por cuenca",
    ):
        assert spanish_heading not in body, (
            f"Spanish heading should be translated: {spanish_heading!r}"
        )


def test_schema_sql_executes_against_fresh_duckdb(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection, tmp_path: Path
) -> None:
    """The emitted DDL must build an empty mirror of the published structure."""
    schema_doc_generator.generate(reader_con, published_tree)
    ddl = (published_tree / "schema.sql").read_text()

    fresh = duckdb.connect()
    try:
        fresh.execute(ddl)
        tables = {row[0] for row in fresh.execute("SHOW TABLES").fetchall()}
        assert tables == {
            "wells",
            "well_operator_history",
            "well_events",
            "monthly_production",
        }
        # Round-trip a row to verify FK + column names + types match the
        # published schema. The wells row must be inserted first so the FK
        # on monthly_production is satisfied.
        wells_cols = [row[0] for row in fresh.execute("DESCRIBE wells").fetchall()]
        nulls = ", ".join(["NULL"] * (len(wells_cols) - 1))
        fresh.execute(
            f"INSERT INTO wells ({', '.join(wells_cols)}) VALUES (1, {nulls})"
        )
        fresh.execute(
            """
            INSERT INTO monthly_production VALUES
            (1, DATE '2020-01-01', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
            """
        )
        row = fresh.execute("SELECT idpozo, fecha FROM monthly_production").fetchone()
        assert row == (1, date(2020, 1, 1))
    finally:
        fresh.close()


def test_generate_is_idempotent(
    published_tree: Path, reader_con: duckdb.DuckDBPyConnection
) -> None:
    schema_doc_generator.generate(reader_con, published_tree)
    first = {
        name: (published_tree / name).read_text()
        for name in ("schema.json", "schema.sql", "schema.md", "README.md")
    }
    schema_doc_generator.generate(reader_con, published_tree)
    second = {
        name: (published_tree / name).read_text()
        for name in ("schema.json", "schema.sql", "schema.md", "README.md")
    }
    assert first == second
