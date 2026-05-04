"""Unit tests for the transition_detector deep module.

Five required fixture cases plus auxiliary coverage:
- (a) no transitions  → emit only the first row (initial-state contract)
- (b) single transition → 2 rows
- (c) all 3 fields change in same month vs only one changes
- (d) NULL in any of the 3 fields, transitions to/from NULL
- (e) flap (A → B → A within two months) → 3 rows, not smoothed

The module is invoked with a synthetic source table named `_src` and
produces a target table named `_out`. Inputs are
`(idpozo, fecha, a, b, c)` and outputs are the same, filtered to
transition rows only (including the first row per well).
"""

from datetime import date

import duckdb
import pytest

from scripts.transform.argentina import transition_detector


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(
        """
        CREATE TABLE _src (
            idpozo INTEGER,
            fecha DATE,
            a VARCHAR,
            b VARCHAR,
            c VARCHAR
        )
        """
    )
    yield c
    c.close()


def _seed(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO _src VALUES (?, ?, ?, ?, ?)", rows)


def _detect(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    transition_detector.detect(con, "_src", "_out", ["a", "b", "c"])
    return con.execute(
        "SELECT idpozo, fecha, a, b, c FROM _out ORDER BY idpozo, fecha"
    ).fetchall()


def test_no_transitions_emits_only_first_row(con):
    """Initial-state contract: the first month of every well is a transition
    into the well's starting state, so it is emitted even when nothing else
    changes for the rest of the well's life."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "A", "X", "Y"),
            (1, date(2006, 3, 1), "A", "X", "Y"),
        ],
    )
    assert _detect(con) == [(1, date(2006, 1, 1), "A", "X", "Y")]


def test_single_transition(con):
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "A", "X", "Y"),
            (1, date(2006, 3, 1), "B", "X", "Y"),
            (1, date(2006, 4, 1), "B", "X", "Y"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), "A", "X", "Y"),
        (1, date(2006, 3, 1), "B", "X", "Y"),
    ]


def test_only_one_field_changes(con):
    """A change in a single component of the snapshot triggers a transition."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "A", "X", "Z"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), "A", "X", "Y"),
        (1, date(2006, 2, 1), "A", "X", "Z"),
    ]


def test_all_three_fields_change_same_month(con):
    """A simultaneous change in all three components emits a single
    transition row carrying the new triple — not three rows."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "B", "P", "Q"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), "A", "X", "Y"),
        (1, date(2006, 2, 1), "B", "P", "Q"),
    ]


def test_null_in_any_field_emits_transition(con):
    """A → NULL in any component is a transition; NULL → A is also a
    transition. NULLs are values, not gaps to be smoothed over."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "A", None, "Y"),
            (1, date(2006, 3, 1), "A", "X", "Y"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), "A", "X", "Y"),
        (1, date(2006, 2, 1), "A", None, "Y"),
        (1, date(2006, 3, 1), "A", "X", "Y"),
    ]


def test_well_starts_with_null(con):
    """A NULL first row is still emitted — initial state, even if unknown."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), None, None, None),
            (1, date(2006, 2, 1), "A", "X", "Y"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), None, None, None),
        (1, date(2006, 2, 1), "A", "X", "Y"),
    ]


def test_flap_is_not_smoothed(con):
    """A → B → A across three months produces three rows, not one or two."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "B", "X", "Y"),
            (1, date(2006, 3, 1), "A", "X", "Y"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), "A", "X", "Y"),
        (1, date(2006, 2, 1), "B", "X", "Y"),
        (1, date(2006, 3, 1), "A", "X", "Y"),
    ]


def test_unsorted_input_is_sorted_internally(con):
    _seed(
        con,
        [
            (1, date(2006, 3, 1), "B", "X", "Y"),
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "A", "X", "Y"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), "A", "X", "Y"),
        (1, date(2006, 3, 1), "B", "X", "Y"),
    ]


def test_two_wells_independent(con):
    """Per-well partitioning: well 2's first row is its own initial state,
    not absorbed into well 1's run."""
    _seed(
        con,
        [
            (1, date(2006, 1, 1), "A", "X", "Y"),
            (1, date(2006, 2, 1), "A", "X", "Y"),
            (2, date(2006, 1, 1), "A", "X", "Y"),
            (2, date(2006, 2, 1), "B", "X", "Y"),
        ],
    )
    assert _detect(con) == [
        (1, date(2006, 1, 1), "A", "X", "Y"),
        (2, date(2006, 1, 1), "A", "X", "Y"),
        (2, date(2006, 2, 1), "B", "X", "Y"),
    ]
