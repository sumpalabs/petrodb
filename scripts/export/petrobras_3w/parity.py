"""Parity check suite for the Petrobras 3W publish.

Runs the nine queries described in PRD #18 / issue #23 against three
sources of truth — the staged upstream parquet tree pinned at git tag
``v.1.70.0`` / dataset version ``2.0.0``, the published catalog
(``instances.parquet``, ``wells.parquet``), and the published
``observations/`` hive tree. Any divergence aborts publish.

Where the validator (``validator.py``) enforces structural invariants
of the *intermediate* DuckDB DB before writes, parity is the *post-write*
correctness gate that proves the published bytes round-trip the upstream
bytes 1:1. The bit-for-bit comparison policy (no epsilon tolerance) is
set in PRD #18: the 27 sensor floats + ``class`` + ``state`` +
``timestamp`` are preserved verbatim, so any discrepancy is a writer
bug we want to catch.

Each check raises a specific subclass of ``ParityError`` so the orchestrator
can produce an informative abort message and the test suite can target
single checks. The checks run in PRD-#18 order:

1.  Per-event-class total row count — upstream vs catalog vs published.
2.  Per-instance row count — upstream vs catalog vs published.
3.  Global ``class`` distribution — upstream vs published.
4.  Global ``state`` distribution — upstream vs published.
5.  Per-sensor global aggregates (SUM/AVG/MIN/MAX/COUNT/NULL) — upstream
    vs published, for every non-identifier body column.
6.  Per-sensor aggregates grouped by ``event_class`` — same metrics.
7.  Per-instance ``(start_ts, end_ts)`` — upstream MIN/MAX vs catalog
    ``start_ts``/``end_ts`` vs published MIN/MAX.
8.  Distinct real-Well count — upstream count vs ``wells.parquet``
    rowcount vs the pinned ``EXPECTED_REAL_WELL_COUNT``.
9.  Per-event-class instance count — upstream distinct-instance count
    vs catalog row count.

Sensor columns are discovered at runtime from the published
``observations`` schema (the upstream side carries the same body, minus
the three RLE-encoded constants the writer adds). That keeps the check
agnostic to upstream's exact 27-column schema — a future column add or
rename surfaces as a parity match on the renamed column, not a hard-
coded reference to a missing column name.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from scripts.export.petrobras_3w.validator import EXPECTED_REAL_WELL_COUNT

# Columns present in every published Observations file body but not part
# of the upstream-sensor schema. The first three are upstream's own
# label/operating-status/time columns; the next three are the RLE-encoded
# constants the writer derives from the catalog. ``event_class`` is the
# hive-partition column on the published side (not stored in the file
# body) and the regex-derived column on the upstream side, so it is also
# excluded from the "sensor" list.
_NON_SENSOR_COLUMNS: frozenset[str] = frozenset(
    {
        "class",
        "state",
        "timestamp",
        "instance_id",
        "well_id",
        "well_kind",
        "event_class",
    }
)


class ParityError(Exception):
    """Base class for parity divergences between upstream and published."""


class ParityRowCountPerEventClassError(ParityError):
    """Check 1: per-event-class row count diverges (upstream / catalog / pub)."""


class ParityRowCountPerInstanceError(ParityError):
    """Check 2: per-instance row count diverges (upstream / catalog / pub)."""


class ParityClassDistributionError(ParityError):
    """Check 3: global `class`-value distribution diverges (upstream vs pub)."""


class ParityStateDistributionError(ParityError):
    """Check 4: global `state`-value distribution diverges (upstream vs pub)."""


class ParitySensorAggregatesError(ParityError):
    """Check 5: a per-sensor global aggregate diverges (upstream vs pub)."""


class ParitySensorAggregatesByEventClassError(ParityError):
    """Check 6: a per-sensor per-event-class aggregate diverges."""


class ParityInstanceTimestampsError(ParityError):
    """Check 7: per-instance (start_ts, end_ts) diverges (any of three sources)."""


class ParityRealWellCountError(ParityError):
    """Check 8: distinct real-Well count diverges from the pinned upstream."""


class ParityInstanceCountPerEventClassError(ParityError):
    """Check 9: per-event-class instance count diverges (upstream vs catalog)."""


def check(staging_dir: Path, output_dir: Path) -> None:
    """Run the full nine-check parity suite.

    ``staging_dir`` is the staged upstream tree (a ``dataset/N/*.parquet``
    layout). ``output_dir`` is the published-parquets directory written
    by ``parquet_writer``. The function reads both via a fresh DuckDB
    in-memory connection — it does not share state with the validator's
    intermediate DB.
    """
    staging_dir = Path(staging_dir)
    output_dir = Path(output_dir)

    con = duckdb.connect()
    try:
        _register_views(con, staging_dir, output_dir)
        sensors = _sensor_columns(con)
        _check_row_count_per_event_class(con)
        _check_row_count_per_instance(con)
        _check_class_distribution(con)
        _check_state_distribution(con)
        _check_sensor_aggregates(con, sensors)
        _check_sensor_aggregates_by_event_class(con, sensors)
        _check_instance_timestamps(con)
        _check_real_well_count(con)
        _check_instance_count_per_event_class(con)
    finally:
        con.close()


def _register_views(
    con: duckdb.DuckDBPyConnection, staging_dir: Path, output_dir: Path
) -> None:
    """Wire the three sources into named views with consistent types.

    Both views surface ``event_class`` as ``BIGINT``: the upstream view
    derives it from the directory name (cast on the way out); the
    published view reads it via ``hive_partitioning=true`` (DuckDB picks
    BIGINT for the autodetected integer partition value). ``instance_id``
    is regex-derived from the source filename on the upstream side and
    materialised as a constant column on the published side — both are
    VARCHAR.
    """
    staging_glob = str(staging_dir / "dataset" / "*" / "*.parquet")
    pub_obs_glob = str(output_dir / "observations" / "event_class=*" / "*.parquet")
    instances_path = output_dir / "instances.parquet"
    wells_path = output_dir / "wells.parquet"

    con.execute(
        f"""
        CREATE OR REPLACE VIEW upstream_obs AS
        SELECT
            * EXCLUDE (filename),
            CAST(regexp_extract(filename, '/dataset/([0-9]+)/', 1)
                 AS BIGINT) AS event_class,
            regexp_extract(filename, '/([^/]+)\\.parquet$', 1)
                AS instance_id
        FROM read_parquet(
            '{staging_glob}',
            filename = true,
            union_by_name = true
        )
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE VIEW pub_obs AS
        SELECT *
        FROM read_parquet(
            '{pub_obs_glob}',
            hive_partitioning = true,
            union_by_name = true
        )
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE VIEW pub_instances AS
        SELECT * FROM read_parquet('{instances_path}')
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE VIEW pub_wells AS
        SELECT * FROM read_parquet('{wells_path}')
        """
    )


def _sensor_columns(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """Discover sensor columns from the published `pub_obs` schema.

    Everything that is not an identifier / label / time / hive column is
    a sensor. Discovered at runtime so the check stays agnostic to the
    exact 27-column upstream schema.
    """
    described = con.execute("DESCRIBE SELECT * FROM pub_obs").fetchall()
    return tuple(row[0] for row in described if row[0] not in _NON_SENSOR_COLUMNS)


def _check_row_count_per_event_class(con: duckdb.DuckDBPyConnection) -> None:
    """Check 1: per-event-class row count matches across all three sources."""
    rows = con.execute(
        """
        WITH
        upstream AS (
            SELECT event_class, COUNT(*) AS n
            FROM upstream_obs GROUP BY event_class
        ),
        catalog AS (
            SELECT event_class, SUM(n_rows) AS n
            FROM pub_instances GROUP BY event_class
        ),
        pub AS (
            SELECT event_class, COUNT(*) AS n
            FROM pub_obs GROUP BY event_class
        )
        SELECT
            COALESCE(u.event_class, c.event_class, p.event_class) AS event_class,
            u.n AS upstream_n, c.n AS catalog_n, p.n AS pub_n
        FROM upstream u
        FULL OUTER JOIN catalog c USING (event_class)
        FULL OUTER JOIN pub p USING (event_class)
        WHERE u.n IS DISTINCT FROM c.n
           OR c.n IS DISTINCT FROM p.n
        ORDER BY event_class
        """
    ).fetchall()
    if rows:
        raise ParityRowCountPerEventClassError(
            f"per-event-class row count diverges for {len(rows)} event class(es): "
            f"{rows}"
        )


def _check_row_count_per_instance(con: duckdb.DuckDBPyConnection) -> None:
    """Check 2: per-instance row count matches upstream / catalog / pub."""
    rows = con.execute(
        """
        WITH
        upstream AS (
            SELECT instance_id, COUNT(*) AS n
            FROM upstream_obs GROUP BY instance_id
        ),
        catalog AS (
            SELECT instance_id, n_rows AS n FROM pub_instances
        ),
        pub AS (
            SELECT instance_id, COUNT(*) AS n
            FROM pub_obs GROUP BY instance_id
        )
        SELECT
            COALESCE(u.instance_id, c.instance_id, p.instance_id) AS instance_id,
            u.n AS upstream_n, c.n AS catalog_n, p.n AS pub_n
        FROM upstream u
        FULL OUTER JOIN catalog c USING (instance_id)
        FULL OUTER JOIN pub p USING (instance_id)
        WHERE u.n IS DISTINCT FROM c.n
           OR c.n IS DISTINCT FROM p.n
        ORDER BY instance_id
        """
    ).fetchall()
    if rows:
        raise ParityRowCountPerInstanceError(
            f"per-instance row count diverges for {len(rows)} instance(s); "
            f"first: {rows[0]}"
        )


def _check_class_distribution(con: duckdb.DuckDBPyConnection) -> None:
    """Check 3: global ``class``-value distribution matches upstream exactly.

    ``class`` is NULL on the warmup prefix of real-Well anomaly Instances,
    and a NULL bucket on both sides is the expected normal — so the join
    must treat NULL=NULL as a match. ``USING (class)`` would split it
    into two phantom mismatches, so we use ``IS NOT DISTINCT FROM``.
    """
    rows = con.execute(
        """
        WITH
        upstream AS (
            SELECT class, COUNT(*) AS n FROM upstream_obs GROUP BY class
        ),
        pub AS (
            SELECT class, COUNT(*) AS n FROM pub_obs GROUP BY class
        )
        SELECT COALESCE(u.class, p.class) AS class,
               u.n AS upstream_n, p.n AS pub_n
        FROM upstream u
        FULL OUTER JOIN pub p ON u.class IS NOT DISTINCT FROM p.class
        WHERE u.n IS DISTINCT FROM p.n
        ORDER BY class
        """
    ).fetchall()
    if rows:
        raise ParityClassDistributionError(
            f"`class` distribution diverges for {len(rows)} class value(s): {rows}"
        )


def _check_state_distribution(con: duckdb.DuckDBPyConnection) -> None:
    """Check 4: global ``state``-value distribution matches upstream exactly.

    NULL is a legitimate value here (same reasoning as the class check),
    so ``IS NOT DISTINCT FROM`` is used for the join predicate.
    """
    rows = con.execute(
        """
        WITH
        upstream AS (
            SELECT state, COUNT(*) AS n FROM upstream_obs GROUP BY state
        ),
        pub AS (
            SELECT state, COUNT(*) AS n FROM pub_obs GROUP BY state
        )
        SELECT COALESCE(u.state, p.state) AS state,
               u.n AS upstream_n, p.n AS pub_n
        FROM upstream u
        FULL OUTER JOIN pub p ON u.state IS NOT DISTINCT FROM p.state
        WHERE u.n IS DISTINCT FROM p.n
        ORDER BY state
        """
    ).fetchall()
    if rows:
        raise ParityStateDistributionError(
            f"`state` distribution diverges for {len(rows)} state value(s): {rows}"
        )


def _quote(identifier: str) -> str:
    """Double-quote a SQL identifier, escaping embedded double quotes.

    Sensor columns can contain hyphens (`P-PDG`, `ESTADO-SDV-GL`), so the
    parity SQL must always quote them. Embedded ``"`` is doubled per the
    SQL standard.
    """
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _check_sensor_aggregates(
    con: duckdb.DuckDBPyConnection, sensors: tuple[str, ...]
) -> None:
    """Check 5: per-sensor global SUM/AVG/MIN/MAX/COUNT/NULL match upstream."""
    for col in sensors:
        quoted = _quote(col)
        result = con.execute(
            f"""
            WITH
            u AS (
                SELECT
                    SUM({quoted}) AS s, AVG({quoted}) AS a,
                    MIN({quoted}) AS mn, MAX({quoted}) AS mx,
                    COUNT({quoted}) AS c,
                    COUNT(*) - COUNT({quoted}) AS nl
                FROM upstream_obs
            ),
            p AS (
                SELECT
                    SUM({quoted}) AS s, AVG({quoted}) AS a,
                    MIN({quoted}) AS mn, MAX({quoted}) AS mx,
                    COUNT({quoted}) AS c,
                    COUNT(*) - COUNT({quoted}) AS nl
                FROM pub_obs
            )
            SELECT u.s, u.a, u.mn, u.mx, u.c, u.nl,
                   p.s, p.a, p.mn, p.mx, p.c, p.nl
            FROM u, p
            WHERE u.s  IS DISTINCT FROM p.s
               OR u.a  IS DISTINCT FROM p.a
               OR u.mn IS DISTINCT FROM p.mn
               OR u.mx IS DISTINCT FROM p.mx
               OR u.c  IS DISTINCT FROM p.c
               OR u.nl IS DISTINCT FROM p.nl
            """
        ).fetchall()
        if result:
            upstream_agg = result[0][:6]
            pub_agg = result[0][6:]
            raise ParitySensorAggregatesError(
                f"sensor `{col}` global aggregates diverge: "
                f"upstream(s,a,mn,mx,c,nl)={upstream_agg}, "
                f"published={pub_agg}"
            )


def _check_sensor_aggregates_by_event_class(
    con: duckdb.DuckDBPyConnection, sensors: tuple[str, ...]
) -> None:
    """Check 6: per-sensor aggregates grouped by `event_class` match exactly."""
    for col in sensors:
        quoted = _quote(col)
        rows = con.execute(
            f"""
            WITH
            u AS (
                SELECT
                    event_class,
                    SUM({quoted}) AS s, AVG({quoted}) AS a,
                    MIN({quoted}) AS mn, MAX({quoted}) AS mx,
                    COUNT({quoted}) AS c,
                    COUNT(*) - COUNT({quoted}) AS nl
                FROM upstream_obs
                GROUP BY event_class
            ),
            p AS (
                SELECT
                    event_class,
                    SUM({quoted}) AS s, AVG({quoted}) AS a,
                    MIN({quoted}) AS mn, MAX({quoted}) AS mx,
                    COUNT({quoted}) AS c,
                    COUNT(*) - COUNT({quoted}) AS nl
                FROM pub_obs
                GROUP BY event_class
            )
            SELECT COALESCE(u.event_class, p.event_class) AS event_class,
                   u.s, u.a, u.mn, u.mx, u.c, u.nl,
                   p.s, p.a, p.mn, p.mx, p.c, p.nl
            FROM u
            FULL OUTER JOIN p USING (event_class)
            WHERE u.s  IS DISTINCT FROM p.s
               OR u.a  IS DISTINCT FROM p.a
               OR u.mn IS DISTINCT FROM p.mn
               OR u.mx IS DISTINCT FROM p.mx
               OR u.c  IS DISTINCT FROM p.c
               OR u.nl IS DISTINCT FROM p.nl
            ORDER BY event_class
            """
        ).fetchall()
        if rows:
            raise ParitySensorAggregatesByEventClassError(
                f"sensor `{col}` per-event-class aggregates diverge for "
                f"{len(rows)} event class(es); first: {rows[0]}"
            )


def _check_instance_timestamps(con: duckdb.DuckDBPyConnection) -> None:
    """Check 7: per-instance MIN/MAX timestamp matches upstream / catalog / pub."""
    rows = con.execute(
        """
        WITH
        upstream AS (
            SELECT instance_id,
                   MIN("timestamp") AS min_ts,
                   MAX("timestamp") AS max_ts
            FROM upstream_obs
            GROUP BY instance_id
        ),
        catalog AS (
            SELECT instance_id, start_ts, end_ts FROM pub_instances
        ),
        pub AS (
            SELECT instance_id,
                   MIN("timestamp") AS min_ts,
                   MAX("timestamp") AS max_ts
            FROM pub_obs
            GROUP BY instance_id
        )
        SELECT COALESCE(u.instance_id, c.instance_id, p.instance_id)
                   AS instance_id,
               u.min_ts AS upstream_min, u.max_ts AS upstream_max,
               c.start_ts AS catalog_start, c.end_ts AS catalog_end,
               p.min_ts AS pub_min, p.max_ts AS pub_max
        FROM upstream u
        FULL OUTER JOIN catalog c USING (instance_id)
        FULL OUTER JOIN pub p USING (instance_id)
        WHERE u.min_ts IS DISTINCT FROM c.start_ts
           OR u.max_ts IS DISTINCT FROM c.end_ts
           OR u.min_ts IS DISTINCT FROM p.min_ts
           OR u.max_ts IS DISTINCT FROM p.max_ts
        ORDER BY instance_id
        """
    ).fetchall()
    if rows:
        raise ParityInstanceTimestampsError(
            f"per-instance timestamps diverge for {len(rows)} instance(s); "
            f"first: {rows[0]}"
        )


def _check_real_well_count(con: duckdb.DuckDBPyConnection) -> None:
    """Check 8: distinct real-Well count matches the pinned upstream count.

    Compares three counts: the count of distinct ``WELL-NNNNN`` prefixes
    in the staged upstream tree, the row count of ``wells.parquet``, and
    the pinned ``EXPECTED_REAL_WELL_COUNT`` (40 at git tag ``v.1.70.0``
    / dataset version ``2.0.0``). Any disagreement is a hard fail.
    """
    upstream_count = con.execute(
        """
        SELECT COUNT(DISTINCT
            CAST(regexp_extract(instance_id, '^WELL-0*([0-9]+)_', 1) AS INTEGER)
        )
        FROM upstream_obs
        WHERE starts_with(instance_id, 'WELL-')
        """
    ).fetchone()[0]
    pub_count = con.execute("SELECT COUNT(*) FROM pub_wells").fetchone()[0]
    if (
        upstream_count != EXPECTED_REAL_WELL_COUNT
        or pub_count != EXPECTED_REAL_WELL_COUNT
    ):
        raise ParityRealWellCountError(
            f"real-Well count diverges: upstream={upstream_count}, "
            f"wells.parquet={pub_count}, pinned={EXPECTED_REAL_WELL_COUNT}"
        )


def _check_instance_count_per_event_class(con: duckdb.DuckDBPyConnection) -> None:
    """Check 9: per-event-class instance count matches upstream's folder file count.

    Each upstream file is one Instance, so ``COUNT(DISTINCT instance_id)``
    grouped by ``event_class`` over ``upstream_obs`` is equivalent to the
    file count of ``upstream/dataset/N/`` for each ``N`` (and earlier
    checks would already have caught a missing file).
    """
    rows = con.execute(
        """
        WITH
        upstream AS (
            SELECT event_class, COUNT(DISTINCT instance_id) AS n
            FROM upstream_obs
            GROUP BY event_class
        ),
        catalog AS (
            SELECT event_class, COUNT(*) AS n
            FROM pub_instances
            GROUP BY event_class
        )
        SELECT COALESCE(u.event_class, c.event_class) AS event_class,
               u.n AS upstream_n, c.n AS catalog_n
        FROM upstream u
        FULL OUTER JOIN catalog c USING (event_class)
        WHERE u.n IS DISTINCT FROM c.n
        ORDER BY event_class
        """
    ).fetchall()
    if rows:
        raise ParityInstanceCountPerEventClassError(
            f"per-event-class instance count diverges for {len(rows)} "
            f"event class(es): {rows}"
        )
