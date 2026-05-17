"""Shallow-clone the upstream Petrobras 3W repo at the pinned git tag.

Two responsibilities:

- `stage(staging_dir)` — idempotently `git clone --depth 1 --branch <tag>`
  the upstream repo into `staging_dir`. If the staging dir already has a
  `dataset/dataset.ini`, the clone is skipped (tests can pre-populate a
  minimal fixture).
- `parse_dataset_ini(staging_dir)` — extract every piece of structured
  information the rest of the pipeline needs from `dataset/dataset.ini`:
  the dataset semver, the per-event class table, the sensor-column glossary.

The parser is the single source of truth for event-class metadata: the
canonical `NAMES`, `LABEL`s, `DESCRIPTION`s, and `TRANSIENT` flags all
come from `dataset.ini`, so a future upstream rename surfaces as a
parse-time change rather than silent drift.
"""

from __future__ import annotations

import configparser
import subprocess
from dataclasses import dataclass
from pathlib import Path

from scripts.transform.petrobras_3w.constants import (
    PIN_GIT_TAG,
    UPSTREAM_DATASET_INI_RELPATH,
    UPSTREAM_REPO_URL,
)


@dataclass(frozen=True)
class EventTypeSpec:
    """One row of the future `event_types` table, sourced from `dataset.ini`."""

    event_class: int
    name: str
    description: str
    has_transient: bool


@dataclass(frozen=True)
class DatasetIni:
    """Structured view over upstream `dataset.ini`."""

    dataset_version: str
    event_types: tuple[EventTypeSpec, ...]
    sensor_descriptions: dict[str, str]


def stage(staging_dir: Path) -> Path:
    """Shallow-clone the pinned upstream tag if not already staged.

    Returns the staging directory. Idempotent: a second call with an
    already-populated `staging_dir` is a no-op. The check is the
    presence of `dataset/dataset.ini`, not git metadata, so a test
    fixture that drops just that file is enough to short-circuit.
    """
    staging_dir = Path(staging_dir)
    ini = staging_dir / UPSTREAM_DATASET_INI_RELPATH
    if ini.exists():
        return staging_dir
    staging_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            PIN_GIT_TAG,
            UPSTREAM_REPO_URL,
            str(staging_dir),
        ],
        check=True,
    )
    return staging_dir


def parse_dataset_ini(staging_dir: Path) -> DatasetIni:
    """Read upstream `dataset.ini` and return a structured projection.

    The upstream file uses `configparser` with `%` interpolation, which
    bites on column-unit strings such as `[%%]`. We disable interpolation
    so those strings survive verbatim.
    """
    staging_dir = Path(staging_dir)
    ini_path = staging_dir / UPSTREAM_DATASET_INI_RELPATH
    parser = configparser.ConfigParser(interpolation=None)
    # Preserve key case verbatim — sensor column names like `QGL`, `P-PDG`
    # would otherwise be lowercased by configparser's default option-name
    # normaliser, breaking the round-trip to the published parquet.
    parser.optionxform = str
    parser.read(ini_path)

    dataset_version = parser["VERSION"]["DATASET"].strip()

    names_raw = parser["EVENTS"]["NAMES"]
    names = tuple(name.strip() for name in names_raw.replace("\n", " ").split(","))
    specs: list[EventTypeSpec] = []
    for name in names:
        section = parser[name]
        # `NORMAL` has no `TRANSIENT` key; default to false (it is not an anomaly).
        transient = section.getboolean("TRANSIENT", fallback=False)
        specs.append(
            EventTypeSpec(
                event_class=int(section["LABEL"]),
                name=name,
                description=section["DESCRIPTION"].strip(),
                has_transient=transient,
            )
        )

    sensor_descriptions = {
        column: parser["PARQUET_FILE_PROPERTIES"][column].strip()
        for column in parser["PARQUET_FILE_PROPERTIES"]
    }

    return DatasetIni(
        dataset_version=dataset_version,
        event_types=tuple(specs),
        sensor_descriptions=sensor_descriptions,
    )
