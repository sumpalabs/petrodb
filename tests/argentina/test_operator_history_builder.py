"""Unit tests for operator_history_builder.

Synthetic stg_production rows seed an in-memory DuckDB connection. The
builder is invoked directly; the resulting `well_operator_history`
table is asserted against expected (idpozo, idempresa, empresa,
valid_from, valid_to) tuples.
"""

from datetime import date

import duckdb
import pytest

from scripts.transform.argentina import operator_history_builder

PRODUCTION_COLUMNS = (
    "idpozo INTEGER, anio INTEGER, mes INTEGER, idempresa VARCHAR, empresa VARCHAR"
)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(f"CREATE TABLE stg_production ({PRODUCTION_COLUMNS})")
    yield c
    c.close()


def _seed(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO stg_production VALUES (?, ?, ?, ?, ?)", rows)


def _result(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute(
        """
        SELECT idpozo, idempresa, empresa, valid_from, valid_to
        FROM well_operator_history
        ORDER BY idpozo, valid_from
        """
    ).fetchall()


def test_single_operator_run(con):
    _seed(
        con,
        [
            (1001, 2006, 1, "Z001", "OPERATOR Z"),
            (1001, 2006, 2, "Z001", "OPERATOR Z"),
        ],
    )
    operator_history_builder.build(con)
    assert _result(con) == [
        (1001, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 2, 1)),
    ]


def test_back_to_back_operators(con):
    _seed(
        con,
        [
            (1001, 2006, 1, "Z001", "OPERATOR Z"),
            (1001, 2006, 2, "Z001", "OPERATOR Z"),
            (1001, 2006, 3, "APEA", "APEA OPERATOR"),
        ],
    )
    operator_history_builder.build(con)
    assert _result(con) == [
        (1001, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 2, 1)),
        (1001, "APEA", "APEA OPERATOR", date(2006, 3, 1), date(2006, 3, 1)),
    ]


def test_null_idempresa_is_its_own_run(con):
    """A NULL-idempresa month between two non-NULL runs surfaces as a
    standalone interval with idempresa IS NULL — empresa likewise NULL
    if the source carries NULL there."""
    _seed(
        con,
        [
            (1001, 2006, 1, "Z001", "OPERATOR Z"),
            (1001, 2006, 2, None, None),
            (1001, 2006, 3, "APEA", "APEA OPERATOR"),
        ],
    )
    operator_history_builder.build(con)
    assert _result(con) == [
        (1001, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 1, 1)),
        (1001, None, None, date(2006, 2, 1), date(2006, 2, 1)),
        (1001, "APEA", "APEA OPERATOR", date(2006, 3, 1), date(2006, 3, 1)),
    ]


def test_idempresa_is_varchar(con):
    """idempresa must round-trip as VARCHAR — alphanumeric source codes
    like 'Z001'/'APEA' are not integers."""
    _seed(con, [(1001, 2006, 1, "Z001", "OPERATOR Z")])
    operator_history_builder.build(con)
    type_row = con.execute(
        "SELECT typeof(idempresa) FROM well_operator_history LIMIT 1"
    ).fetchone()
    assert type_row[0] == "VARCHAR"


def test_first_month_empresa_wins(con):
    """If the operator name changed mid-run for the same idempresa code,
    the first-month value wins — source-fidelity for the run as a
    whole, not a per-month replay."""
    _seed(
        con,
        [
            (1001, 2006, 1, "Z001", "Z001 ORIGINAL NAME"),
            (1001, 2006, 2, "Z001", "Z001 RENAMED"),
            (1001, 2006, 3, "Z001", "Z001 RENAMED"),
        ],
    )
    operator_history_builder.build(con)
    assert _result(con) == [
        (1001, "Z001", "Z001 ORIGINAL NAME", date(2006, 1, 1), date(2006, 3, 1)),
    ]


def test_two_wells_independent(con):
    """Per-well partitioning at the builder level mirrors the
    interval_collapser's contract."""
    _seed(
        con,
        [
            (1001, 2006, 1, "Z001", "OPERATOR Z"),
            (1001, 2006, 2, "APEA", "APEA OPERATOR"),
            (2002, 2006, 1, "APEA", "APEA OPERATOR"),
            (2002, 2006, 2, "APEA", "APEA OPERATOR"),
        ],
    )
    operator_history_builder.build(con)
    assert _result(con) == [
        (1001, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 1, 1)),
        (1001, "APEA", "APEA OPERATOR", date(2006, 2, 1), date(2006, 2, 1)),
        (2002, "APEA", "APEA OPERATOR", date(2006, 1, 1), date(2006, 2, 1)),
    ]
