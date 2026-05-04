"""Pre-publish validation hook for the Argentina export.

Invoked unconditionally before parquet writes. Enforces two of the six
PRD invariants:

1. Every non-NULL `geom` in `wells` parses as valid WKB.
2. Every `idpozo` in `well_operator_history` exists in `wells` (FK).

Later issues add PK uniqueness on (idpozo, fecha), FK integrity for
`well_events` and `monthly_production`, date completeness, partition
counts, and the 50 MB soft-warn.

Failure raises and aborts the export. Parquets are never written on a
failed validation.
"""

import duckdb


class FKIntegrityError(Exception):
    """An idpozo in a child table has no matching row in `wells`."""


def validate(con: duckdb.DuckDBPyConnection) -> None:
    _validate_wkb_parseable(con)
    _validate_operator_history_fk(con)


def _validate_wkb_parseable(con: duckdb.DuckDBPyConnection) -> None:
    """Every non-NULL `geom` in `wells` must parse as WKB.

    DuckDB's spatial extension raises on bad input, which is exactly the
    abort behavior we want — we materialize the parse over every row
    and let any failure surface as an exception.
    """
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")
    # COUNT(expr) forces evaluation of ST_GeomFromWKB on every non-NULL
    # row; a wrapping COUNT(*) would let the optimizer elide the parse.
    con.execute(
        """
        SELECT COUNT(ST_GeomFromWKB(geom))
        FROM wells
        WHERE geom IS NOT NULL
        """
    ).fetchone()


def _validate_operator_history_fk(con: duckdb.DuckDBPyConnection) -> None:
    """Every `idpozo` in `well_operator_history` must exist in `wells`."""
    orphans = con.execute(
        """
        SELECT COUNT(DISTINCT h.idpozo)
        FROM well_operator_history h
        ANTI JOIN wells w ON h.idpozo = w.idpozo
        """
    ).fetchone()[0]
    if orphans:
        raise FKIntegrityError(
            f"well_operator_history has {orphans} idpozo value(s) absent from wells"
        )
