"""End-to-end smoke test for the Petrobras 3W pipeline.

Runs the transform + export orchestrators against a fixture upstream
tree (dataset.ini + a handful of per-Instance parquets covering the
three well_kinds and a representative mix of has_transient/has_normal
event classes), asserts that:

- `event_types.parquet` is emitted with the 10 canonical rows,
- `instances.parquet` catalogues every staged Instance file,
- the four cross-cutting docs are generated (schema.md/.json/.sql,
  README.md, LICENSE-3W-DATA.md),
- the static site is patched with a new tab and a root README entry,
- the validator emits the pinned upstream identity to the log,
- and the validator aborts publish on the structural invariants from
  CONTEXT.md's pre-publish validation list.

The shallow-clone step is short-circuited: the staging directory is
pre-populated with `dataset/dataset.ini` + the per-Instance fixtures,
which the stager treats as "already staged".
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
    PUBLIC_BASE_URL,
)
from tests.petrobras_3w.conftest import build_instance_parquets

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
    short-circuits its `git clone` step, then materialize the per-Instance
    parquet fixtures the instances builder reads.
    """
    staging = tmp_path / "staging"
    shutil.copytree(FIXTURES, staging)
    build_instance_parquets(staging)
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
    assert set(schema_payload["tables"]) == {"event_types", "wells", "instances"}
    wells_cols = {c["name"] for c in schema_payload["tables"]["wells"]["columns"]}
    assert wells_cols == {
        "well_id",
        "n_instances",
        "first_ts",
        "last_ts",
        "n_observations",
    }
    instance_well_fks = [
        fk
        for fk in schema_payload["tables"]["instances"]["foreign_keys"]
        if fk["column"] == "well_id"
    ]
    assert any(
        fk["references_table"] == "wells" and fk["references_column"] == "well_id"
        for fk in instance_well_fks
    ), "instances.well_id should declare FK to wells.well_id"
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
    instance_cols = {
        c["name"] for c in schema_payload["tables"]["instances"]["columns"]
    }
    assert instance_cols == {
        "instance_id",
        "well_kind",
        "well_id",
        "event_class",
        "start_ts",
        "end_ts",
        "duration_s",
        "n_rows",
        "n_rows_warmup_null",
        "n_rows_normal",
        "n_rows_transient",
        "n_rows_steady",
        "source_file",
        "source_url",
    }
    instance_fks = schema_payload["tables"]["instances"]["foreign_keys"]
    assert any(
        fk["column"] == "event_class"
        and fk["references_table"] == "event_types"
        and fk["references_column"] == "event_class"
        for fk in instance_fks
    ), "instances table should declare event_class FK to event_types"

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
    # All published parquets are surfaced on the static site.
    assert "petrobras_3w/event_types.parquet" in first_index
    assert "petrobras_3w/instances.parquet" in first_index
    assert "petrobras_3w/wells.parquet" in first_index
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


# ---------------------------------------------------------------------------
# Instance catalog (issue #20)
# ---------------------------------------------------------------------------


def _read_instances(out_dir: Path) -> list[dict]:
    path = out_dir / "instances.parquet"
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT * FROM read_parquet('{path}') ORDER BY event_class, instance_id"
    ).fetchall()
    columns = [
        c[0]
        for c in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}')"
        ).fetchall()
    ]
    return [dict(zip(columns, row)) for row in rows]


def test_pipeline_emits_instances_catalog(tmp_path: Path) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    assert (out_dir / "instances.parquet").exists()
    rows = _read_instances(out_dir)
    by_id = {r["instance_id"]: r for r in rows}

    # Every primary fixture (one per representative event class across the
    # three well_kinds) lands in the catalog under its expected event class.
    primary_id_to_event_class = {
        "WELL-00001_20120101000000": 0,
        "WELL-00002_20120102000000": 1,
        "WELL-00003_20120103000000": 3,
        "SIMULATED_00001": 8,
        "DRAWN_00001": 9,
    }
    for instance_id, event_class in primary_id_to_event_class.items():
        assert instance_id in by_id, f"{instance_id} missing from catalog"
        assert by_id[instance_id]["event_class"] == event_class


def test_instances_well_kind_and_well_id(tmp_path: Path) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)
    by_id = {r["instance_id"]: r for r in _read_instances(out_dir)}

    # well_kind values reflect the upstream filename prefix.
    real = by_id["WELL-00002_20120102000000"]
    assert real["well_kind"] == "real"
    assert real["well_id"] == 2  # leading zeros stripped

    sim = by_id["SIMULATED_00001"]
    assert sim["well_kind"] == "simulated"
    assert sim["well_id"] is None

    drawn = by_id["DRAWN_00001"]
    assert drawn["well_kind"] == "drawn"
    assert drawn["well_id"] is None


def test_instances_row_count_accounting(tmp_path: Path) -> None:
    """The four `n_rows_*` columns partition `n_rows` (with NULL n_rows_transient
    treated as zero), and `n_rows_transient` is NULL exactly when the event's
    `has_transient = false`.
    """
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)
    rows = _read_instances(out_dir)

    for row in rows:
        bucket_sum = (
            row["n_rows_warmup_null"]
            + row["n_rows_normal"]
            + (row["n_rows_transient"] or 0)
            + row["n_rows_steady"]
        )
        assert bucket_sum == row["n_rows"], (
            f"sub-counts do not sum to n_rows for {row['instance_id']}"
        )

    by_id = {r["instance_id"]: r for r in rows}

    # Event 0 (NORMAL, has_transient=false): all 10 rows are class=0=event_class,
    # so they roll into n_rows_steady (not n_rows_normal — that bucket is for the
    # NORMAL precursor of an anomaly, which event 0 has no concept of).
    ev0 = by_id["WELL-00001_20120101000000"]
    assert ev0["n_rows_transient"] is None
    assert ev0["n_rows_normal"] == 0
    assert ev0["n_rows_steady"] == 10
    # Event 3 (Severe Slugging, has_transient=false): n_rows_transient is NULL.
    assert by_id["WELL-00003_20120103000000"]["n_rows_transient"] is None
    assert by_id["WELL-00003_20120103000000"]["n_rows_steady"] == 8

    # Event 1 (has_transient=true): 3 NULL + 4 NORMAL + 2 TRANSIENT + 3 STEADY.
    ev1 = by_id["WELL-00002_20120102000000"]
    assert ev1["n_rows_warmup_null"] == 3
    assert ev1["n_rows_normal"] == 4
    assert ev1["n_rows_transient"] == 2
    assert ev1["n_rows_steady"] == 3

    # Event 8 (has_transient=true, simulated): 0 warmup + 2 NORMAL + 2 TRANSIENT (108) + 1 STEADY.
    ev8 = by_id["SIMULATED_00001"]
    assert ev8["n_rows_warmup_null"] == 0
    assert ev8["n_rows_normal"] == 2
    assert ev8["n_rows_transient"] == 2
    assert ev8["n_rows_steady"] == 1


def test_instances_source_url_matches_adr0001_pattern(tmp_path: Path) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)
    rows = _read_instances(out_dir)

    for row in rows:
        expected = (
            f"{PUBLIC_BASE_URL}/observations/"
            f"event_class={row['event_class']}/{row['instance_id']}.parquet"
        )
        assert row["source_url"] == expected


def test_instances_source_file_retains_extension(tmp_path: Path) -> None:
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)
    rows = _read_instances(out_dir)

    for row in rows:
        assert row["source_file"] == f"{row['instance_id']}.parquet"


def test_validator_rejects_duplicate_instance_id(tmp_path: Path) -> None:
    """Rule 1: instance_id must be unique."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        # Duplicate an existing row to force a PK collision.
        con.execute(
            "INSERT INTO instances "
            "SELECT * FROM instances WHERE instance_id = 'SIMULATED_00001'"
        )

    with pytest.raises(validator.InstancePkError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    assert not (out_dir / "instances.parquet").exists()


def test_validator_rejects_unknown_event_class(tmp_path: Path) -> None:
    """Rule 4: every instances.event_class must exist in event_types."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        con.execute("UPDATE instances SET event_class = 42 WHERE event_class = 9")

    with pytest.raises(validator.InstanceEventClassFkError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    assert not (out_dir / "instances.parquet").exists()


def test_validator_rejects_well_id_violation(tmp_path: Path) -> None:
    """well_id is non-NULL only when well_kind = 'real'."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        con.execute(
            "UPDATE instances SET well_id = 999 WHERE instance_id = 'SIMULATED_00001'"
        )

    with pytest.raises(validator.InstanceWellKindError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)


def test_validator_rejects_transient_nullness_mismatch(tmp_path: Path) -> None:
    """n_rows_transient is NULL iff event_types.has_transient = false."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        # event_class 0 has has_transient=false, so n_rows_transient must be NULL.
        # Setting it to 0 should trip the validator.
        con.execute("UPDATE instances SET n_rows_transient = 0 WHERE event_class = 0")

    with pytest.raises(validator.InstanceTransientNullnessError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)


def test_validator_rejects_row_count_accounting_break(tmp_path: Path) -> None:
    """The four n_rows_* columns must sum to n_rows."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        con.execute(
            "UPDATE instances SET n_rows_steady = n_rows_steady + 5 "
            "WHERE instance_id = 'WELL-00001_20120101000000'"
        )

    with pytest.raises(validator.InstanceRowCountAccountingError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)


# ---------------------------------------------------------------------------
# wells master table (issue #21)
# ---------------------------------------------------------------------------


def _read_wells(out_dir: Path) -> list[dict]:
    path = out_dir / "wells.parquet"
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT * FROM read_parquet('{path}') ORDER BY well_id"
    ).fetchall()
    columns = [
        c[0]
        for c in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}')"
        ).fetchall()
    ]
    return [dict(zip(columns, row)) for row in rows]


def test_pipeline_emits_wells_master(tmp_path: Path) -> None:
    """`wells.parquet` exists with one row per distinct real well (40 rows
    per the pinned upstream tag; rule 7).
    """
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    assert (out_dir / "wells.parquet").exists()
    rows = _read_wells(out_dir)
    assert len(rows) == 40

    well_ids = [r["well_id"] for r in rows]
    # IDs 17 and 18 are absent upstream; all other IDs 1..42 are present.
    expected_ids = list(range(1, 17)) + list(range(19, 43))
    assert well_ids == expected_ids

    by_id = {r["well_id"]: r for r in rows}
    columns = set(rows[0])
    assert columns == {
        "well_id",
        "n_instances",
        "first_ts",
        "last_ts",
        "n_observations",
    }

    # WELL-00001 has exactly one event-0 fixture with 10 rows.
    one = by_id[1]
    assert one["n_instances"] == 1
    assert one["n_observations"] == 10

    # WELL-00002 has exactly one event-1 fixture with 12 rows.
    two = by_id[2]
    assert two["n_instances"] == 1
    assert two["n_observations"] == 12

    # The padding fixtures contribute exactly 1 row each.
    forty_two = by_id[42]
    assert forty_two["n_instances"] == 1
    assert forty_two["n_observations"] == 1


def test_wells_excludes_simulated_and_drawn(tmp_path: Path) -> None:
    """No `well_id` from a non-real instance appears in `wells.parquet`."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    well_ids = {r["well_id"] for r in _read_wells(out_dir)}
    # `wells.parquet` only has real-Well IDs; the simulated/drawn instances
    # have NULL well_id and contribute nothing here.
    assert None not in well_ids


def test_wells_aggregates_match_instances(tmp_path: Path) -> None:
    """`SUM(n_instances)` equals the count of real instances; likewise for
    `SUM(n_observations)` and the per-Instance `n_rows`.
    """
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    con = duckdb.connect()
    real_instance_count, real_row_total = con.execute(
        f"""
        SELECT COUNT(*), SUM(n_rows)
        FROM read_parquet('{out_dir / "instances.parquet"}')
        WHERE well_kind = 'real'
        """
    ).fetchone()
    wells_instance_total, wells_observation_total = con.execute(
        f"""
        SELECT SUM(n_instances), SUM(n_observations)
        FROM read_parquet('{out_dir / "wells.parquet"}')
        """
    ).fetchone()
    assert wells_instance_total == real_instance_count
    assert wells_observation_total == real_row_total


def test_validator_rejects_well_count_mismatch(tmp_path: Path) -> None:
    """Rule 7: real-Well rowcount must match the pinned upstream count."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        # Drop a well from the wells master to trip rule 7.
        con.execute("DELETE FROM wells WHERE well_id = 42")

    with pytest.raises(validator.WellsRowCountError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)

    assert not (out_dir / "wells.parquet").exists()


def test_validator_rejects_well_id_orphan(tmp_path: Path) -> None:
    """Rule 3: every non-NULL `instances.well_id` exists in `wells.parquet`."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        # Drop the well row but leave the instance pointing at it; this is
        # exactly the FK violation rule 3 watches for. Also re-pad an extra
        # well so the total stays at 40 and rule 7 does not trip first.
        con.execute("DELETE FROM wells WHERE well_id = 1")
        con.execute(
            "INSERT INTO wells VALUES "
            "(9999, 0, TIMESTAMP '2099-01-01', TIMESTAMP '2099-01-01', 0)"
        )

    with pytest.raises(validator.WellsIdFkError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)


def test_validator_rejects_non_real_well_in_wells(tmp_path: Path) -> None:
    """Rule 8: `wells.parquet` rows are limited to real `instances.well_id`."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    with duckdb.connect(str(db_path)) as con:
        # Replace a real-well row with one whose ID is not the well_id of any
        # `well_kind = 'real'` instance. Also drop the matching instance so
        # rule 3 (FK from instances to wells) still passes — rule 8 is what
        # this test is exercising. Keep the wells rowcount at 40 so rule 7
        # passes.
        con.execute("DELETE FROM instances WHERE well_id = 42")
        con.execute("DELETE FROM wells WHERE well_id = 42")
        con.execute(
            "INSERT INTO wells VALUES "
            "(9999, 0, TIMESTAMP '2099-01-01', TIMESTAMP '2099-01-01', 0)"
        )

    with pytest.raises(validator.WellsKindError):
        export_orch.run(db_path=db_path, output_dir=out_dir, dataset_ini=dataset_ini)
