"""Unit tests for monthly_production_builder.

Synthetic stg_production rows seed an in-memory DuckDB connection. The
builder is invoked directly; the resulting `monthly_production` table
is asserted against expected
`(idpozo, fecha, prod_pet, prod_gas, prod_agua, iny_agua, iny_gas,
   iny_co2, iny_otro, tef, vida_util)` tuples.

Date-completeness contract: every month in
`[first_production_row, last_production_row]` per well is represented
in the output. Source rows pass through verbatim; missing months are
synthesized with NULL measurements.
"""

from datetime import date

import duckdb
import pytest

from scripts.transform.argentina import monthly_production_builder

PRODUCTION_COLUMNS = (
    "idpozo INTEGER, anio INTEGER, mes INTEGER, "
    "prod_pet DOUBLE, prod_gas DOUBLE, prod_agua DOUBLE, "
    "iny_agua DOUBLE, iny_gas DOUBLE, iny_co2 DOUBLE, iny_otro DOUBLE, "
    "tef DOUBLE, vida_util DOUBLE"
)

# Default measurement tuple used by helpers; arbitrary distinct values.
M = (80.5, 1900.0, 7.0, 0.0, 0.0, 0.0, 0.0, 15.0, 1800.0)


def _row(idpozo: int, anio: int, mes: int, measurements: tuple = M) -> tuple:
    return (idpozo, anio, mes, *measurements)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(f"CREATE TABLE stg_production ({PRODUCTION_COLUMNS})")
    yield c
    c.close()


def _seed(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany(
        "INSERT INTO stg_production VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _result(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute(
        """
        SELECT idpozo, fecha, prod_pet, prod_gas, prod_agua,
               iny_agua, iny_gas, iny_co2, iny_otro, tef, vida_util
        FROM monthly_production
        ORDER BY idpozo, fecha
        """
    ).fetchall()


def test_no_gaps_pass_through(con):
    _seed(
        con,
        [
            _row(1001, 2006, 1),
            _row(1001, 2006, 2),
        ],
    )
    monthly_production_builder.build(con)
    out = _result(con)
    assert len(out) == 2
    assert out[0] == (1001, date(2006, 1, 1), *M)
    assert out[1] == (1001, date(2006, 2, 1), *M)


def test_single_month_gap_synthesizes_one_row(con):
    _seed(
        con,
        [
            _row(1001, 2006, 1),
            _row(1001, 2006, 3),
        ],
    )
    monthly_production_builder.build(con)
    out = _result(con)
    assert len(out) == 3
    assert out[0] == (1001, date(2006, 1, 1), *M)
    assert out[1] == (
        1001,
        date(2006, 2, 1),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert out[2] == (1001, date(2006, 3, 1), *M)


def test_multi_month_gap_across_years(con):
    """Well with rows in 2006-01 and 2007-01 needs 11 synthesized
    fill rows for Feb-Dec 2006."""
    _seed(
        con,
        [
            _row(1001, 2006, 1),
            _row(1001, 2007, 1),
        ],
    )
    monthly_production_builder.build(con)
    out = _result(con)
    assert len(out) == 13
    assert out[0] == (1001, date(2006, 1, 1), *M)
    assert out[-1] == (1001, date(2007, 1, 1), *M)
    for row in out[1:-1]:
        assert row[2:] == (None,) * 9, f"row {row[1]} should have NULL measurements"


def test_only_idpozo_and_fecha_and_measurements_are_kept(con):
    """Source `anio` / `mes` must not survive as separate columns;
    `fecha` is the only time column."""
    _seed(con, [_row(1001, 2006, 1)])
    monthly_production_builder.build(con)
    cols = {row[0] for row in con.execute("DESCRIBE monthly_production").fetchall()}
    assert cols == {
        "idpozo",
        "fecha",
        "prod_pet",
        "prod_gas",
        "prod_agua",
        "iny_agua",
        "iny_gas",
        "iny_co2",
        "iny_otro",
        "tef",
        "vida_util",
    }


def test_pk_uniqueness_idpozo_fecha(con):
    """Even with duplicate source rows for the same `(idpozo, anio, mes)`,
    the output has a unique `(idpozo, fecha)` pair (ANY_VALUE picks one)."""
    _seed(
        con,
        [
            _row(1001, 2006, 1, (80.0, 1900.0, 7.0, 0, 0, 0, 0, 15, 1800)),
            _row(1001, 2006, 1, (81.0, 1910.0, 7.1, 0, 0, 0, 0, 15, 1800)),
        ],
    )
    monthly_production_builder.build(con)
    pk_count = con.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT idpozo, fecha FROM monthly_production)"
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM monthly_production").fetchone()[0]
    assert pk_count == total == 1


def test_two_wells_independent(con):
    """Per-well partitioning: one well's first/last date does not bleed
    into another's spine."""
    _seed(
        con,
        [
            _row(1001, 2006, 1),
            _row(1001, 2006, 3),
            _row(2002, 2007, 6),
            _row(2002, 2007, 7),
        ],
    )
    monthly_production_builder.build(con)
    out = _result(con)
    assert len(out) == 5  # 1001: Jan,Feb(synth),Mar; 2002: Jun,Jul
    assert [r[0] for r in out] == [1001, 1001, 1001, 2002, 2002]


def test_temp_tables_dropped(con):
    """The builder cleans up its scratch tables — only monthly_production
    survives in the schema (besides stg_production)."""
    _seed(con, [_row(1001, 2006, 1)])
    monthly_production_builder.build(con)
    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert "monthly_production" in tables
    assert "_mp_input" not in tables
    assert "_mp_filled" not in tables
