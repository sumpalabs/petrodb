"""Unit tests for the interval_collapser deep module.

Six fixture cases exercise the gap-and-island contract:
- (a) single contiguous run
- (b) two operators back-to-back
- (c) NULL gap between two non-NULL runs (3 intervals out)
- (d) single-month flip mid-run (3 intervals out, not smoothed)
- (e) well that starts NULL
- (f) well that ends NULL

The module is invoked with a synthetic source table named `_src` and
produces a target table named `_out`. Inputs are `(idpozo, fecha, value)`
and outputs are `(idpozo, value, valid_from, valid_to)`.
"""

from datetime import date

import duckdb
import pytest

from scripts.transform.argentina import interval_collapser


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(
        """
        CREATE TABLE _src (
            idpozo INTEGER,
            fecha DATE,
            value VARCHAR
        )
        """
    )
    yield c
    c.close()


def _seed(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO _src VALUES (?, ?, ?)", rows)


def _collapse(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    interval_collapser.collapse(con, "_src", "_out", "value")
    return con.execute(
        "SELECT idpozo, value, valid_from, valid_to FROM _out ORDER BY idpozo, valid_from"
    ).fetchall()


def test_single_contiguous_run(con):
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A"),
            (1, date(2006, 2, 1), "A"),
            (1, date(2006, 3, 1), "A"),
        ],
    )
    assert _collapse(con) == [(1, "A", date(2006, 1, 1), date(2006, 3, 1))]


def test_two_operators_back_to_back(con):
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A"),
            (1, date(2006, 2, 1), "A"),
            (1, date(2006, 3, 1), "B"),
            (1, date(2006, 4, 1), "B"),
        ],
    )
    assert _collapse(con) == [
        (1, "A", date(2006, 1, 1), date(2006, 2, 1)),
        (1, "B", date(2006, 3, 1), date(2006, 4, 1)),
    ]


def test_null_gap_between_non_null_runs(con):
    """A → NULL → B yields 3 distinct intervals; the NULL is its own run."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A"),
            (1, date(2006, 2, 1), None),
            (1, date(2006, 3, 1), None),
            (1, date(2006, 4, 1), "B"),
        ],
    )
    assert _collapse(con) == [
        (1, "A", date(2006, 1, 1), date(2006, 1, 1)),
        (1, None, date(2006, 2, 1), date(2006, 3, 1)),
        (1, "B", date(2006, 4, 1), date(2006, 4, 1)),
    ]


def test_single_month_flip_not_smoothed(con):
    """A → B → A across three months produces three intervals, not one."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A"),
            (1, date(2006, 2, 1), "B"),
            (1, date(2006, 3, 1), "A"),
        ],
    )
    assert _collapse(con) == [
        (1, "A", date(2006, 1, 1), date(2006, 1, 1)),
        (1, "B", date(2006, 2, 1), date(2006, 2, 1)),
        (1, "A", date(2006, 3, 1), date(2006, 3, 1)),
    ]


def test_well_starts_null(con):
    """First row is NULL — emit a NULL interval before the non-NULL run."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), None),
            (1, date(2006, 2, 1), None),
            (1, date(2006, 3, 1), "A"),
        ],
    )
    assert _collapse(con) == [
        (1, None, date(2006, 1, 1), date(2006, 2, 1)),
        (1, "A", date(2006, 3, 1), date(2006, 3, 1)),
    ]


def test_well_ends_null(con):
    """Last row is NULL — emit a NULL interval after the non-NULL run."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A"),
            (1, date(2006, 2, 1), None),
        ],
    )
    assert _collapse(con) == [
        (1, "A", date(2006, 1, 1), date(2006, 1, 1)),
        (1, None, date(2006, 2, 1), date(2006, 2, 1)),
    ]


def test_unsorted_input_is_sorted_internally(con):
    """The module sorts by (idpozo, fecha) internally — caller need not pre-sort."""
    _seed(
        con,
        [
            (1, date(2006, 3, 1), "A"),
            (1, date(2006, 1, 1), "A"),
            (1, date(2006, 2, 1), "A"),
        ],
    )
    assert _collapse(con) == [(1, "A", date(2006, 1, 1), date(2006, 3, 1))]


def test_two_wells_independent(con):
    """Per-well partitioning: one well's transitions do not bleed into another."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A"),
            (1, date(2006, 2, 1), "A"),
            (2, date(2006, 1, 1), "B"),
            (2, date(2006, 2, 1), "C"),
        ],
    )
    assert _collapse(con) == [
        (1, "A", date(2006, 1, 1), date(2006, 2, 1)),
        (2, "B", date(2006, 1, 1), date(2006, 1, 1)),
        (2, "C", date(2006, 2, 1), date(2006, 2, 1)),
    ]
