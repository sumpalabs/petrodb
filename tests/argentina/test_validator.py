"""Unit tests for the Argentina export validator.

Exercises the WKB-parseability and operator-history FK invariants.
Later issues add PK uniqueness, additional FK checks, date
completeness, partition counts.
"""

from datetime import date

import duckdb
import pytest

from scripts.export.argentina import validator

VALID_WKB_HEX = "0101000020E61000000000000000405140000000000000C040"
INVALID_WKB_HEX = "DEADBEEFCAFEBABEDEADBEEFCAFEBABE"


def _make_wells_with_geom(
    con: duckdb.DuckDBPyConnection, hex_values: list[str | None]
) -> None:
    con.execute("CREATE OR REPLACE TABLE wells (idpozo INTEGER, geom BLOB)")
    for i, hx in enumerate(hex_values, start=1):
        if hx is None:
            con.execute("INSERT INTO wells VALUES (?, NULL)", [i])
        else:
            con.execute(
                "INSERT INTO wells VALUES (?, unhex(?))",
                [i, hx],
            )
    con.execute(
        """
        CREATE OR REPLACE TABLE well_operator_history (
            idpozo INTEGER,
            idempresa VARCHAR,
            empresa VARCHAR,
            valid_from DATE,
            valid_to DATE
        )
        """
    )


def _seed_operator_history(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO well_operator_history VALUES (?, ?, ?, ?, ?)", rows)


def test_validator_passes_on_valid_wkb():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, VALID_WKB_HEX])
    validator.validate(con)


def test_validator_passes_when_geom_is_null():
    """NULL geom rows are skipped (the invariant only applies to non-NULL rows)."""
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, None, None])
    validator.validate(con)


def test_validator_raises_on_invalid_wkb():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, INVALID_WKB_HEX])
    with pytest.raises(Exception):
        validator.validate(con)


def test_operator_history_fk_passes_when_all_idpozos_in_wells():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, VALID_WKB_HEX])
    _seed_operator_history(
        con,
        [
            (1, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 12, 1)),
            (2, "APEA", "APEA OPERATOR", date(2006, 1, 1), date(2006, 12, 1)),
        ],
    )
    validator.validate(con)


def test_operator_history_fk_raises_on_orphan_idpozo():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])  # idpozo 1 only
    _seed_operator_history(
        con,
        [
            (1, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 12, 1)),
            (999, "APEA", "APEA OPERATOR", date(2006, 1, 1), date(2006, 12, 1)),
        ],
    )
    with pytest.raises(validator.FKIntegrityError, match="well_operator_history"):
        validator.validate(con)


def test_operator_history_fk_passes_when_history_empty():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    validator.validate(con)
