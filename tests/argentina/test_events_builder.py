"""Unit tests for events_builder.

Synthetic stg_production rows seed an in-memory DuckDB connection. The
builder is invoked directly; the resulting `well_events` table is
asserted against expected
`(idpozo, event_date, tipoestado, tipoextraccion, tipopozo)` tuples.

First-row-per-well decision: emit. The first month of every well is a
transition into its initial operational state — a meaningful event by
itself. Documented in transition_detector and exercised here.

Source-fidelity: the builder reads stg_production directly, NOT from
any future gap-filled monthly_production table. A NULL gap in any of
the three components surfaces as its own transition.
"""

from datetime import date

import duckdb
import pytest

from scripts.transform.argentina import events_builder

PRODUCTION_COLUMNS = (
    "idpozo INTEGER, anio INTEGER, mes INTEGER, "
    "tipoestado VARCHAR, tipoextraccion VARCHAR, tipopozo VARCHAR"
)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute(f"CREATE TABLE stg_production ({PRODUCTION_COLUMNS})")
    yield c
    c.close()


def _seed(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO stg_production VALUES (?, ?, ?, ?, ?, ?)", rows)


def _result(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute(
        """
        SELECT idpozo, event_date, tipoestado, tipoextraccion, tipopozo
        FROM well_events
        ORDER BY idpozo, event_date
        """
    ).fetchall()


def test_first_row_per_well_is_emitted(con):
    """A well with no transitions yields a single event row — the
    initial-state snapshot at its first month."""
    _seed(
        con,
        [
            (1001, 2006, 1, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
            (1001, 2006, 2, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
        ],
    )
    events_builder.build(con)
    assert _result(con) == [
        (
            1001,
            date(2006, 1, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
    ]


def test_single_tipoestado_transition(con):
    _seed(
        con,
        [
            (1001, 2006, 1, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
            (1001, 2006, 2, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
            (
                1001,
                2006,
                3,
                "Parado Transitoriamente",
                "Bombeo Mecánico",
                "Petrolífero",
            ),
        ],
    )
    events_builder.build(con)
    assert _result(con) == [
        (
            1001,
            date(2006, 1, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
        (
            1001,
            date(2006, 3, 1),
            "Parado Transitoriamente",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
    ]


def test_all_three_change_same_month_emits_one_row(con):
    """A simultaneous change in all three components yields a single
    event row carrying the new triple — not three rows."""
    _seed(
        con,
        [
            (1001, 2006, 1, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
            (1001, 2006, 2, "Abandonado", "Surgencia Natural", "Gasífero"),
        ],
    )
    events_builder.build(con)
    assert _result(con) == [
        (
            1001,
            date(2006, 1, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
        (1001, date(2006, 2, 1), "Abandonado", "Surgencia Natural", "Gasífero"),
    ]


def test_null_in_any_field_is_a_transition(con):
    """NULL gaps in the operator-state triple are events too — source
    fidelity, not gap-fill."""
    _seed(
        con,
        [
            (1001, 2006, 1, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
            (1001, 2006, 2, "Extracción Efectiva", None, "Petrolífero"),
            (1001, 2006, 3, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
        ],
    )
    events_builder.build(con)
    assert _result(con) == [
        (
            1001,
            date(2006, 1, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
        (1001, date(2006, 2, 1), "Extracción Efectiva", None, "Petrolífero"),
        (
            1001,
            date(2006, 3, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
    ]


def test_flap_emits_three_rows(con):
    """A → B → A within two months is not smoothed — three events."""
    _seed(
        con,
        [
            (1001, 2006, 1, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
            (
                1001,
                2006,
                2,
                "Parado Transitoriamente",
                "Bombeo Mecánico",
                "Petrolífero",
            ),
            (1001, 2006, 3, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
        ],
    )
    events_builder.build(con)
    assert _result(con) == [
        (
            1001,
            date(2006, 1, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
        (
            1001,
            date(2006, 2, 1),
            "Parado Transitoriamente",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
        (
            1001,
            date(2006, 3, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
    ]


def test_two_wells_independent(con):
    _seed(
        con,
        [
            (1001, 2006, 1, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero"),
            (1001, 2006, 2, "Abandonado", "Bombeo Mecánico", "Petrolífero"),
            (2002, 2006, 1, "Extracción Efectiva", "Surgencia Natural", "Gasífero"),
            (2002, 2006, 2, "Extracción Efectiva", "Surgencia Natural", "Gasífero"),
        ],
    )
    events_builder.build(con)
    assert _result(con) == [
        (
            1001,
            date(2006, 1, 1),
            "Extracción Efectiva",
            "Bombeo Mecánico",
            "Petrolífero",
        ),
        (1001, date(2006, 2, 1), "Abandonado", "Bombeo Mecánico", "Petrolífero"),
        (
            2002,
            date(2006, 1, 1),
            "Extracción Efectiva",
            "Surgencia Natural",
            "Gasífero",
        ),
    ]


def test_temp_tables_dropped(con):
    """The builder cleans up its scratch tables — only well_events
    survives in the schema (besides stg_production)."""
    _seed(
        con,
        [(1001, 2006, 1, "Extracción Efectiva", "Bombeo Mecánico", "Petrolífero")],
    )
    events_builder.build(con)
    tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }
    assert "well_events" in tables
    assert "_events_input" not in tables
    assert "_events_transitions" not in tables
