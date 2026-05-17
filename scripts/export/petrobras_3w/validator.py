"""Pre-publish validation hook for the Petrobras 3W export.

Invoked unconditionally before parquet writes. The full set of nine
invariants from CONTEXT.md (`Petrobras 3W dataset — pre-publish
validation`) gets filled in across subsequent slices as more tables are
added. This slice covers:

`event_types` (from #19):
- `event_types.event_class` is the PK and is unique.
- `event_types` has exactly 10 rows.
- `has_transient = false` exactly for event_classes {0, 3, 4}.
- `transient_code = event_class + 100` when `has_transient = true`,
  NULL otherwise.

`instances` (#20):
- `instance_id` is unique (rule 1 from CONTEXT.md).
- Every `event_class` exists in `event_types` (rule 4 — FK integrity).
- `well_kind` is one of `{real, simulated, drawn}`; `well_id` is
  non-NULL iff `well_kind = real` (matches the well-kind contract in
  CONTEXT.md's Language section).
- `n_rows_transient` is NULL exactly when the row's `event_class` has
  `has_transient = false` in `event_types`.
- The four `n_rows_*` columns sum to `n_rows` for every row (treating
  the NULL `n_rows_transient` as zero).

`wells` (#21):
- Every non-NULL `instances.well_id` exists in `wells.well_id` (rule 3
  — FK integrity).
- `wells.well_id` is limited to the union of `instances.well_id WHERE
  well_kind = 'real'` (rule 8 — no synthetic IDs leak in).
- `wells.well_id` rowcount matches the pinned real-Well count derived
  from upstream filename prefixes at `v.1.70.0` (rule 7,
  EXPECTED_REAL_WELL_COUNT = 40). Upstream's `dataset/README.md`
  states "42 real wells covered" but only 40 IDs actually appear in
  instance filenames (IDs 17 and 18 are absent); the validator pins on
  the observed 40 so upstream version drift surfaces as a hard fail.

Also emits the pinned upstream identity (git tag + dataset version) to
the validation log so consumers reading export output can verify the
upstream snapshot, per ADR-0002 and issue #19's acceptance criteria.
"""

from __future__ import annotations

import logging

import duckdb

from scripts.transform.petrobras_3w.constants import (
    PIN_DATASET_VERSION,
    PIN_GIT_TAG,
)
from scripts.transform.petrobras_3w.upstream_stager import DatasetIni

EXPECTED_EVENT_TYPES_COUNT = 10
NON_TRANSIENT_EVENT_CLASSES = (0, 3, 4)
VALID_WELL_KINDS = ("real", "simulated", "drawn")
# Distinct real-Well IDs at the pinned upstream tag `v.1.70.0` /
# dataset version `2.0.0`. Derived by listing every
# `dataset/N/WELL-NNNNN_*` filename prefix in the upstream tree.
EXPECTED_REAL_WELL_COUNT = 40


class EventTypeCountError(Exception):
    """`event_types` row count diverges from the upstream pinned 10."""


class EventTypeTransientError(Exception):
    """`has_transient` / `transient_code` diverges from the pinned upstream."""


class EventTypePkError(Exception):
    """`event_types.event_class` has duplicate rows."""


class UpstreamDatasetVersionError(Exception):
    """Parsed `dataset.ini` reports a version that does not match the pin."""


class InstancePkError(Exception):
    """`instances.instance_id` has duplicate rows (rule 1)."""


class InstanceEventClassFkError(Exception):
    """`instances.event_class` references a row not in `event_types` (rule 4)."""


class InstanceWellKindError(Exception):
    """`well_kind` is outside `{real, simulated, drawn}` or `well_id` does
    not match the well-kind contract (non-NULL iff `well_kind = real`)."""


class InstanceTransientNullnessError(Exception):
    """`n_rows_transient` nullness does not match `event_types.has_transient`."""


class InstanceRowCountAccountingError(Exception):
    """`n_rows_warmup_null + n_rows_normal + n_rows_transient + n_rows_steady`
    does not equal `n_rows` for at least one Instance."""


class WellsIdFkError(Exception):
    """An `instances.well_id` is non-NULL but missing from `wells` (rule 3)."""


class WellsRowCountError(Exception):
    """`wells` rowcount diverges from the pinned upstream real-Well count
    (rule 7). Likely upstream version drift; refresh required."""


class WellsKindError(Exception):
    """`wells.well_id` is not the well_id of any `well_kind = 'real'`
    instance (rule 8). Synthetic / simulated / drawn IDs must not leak
    into the real-Well master."""


def log_pinned_upstream(
    dataset_ini: DatasetIni, logger: logging.Logger | None = None
) -> None:
    """Emit the pinned git tag + dataset version + parsed dataset version.

    The parsed version is asserted to equal `PIN_DATASET_VERSION`: a
    mismatch means the pinned git tag now ships a different upstream
    dataset version than when this code was pinned, and a maintainer
    review is required (per ADR-0002's event-driven refresh policy).
    """
    logger = logger or logging.getLogger("petrobras_3w.export")
    logger.info(
        "petrobras_3w upstream: git_tag=%s dataset_version=%s",
        PIN_GIT_TAG,
        PIN_DATASET_VERSION,
    )
    if dataset_ini.dataset_version != PIN_DATASET_VERSION:
        raise UpstreamDatasetVersionError(
            f"upstream dataset.ini reports dataset version "
            f"{dataset_ini.dataset_version!r} but pipeline is pinned to "
            f"{PIN_DATASET_VERSION!r} at git tag {PIN_GIT_TAG!r}"
        )


def validate(
    con: duckdb.DuckDBPyConnection,
    dataset_ini: DatasetIni,
    logger: logging.Logger | None = None,
) -> None:
    log_pinned_upstream(dataset_ini, logger=logger)
    _validate_event_types_row_count(con)
    _validate_event_types_pk(con)
    _validate_event_types_transient(con)
    _validate_instances_pk(con)
    _validate_instances_event_class_fk(con)
    _validate_instances_well_kind(con)
    _validate_instances_transient_nullness(con)
    _validate_instances_row_count_accounting(con)
    _validate_wells_row_count(con)
    _validate_wells_id_fk(con)
    _validate_wells_kind(con)


def _validate_event_types_row_count(con: duckdb.DuckDBPyConnection) -> None:
    row_count = con.execute("SELECT COUNT(*) FROM event_types").fetchone()[0]
    if row_count != EXPECTED_EVENT_TYPES_COUNT:
        raise EventTypeCountError(
            f"event_types has {row_count} row(s); upstream pin expects "
            f"{EXPECTED_EVENT_TYPES_COUNT}"
        )


def _validate_event_types_pk(con: duckdb.DuckDBPyConnection) -> None:
    duplicate_groups = con.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT event_class
            FROM event_types
            GROUP BY event_class
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    if duplicate_groups:
        raise EventTypePkError(
            f"event_types has {duplicate_groups} duplicate event_class value(s)"
        )


def _validate_event_types_transient(con: duckdb.DuckDBPyConnection) -> None:
    """`has_transient` toggles must match upstream pin; `transient_code`
    must equal `event_class + 100` when transient, NULL otherwise.
    """
    non_transient = sorted(
        row[0]
        for row in con.execute(
            "SELECT event_class FROM event_types WHERE has_transient = false"
        ).fetchall()
    )
    if tuple(non_transient) != NON_TRANSIENT_EVENT_CLASSES:
        raise EventTypeTransientError(
            f"non-transient event classes are {non_transient}; upstream pin "
            f"expects {list(NON_TRANSIENT_EVENT_CLASSES)}"
        )

    bad_codes = con.execute(
        """
        SELECT COUNT(*) FROM event_types
        WHERE
            (has_transient = true  AND transient_code IS DISTINCT FROM event_class + 100)
            OR
            (has_transient = false AND transient_code IS NOT NULL)
        """
    ).fetchone()[0]
    if bad_codes:
        raise EventTypeTransientError(
            f"event_types has {bad_codes} row(s) with inconsistent transient_code"
        )


def _validate_instances_pk(con: duckdb.DuckDBPyConnection) -> None:
    duplicate_groups = con.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT instance_id
            FROM instances
            GROUP BY instance_id
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    if duplicate_groups:
        raise InstancePkError(
            f"instances has {duplicate_groups} duplicate instance_id value(s)"
        )


def _validate_instances_event_class_fk(con: duckdb.DuckDBPyConnection) -> None:
    orphans = con.execute(
        """
        SELECT COUNT(*) FROM instances i
        LEFT JOIN event_types et ON et.event_class = i.event_class
        WHERE et.event_class IS NULL
        """
    ).fetchone()[0]
    if orphans:
        raise InstanceEventClassFkError(
            f"instances has {orphans} row(s) whose event_class is not in event_types"
        )


def _validate_instances_well_kind(con: duckdb.DuckDBPyConnection) -> None:
    bad_kind = con.execute(
        f"""
        SELECT COUNT(*) FROM instances
        WHERE well_kind NOT IN {VALID_WELL_KINDS}
        """
    ).fetchone()[0]
    if bad_kind:
        raise InstanceWellKindError(
            f"instances has {bad_kind} row(s) with well_kind outside "
            f"{list(VALID_WELL_KINDS)}"
        )
    # `well_id` is non-NULL iff `well_kind = 'real'`.
    bad_well_id = con.execute(
        """
        SELECT COUNT(*) FROM instances
        WHERE (well_kind = 'real'     AND well_id IS NULL)
           OR (well_kind <> 'real'    AND well_id IS NOT NULL)
        """
    ).fetchone()[0]
    if bad_well_id:
        raise InstanceWellKindError(
            f"instances has {bad_well_id} row(s) where well_id nullness does "
            f"not match the well-kind contract (non-NULL iff well_kind = 'real')"
        )


def _validate_instances_transient_nullness(con: duckdb.DuckDBPyConnection) -> None:
    mismatches = con.execute(
        """
        SELECT COUNT(*) FROM instances i
        JOIN event_types et ON et.event_class = i.event_class
        WHERE (et.has_transient = true  AND i.n_rows_transient IS NULL)
           OR (et.has_transient = false AND i.n_rows_transient IS NOT NULL)
        """
    ).fetchone()[0]
    if mismatches:
        raise InstanceTransientNullnessError(
            f"instances has {mismatches} row(s) whose n_rows_transient nullness "
            f"does not match event_types.has_transient"
        )


def _validate_instances_row_count_accounting(con: duckdb.DuckDBPyConnection) -> None:
    mismatches = con.execute(
        """
        SELECT COUNT(*) FROM instances
        WHERE n_rows_warmup_null
            + n_rows_normal
            + COALESCE(n_rows_transient, 0)
            + n_rows_steady
          <> n_rows
        """
    ).fetchone()[0]
    if mismatches:
        raise InstanceRowCountAccountingError(
            f"instances has {mismatches} row(s) where the four n_rows_* "
            f"sub-counts do not sum to n_rows"
        )


def _validate_wells_row_count(con: duckdb.DuckDBPyConnection) -> None:
    """Rule 7: `wells.parquet` rowcount equals the pinned real-Well count."""
    row_count = con.execute("SELECT COUNT(*) FROM wells").fetchone()[0]
    if row_count != EXPECTED_REAL_WELL_COUNT:
        raise WellsRowCountError(
            f"wells has {row_count} row(s); upstream pin "
            f"({PIN_GIT_TAG} / dataset {PIN_DATASET_VERSION}) expects "
            f"{EXPECTED_REAL_WELL_COUNT}. Likely upstream drift — refresh."
        )


def _validate_wells_kind(con: duckdb.DuckDBPyConnection) -> None:
    """Rule 8: every `wells.well_id` is the `well_id` of at least one
    `well_kind = 'real'` instance.
    """
    orphans = con.execute(
        """
        SELECT COUNT(*) FROM wells w
        WHERE NOT EXISTS (
            SELECT 1 FROM instances i
            WHERE i.well_kind = 'real' AND i.well_id = w.well_id
        )
        """
    ).fetchone()[0]
    if orphans:
        raise WellsKindError(
            f"wells has {orphans} row(s) whose well_id does not appear in any "
            f"real-Well instance"
        )


def _validate_wells_id_fk(con: duckdb.DuckDBPyConnection) -> None:
    """Rule 3: every non-NULL `instances.well_id` exists in `wells`."""
    orphans = con.execute(
        """
        SELECT COUNT(*) FROM instances i
        LEFT JOIN wells w ON w.well_id = i.well_id
        WHERE i.well_id IS NOT NULL AND w.well_id IS NULL
        """
    ).fetchone()[0]
    if orphans:
        raise WellsIdFkError(
            f"instances has {orphans} row(s) whose well_id is not in wells"
        )
