"""Pre-publish validation hook for the Petrobras 3W export.

Invoked unconditionally before parquet writes. The full set of nine
invariants from CONTEXT.md (`Petrobras 3W dataset — pre-publish
validation`) gets filled in across subsequent slices as more tables
are added. This slice covers the structural checks that apply once
`event_types` exists:

- `event_types.event_class` is the PK and is unique.
- `event_types` has exactly 10 rows (one per upstream `[…]` event
  section). The PRD pins this row count, so a count mismatch indicates
  upstream drift and aborts publish.
- `has_transient = false` exactly for event_classes {0, 3, 4}, matching
  the upstream TRANSIENT flags. The validator catches a future upstream
  toggle as a hard failure rather than silently mutating published bytes.
- `transient_code = event_class + 100` when `has_transient = true`,
  NULL otherwise.

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


class EventTypeCountError(Exception):
    """`event_types` row count diverges from the upstream pinned 10."""


class EventTypeTransientError(Exception):
    """`has_transient` / `transient_code` diverges from the pinned upstream."""


class EventTypePkError(Exception):
    """`event_types.event_class` has duplicate rows."""


class UpstreamDatasetVersionError(Exception):
    """Parsed `dataset.ini` reports a version that does not match the pin."""


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
