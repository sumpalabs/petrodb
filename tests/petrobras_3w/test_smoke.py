"""End-to-end smoke test for the Petrobras 3W scaffolding slice (issue #19).

Runs the transform + export orchestrators against a fixture upstream
tree (dataset.ini only), asserts that:

- `event_types.parquet` is emitted with the 10 canonical rows,
- the four cross-cutting docs are generated (schema.md/.json/.sql,
  README.md, LICENSE-3W-DATA.md),
- the static site is patched with a new tab and a root README entry,
- the validator emits the pinned upstream identity to the log.

The shallow-clone step is short-circuited: the staging directory is
pre-populated with `dataset/dataset.ini`, which the stager treats as
"already staged".
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import duckdb
import pytest

from scripts.export.petrobras_3w import orchestrator as export_orch
from scripts.export.petrobras_3w import validator
from scripts.transform.petrobras_3w import orchestrator as transform_orch
from scripts.transform.petrobras_3w.constants import (
    PIN_DATASET_VERSION,
    PIN_GIT_TAG,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "petrobras_3w"


_STUB_README = """\
# PetroData Repository

## Datasets

### Volve Production Data
Volve placeholder.

### FORCE 2020 Well Logs
FORCE placeholder.

## Access Data

placeholder
"""

_STUB_INDEX = """\
<!DOCTYPE html>
<html><body>
    <div class="container">
        <div class="tab-navigation">
            <button class="tab-button active" data-tab="volve">Volve</button>
            <button class="tab-button" data-tab="force2020">Force 2020</button>
        </div>

        <!-- Volve Tab Content -->
        <div id="volve-tab" class="tab-content active">v</div>

        <!-- Force 2020 Tab Content -->
        <div id="force2020-tab" class="tab-content">f</div>

        <footer>footer</footer>
    </div>
</body></html>
"""


def _populated_staging(tmp_path: Path) -> Path:
    """Copy the fixture upstream tree into `tmp_path/staging` so the stager
    short-circuits its `git clone` step."""
    staging = tmp_path / "staging"
    shutil.copytree(FIXTURES, staging)
    return staging


def _site_root(tmp_path: Path) -> Path:
    site_root = tmp_path / "site"
    (site_root / "parquet").mkdir(parents=True)
    (site_root / "README.md").write_text(_STUB_README)
    (site_root / "parquet" / "index.html").write_text(_STUB_INDEX)
    return site_root


def test_pipeline_emits_event_types(tmp_path: Path) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    site_root = _site_root(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        website_root=site_root,
    )

    event_types = out_dir / "event_types.parquet"
    assert event_types.exists(), "event_types.parquet was not written"

    con = duckdb.connect()
    rows = con.execute(
        f"""
        SELECT event_class, name, description, has_transient,
               transient_code, has_normal_prefix
        FROM read_parquet('{event_types}')
        ORDER BY event_class
        """
    ).fetchall()
    assert len(rows) == 10

    # event_class 0..9 in order.
    assert [r[0] for r in rows] == list(range(10))

    # Canonical names from upstream's NAMES list (PascalCase with underscores).
    assert [r[1] for r in rows] == [
        "NORMAL",
        "ABRUPT_INCREASE_OF_BSW",
        "SPURIOUS_CLOSURE_OF_DHSV",
        "SEVERE_SLUGGING",
        "FLOW_INSTABILITY",
        "RAPID_PRODUCTIVITY_LOSS",
        "QUICK_RESTRICTION_IN_PCK",
        "SCALING_IN_PCK",
        "HYDRATE_IN_PRODUCTION_LINE",
        "HYDRATE_IN_SERVICE_LINE",
    ]
    assert [r[2] for r in rows] == [
        "Normal Operation",
        "Abrupt Increase of BSW",
        "Spurious Closure of DHSV",
        "Severe Slugging",
        "Flow Instability",
        "Rapid Productivity Loss",
        "Quick Restriction in PCK",
        "Scaling in PCK",
        "Hydrate in Production Line",
        "Hydrate in Service Line",
    ]

    # `has_transient` is false for exactly {0, 3, 4}.
    non_transient = {r[0] for r in rows if not r[3]}
    assert non_transient == {0, 3, 4}

    # `transient_code = event_class + 100` when has_transient is true,
    # NULL otherwise.
    for event_class, _name, _desc, has_transient, transient_code, _hnp in rows:
        if has_transient:
            assert transient_code == event_class + 100
        else:
            assert transient_code is None

    # `has_normal_prefix` correlates with `has_transient`.
    for _, _, _, has_transient, _, has_normal_prefix in rows:
        assert has_normal_prefix == has_transient


def test_pipeline_emits_documentation(tmp_path: Path) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    for name in (
        "schema.md",
        "schema.json",
        "schema.sql",
        "README.md",
        "LICENSE-3W-DATA.md",
    ):
        assert (out_dir / name).exists(), f"{name} was not generated"

    # schema.json reflects exactly the published parquet
    schema_payload = json.loads((out_dir / "schema.json").read_text())
    assert set(schema_payload["tables"]) == {"event_types"}
    assert schema_payload["upstream"]["git_tag"] == PIN_GIT_TAG
    assert schema_payload["upstream"]["dataset_version"] == PIN_DATASET_VERSION
    schema_cols = {
        c["name"] for c in schema_payload["tables"]["event_types"]["columns"]
    }
    assert schema_cols == {
        "event_class",
        "name",
        "description",
        "has_transient",
        "transient_code",
        "has_normal_prefix",
    }

    # schema.md mirrors the 27-sensor glossary verbatim.
    schema_md = (out_dir / "schema.md").read_text()
    for column in (
        "P-PDG",
        "ABER-CKGL",
        "ESTADO-SDV-GL",
        "QGL",
        "T-PDG",
        "class",
        "state",
        "timestamp",
    ):
        assert f"`{column}`" in schema_md, f"schema.md missing {column}"

    # README records the pinned git tag + dataset version.
    readme = (out_dir / "README.md").read_text()
    assert PIN_GIT_TAG in readme
    assert PIN_DATASET_VERSION in readme

    # LICENSE-3W-DATA.md attributes CC BY 4.0 with upstream attribution.
    license_text = (out_dir / "LICENSE-3W-DATA.md").read_text()
    assert "CC BY 4.0" in license_text
    assert "petrobras/3W" in license_text


def test_website_integration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    site_root = _site_root(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        website_root=site_root,
    )
    first_readme = (site_root / "README.md").read_text()
    first_index = (site_root / "parquet" / "index.html").read_text()

    # The README and index must show the new dataset entry/tab.
    assert "### Petrobras 3W Dataset" in first_readme
    assert "import duckdb" in first_readme
    assert 'data-tab="petrobras_3w"' in first_index
    assert 'id="petrobras_3w-tab"' in first_index
    for artifact in ("README.md", "schema.md", "schema.json", "schema.sql"):
        assert f'"petrobras_3w/{artifact}"' in first_index, (
            f"index.html missing link to petrobras_3w/{artifact}"
        )
    # Pin metadata is surfaced on the site.
    assert PIN_GIT_TAG in first_index
    assert PIN_DATASET_VERSION in first_index

    # Re-running must produce byte-identical output (no duplicate blocks).
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        website_root=site_root,
    )
    assert (site_root / "README.md").read_text() == first_readme
    assert (site_root / "parquet" / "index.html").read_text() == first_index


def test_validator_logs_pinned_upstream(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    with caplog.at_level(logging.INFO, logger="petrobras_3w.export"):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert PIN_GIT_TAG in messages
    assert PIN_DATASET_VERSION in messages


def test_validator_rejects_count_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Deleting an event_type row should abort export."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    # Mutate the intermediate DB so validate() finds 9 rows instead of 10.
    with duckdb.connect(str(db_path)) as con:
        con.execute("DELETE FROM event_types WHERE event_class = 9")

    with pytest.raises(validator.EventTypeCountError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    assert not (out_dir / "event_types.parquet").exists()


def test_validator_rejects_dataset_version_drift(tmp_path: Path) -> None:
    """A staged dataset.ini reporting a different DATASET semver must abort."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    # Patch the fixture to report a different DATASET version.
    ini_path = staging / "dataset" / "dataset.ini"
    text = ini_path.read_text()
    ini_path.write_text(text.replace("DATASET = 2.0.0", "DATASET = 3.0.0"))

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    with pytest.raises(validator.UpstreamDatasetVersionError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    assert not (out_dir / "event_types.parquet").exists()
