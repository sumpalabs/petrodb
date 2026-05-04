"""Unit tests for the date_grid_filler deep module.

Five fixture cases exercise the gap-fill contract from the issue:
- (a) no gaps — pass-through
- (b) single one-month gap — one synthetic row inserted
- (c) multi-month gap — N synthetic rows inserted
- (d) well with only one source row — single row, no spine
- (e) NULL value cols already present in source pass through verbatim
      and are indistinguishable from synthesized rows (documented
      contract)

Plus per-well partitioning and unsorted-input cases.

The module is invoked with a synthetic source `_src` and writes to
`_out`. Schema is `(idpozo, fecha, prod_pet, prod_gas)`.
"""

from datetime import date

import duckdb
import pytest

from scripts.transform.argentina import date_grid_filler


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(
        """
        CREATE TABLE _src (
            idpozo INTEGER,
            fecha DATE,
            prod_pet DOUBLE,
            prod_gas DOUBLE
        )
        """
    )
    yield c
    c.close()


def _seed(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO _src VALUES (?, ?, ?, ?)", rows)


def _fill(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    date_grid_filler.fill(con, "_src", "_out", ["prod_pet", "prod_gas"])
    return con.execute(
        "SELECT idpozo, fecha, prod_pet, prod_gas FROM _out ORDER BY idpozo, fecha"
    ).fetchall()


def test_no_gaps_pass_through(con):
    _seed(
        con,
        [
            (1, date(2006, 1, 1), 80.0, 1900.0),
            (1, date(2006, 2, 1), 82.0, 1950.0),
            (1, date(2006, 3, 1), 85.0, 2000.0),
        ],
    )
    assert _fill(con) == [
        (1, date(2006, 1, 1), 80.0, 1900.0),
        (1, date(2006, 2, 1), 82.0, 1950.0),
        (1, date(2006, 3, 1), 85.0, 2000.0),
    ]


def test_single_month_gap_synthesizes_one_row(con):
    _seed(
        con,
        [
            (1, date(2006, 1, 1), 80.0, 1900.0),
            (1, date(2006, 3, 1), 85.0, 2000.0),
        ],
    )
    assert _fill(con) == [
        (1, date(2006, 1, 1), 80.0, 1900.0),
        (1, date(2006, 2, 1), None, None),
        (1, date(2006, 3, 1), 85.0, 2000.0),
    ]


def test_multi_month_gap_spans_year_boundary(con):
    """A 2006-01 → 2007-01 well needs 11 synthesized rows
    (Feb 2006 through Dec 2006), no source rows in between."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), 50.0, 1500.0),
            (1, date(2007, 1, 1), 52.0, 1520.0),
        ],
    )
    out = _fill(con)
    assert len(out) == 13  # 2006-01..2007-01 inclusive
    assert out[0] == (1, date(2006, 1, 1), 50.0, 1500.0)
    assert out[-1] == (1, date(2007, 1, 1), 52.0, 1520.0)
    for i in range(1, 12):
        assert out[i][2] is None and out[i][3] is None, f"row {i} should be synthetic"


def test_single_source_row_yields_single_output_row(con):
    """A well with one source row has first_fecha == last_fecha; the
    spine collapses to one row (no synthesis needed)."""
    _seed(con, [(1, date(2006, 6, 1), 80.0, 1900.0)])
    assert _fill(con) == [(1, date(2006, 6, 1), 80.0, 1900.0)]


def test_existing_null_measurements_pass_through(con):
    """NULL value cols already in source are preserved. The output row
    is indistinguishable from a synthesized fill row — that's the
    documented contract."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), 80.0, 1900.0),
            (1, date(2006, 2, 1), None, None),
            (1, date(2006, 3, 1), 85.0, 2000.0),
        ],
    )
    assert _fill(con) == [
        (1, date(2006, 1, 1), 80.0, 1900.0),
        (1, date(2006, 2, 1), None, None),
        (1, date(2006, 3, 1), 85.0, 2000.0),
    ]


def test_two_wells_independent(con):
    """Per-well partitioning: one well's first/last date does not
    bleed into another's spine."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), 80.0, 1900.0),
            (1, date(2006, 3, 1), 85.0, 2000.0),
            (2, date(2007, 6, 1), 60.0, 1600.0),
            (2, date(2007, 7, 1), 62.0, 1620.0),
        ],
    )
    assert _fill(con) == [
        (1, date(2006, 1, 1), 80.0, 1900.0),
        (1, date(2006, 2, 1), None, None),
        (1, date(2006, 3, 1), 85.0, 2000.0),
        (2, date(2007, 6, 1), 60.0, 1600.0),
        (2, date(2007, 7, 1), 62.0, 1620.0),
    ]


def test_unsorted_input_is_sorted_internally(con):
    """The module sorts by (idpozo, fecha) internally — caller need not pre-sort."""
    _seed(
        con,
        [
            (1, date(2006, 3, 1), 85.0, 2000.0),
            (1, date(2006, 1, 1), 80.0, 1900.0),
        ],
    )
    assert _fill(con) == [
        (1, date(2006, 1, 1), 80.0, 1900.0),
        (1, date(2006, 2, 1), None, None),
        (1, date(2006, 3, 1), 85.0, 2000.0),
    ]
