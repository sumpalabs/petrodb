"""Pre-publish validation hook for the Argentina export.

Invoked unconditionally before parquet writes. Enforces all six PRD
invariants:

Pre-write (`validate`):
1. Every non-NULL `geom` in `wells` parses as valid WKB.
2. Every `idpozo` in `well_operator_history` exists in `wells` (FK).
3. Every `idpozo` in `well_events` exists in `wells` (FK).
4. Every `idpozo` in `monthly_production` exists in `wells` (FK).
5. `monthly_production` has unique `(idpozo, fecha)`.
6. Date-completeness: per well, monthly row count equals
   `MONTH_DIFF(MIN(fecha), MAX(fecha)) + 1`.

Post-write (`validate_partitions`):
7. Partition count equals the number of distinct anios in
   `monthly_production`, and the sum of partition row counts matches
   the table row count.
8. Soft warning if any year-partition Parquet exceeds 50 MB
   (Cloudflare cache headroom).

Hard-failure invariants raise and abort the export. Parquets are never
written on a failed pre-write validation. Soft warnings emit via
`warnings.warn` and do not abort.
"""

import warnings
from pathlib import Path

import duckdb

PARTITION_SIZE_WARN_BYTES = 50 * 1024 * 1024  # 50 MB Cloudflare-edge headroom


class FKIntegrityError(Exception):
    """An idpozo in a child table has no matching row in `wells`."""


class PKUniquenessError(Exception):
    """A table's primary-key tuple has duplicate rows."""


class DateCompletenessError(Exception):
    """A well's monthly row count does not span its full date range."""


class PartitionCountError(Exception):
    """Partition file count or row count does not match the source table."""


def validate(con: duckdb.DuckDBPyConnection) -> None:
    _validate_wkb_parseable(con)
    _validate_operator_history_fk(con)
    _validate_well_events_fk(con)
    _validate_monthly_production_fk(con)
    _validate_monthly_production_pk(con)
    _validate_monthly_production_date_completeness(con)


def validate_partitions(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    """Post-write checks on the hive-partitioned monthly_production tree.

    Read-only DuckDB connection is reused so the read_parquet count
    runs in the same engine instance as the source table count.
    """
    output_dir = Path(output_dir)
    partition_root = output_dir / "monthly_production"
    _validate_partition_counts(con, partition_root)
    _warn_on_oversized_partitions(partition_root)


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


def _validate_well_events_fk(con: duckdb.DuckDBPyConnection) -> None:
    """Every `idpozo` in `well_events` must exist in `wells`."""
    orphans = con.execute(
        """
        SELECT COUNT(DISTINCT e.idpozo)
        FROM well_events e
        ANTI JOIN wells w ON e.idpozo = w.idpozo
        """
    ).fetchone()[0]
    if orphans:
        raise FKIntegrityError(
            f"well_events has {orphans} idpozo value(s) absent from wells"
        )


def _validate_monthly_production_fk(con: duckdb.DuckDBPyConnection) -> None:
    """Every `idpozo` in `monthly_production` must exist in `wells`."""
    orphans = con.execute(
        """
        SELECT COUNT(DISTINCT m.idpozo)
        FROM monthly_production m
        ANTI JOIN wells w ON m.idpozo = w.idpozo
        """
    ).fetchone()[0]
    if orphans:
        raise FKIntegrityError(
            f"monthly_production has {orphans} idpozo value(s) absent from wells"
        )


def _validate_monthly_production_pk(con: duckdb.DuckDBPyConnection) -> None:
    """`(idpozo, fecha)` must uniquely identify a `monthly_production` row.

    Counts duplicate-key groups (HAVING COUNT(*) > 1) rather than
    comparing total vs DISTINCT counts: the diagnostic is more useful
    and the engine prunes the GROUP BY identically.
    """
    duplicate_groups = con.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT idpozo, fecha
            FROM monthly_production
            GROUP BY idpozo, fecha
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    if duplicate_groups:
        raise PKUniquenessError(
            f"monthly_production has {duplicate_groups} duplicate (idpozo, fecha) "
            f"key(s)"
        )


def _validate_monthly_production_date_completeness(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Per-well row count must equal the closed month-span of its dates.

    `DATE_DIFF('month', MIN, MAX) + 1` is the inclusive month count
    between a well's first and last `fecha`. Any well whose row count
    diverges signals a missing month — the gap-fill failed.
    """
    incomplete = con.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT idpozo
            FROM monthly_production
            GROUP BY idpozo
            HAVING COUNT(*) <> DATE_DIFF('month', MIN(fecha), MAX(fecha)) + 1
        )
        """
    ).fetchone()[0]
    if incomplete:
        raise DateCompletenessError(
            f"monthly_production has {incomplete} well(s) whose row count "
            f"does not match the closed month-span of its dates"
        )


def _validate_partition_counts(
    con: duckdb.DuckDBPyConnection, partition_root: Path
) -> None:
    """Partition file count == distinct anios; row totals must match.

    Reads the published parquets back via hive partitioning so the
    check exercises the layout consumers will see, not the intermediate
    table alone.
    """
    expected_year_count, expected_row_count = con.execute(
        """
        SELECT
            COUNT(DISTINCT EXTRACT(YEAR FROM fecha)),
            COUNT(*)
        FROM monthly_production
        """
    ).fetchone()

    partition_files = sorted(partition_root.glob("anio=*/data.parquet"))
    actual_year_count = len(partition_files)
    if actual_year_count != expected_year_count:
        raise PartitionCountError(
            f"monthly_production partition count {actual_year_count} does not "
            f"match {expected_year_count} distinct anio(s) in source table"
        )

    if expected_row_count == 0:
        return
    glob = str(partition_root / "anio=*" / "data.parquet")
    actual_row_count = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{glob}', hive_partitioning = true)"
    ).fetchone()[0]
    if actual_row_count != expected_row_count:
        raise PartitionCountError(
            f"monthly_production partitions hold {actual_row_count} row(s); "
            f"source table has {expected_row_count}"
        )


def _warn_on_oversized_partitions(partition_root: Path) -> None:
    """Soft warning for any partition file over 50 MB (Cloudflare headroom).

    Not a hard failure: the layout is still functional, only the cost
    of edge caching changes. Operators decide whether to re-shard.
    """
    for path in sorted(partition_root.glob("anio=*/data.parquet")):
        size = path.stat().st_size
        if size > PARTITION_SIZE_WARN_BYTES:
            warnings.warn(
                f"{path.relative_to(partition_root.parent)} is "
                f"{size / 1024 / 1024:.1f} MB (>50 MB Cloudflare headroom)",
                stacklevel=2,
            )
