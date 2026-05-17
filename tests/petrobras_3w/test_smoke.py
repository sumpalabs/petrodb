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
from scripts.export.petrobras_3w import parity, validator
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
        staging_dir=staging,
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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )

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
    assert set(schema_payload["tables"]) == {
        "event_types",
        "wells",
        "instances",
        "observations",
    }
    obs_cols = {c["name"] for c in schema_payload["tables"]["observations"]["columns"]}
    # event_class lives in the hive partition, not in the file body — but
    # we surface it as a logical column in the schema so consumers see
    # the full data model. The constant columns instance_id / well_id /
    # well_kind are present in every file body.
    assert {
        "event_class",
        "instance_id",
        "well_id",
        "well_kind",
        "timestamp",
        "class",
    }.issubset(obs_cols)
    # Hyphenated source columns survive into the file body and the docs.
    assert "P-PDG" in obs_cols
    obs_hive_cols = {
        c["name"]
        for c in schema_payload["tables"]["observations"]["columns"]
        if c.get("hive_partition")
    }
    assert obs_hive_cols == {"event_class"}
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

    # The glossary intro no longer refers to issue #22 as future work; the
    # Observations writer landed there. Stale forward-references would
    # confuse consumers reading the published docs.
    assert "once issue #22 lands" not in schema_md, (
        "stale '#22 lands' forward-reference in schema.md"
    )

    # Sensor column descriptions are inlined in the observations table — not
    # left blank with the glossary as the only reference.
    obs_section, _, _ = schema_md.partition("## Sensor-column glossary")
    _, _, observations_block = obs_section.partition("### `observations`")
    assert "Downhole pressure at the PDG" in observations_block, (
        "observations P-PDG row should inline upstream's sensor description"
    )

    # README records the pinned git tag + dataset version.
    readme = (out_dir / "README.md").read_text()
    assert PIN_GIT_TAG in readme
    assert PIN_DATASET_VERSION in readme

    # Four canonical query examples from issue #24 acceptance criteria must
    # be present (a load-by-event-class, b fetch-by-URL, c per-Well CV
    # split, d corpus-wide balance from catalog only).
    assert "WHERE event_class = 8" in readme, "missing event-class load query"
    assert "Fetch one specific Instance" in readme, "missing fetch-by-URL query"
    assert "leave-one-Well-out" in readme, "missing per-well CV split query"
    assert "Corpus balance from the Instance catalog" in readme, (
        "missing corpus-balance catalog-only query"
    )

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
        staging_dir=staging,
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
    # The Observations manifest is surfaced.
    assert "petrobras_3w/observations/_files.json" in first_index
    # The observations hive-glob query example is on the index page.
    assert "observations/event_class=8/*.parquet" in first_index
    # Pin metadata is surfaced on the site.
    assert PIN_GIT_TAG in first_index
    assert PIN_DATASET_VERSION in first_index

    # Re-running must produce byte-identical output (no duplicate blocks).
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )

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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )

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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )

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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )

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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )
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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )
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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )
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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )
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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )

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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )

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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )

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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )

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
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )

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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )

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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


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
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


# ---------------------------------------------------------------------------
# observations time-series (issue #22)
# ---------------------------------------------------------------------------


def _run_pipeline(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Helper: run the full pipeline and return (db_path, out_dir, staging)."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    export_orch.run(
        db_path=db_path,
        output_dir=out_dir,
        dataset_ini=dataset_ini,
        staging_dir=staging,
    )
    return db_path, out_dir, staging


def test_observations_layout(tmp_path: Path) -> None:
    """One parquet per Instance under `observations/event_class=N/...`."""
    _, out_dir, _ = _run_pipeline(tmp_path)

    obs_root = out_dir / "observations"
    assert obs_root.is_dir()

    # Primary fixtures land in their declared partitions.
    primary = {
        0: "WELL-00001_20120101000000",
        1: "WELL-00002_20120102000000",
        3: "WELL-00003_20120103000000",
        8: "SIMULATED_00001",
        9: "DRAWN_00001",
    }
    for event_class, instance_id in primary.items():
        target = obs_root / f"event_class={event_class}" / f"{instance_id}.parquet"
        assert target.exists(), f"missing observations file: {target}"

    # The padding event-0 fixtures are also published — total partition
    # count of event_class=0 should match the count of event_0 instances
    # in the catalog (1 primary + 37 padding = 38).
    event_0_files = sorted((obs_root / "event_class=0").glob("*.parquet"))
    assert len(event_0_files) == 38


def test_observations_preserves_upstream_columns_and_adds_constants(
    tmp_path: Path,
) -> None:
    """Body columns include hyphenated source columns + the three constants;
    event_class is NOT stored in the file body (hive-only).
    """
    _, out_dir, _ = _run_pipeline(tmp_path)

    target = (
        out_dir / "observations" / "event_class=1" / "WELL-00002_20120102000000.parquet"
    )
    con = duckdb.connect()
    # `hive_partitioning=false` because we are inspecting the file body
    # specifically — DuckDB's hive autodetect would otherwise synthesize
    # `event_class` from the parent directory name and mask the check.
    described = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{target}', hive_partitioning=false)"
    ).fetchall()
    cols = {row[0] for row in described}

    # Hyphenated source column survives the writer.
    assert "P-PDG" in cols
    # The body carries `class`, `state`, `timestamp` from upstream.
    assert {"class", "state", "timestamp"}.issubset(cols)
    # The three constant identifiers are added per row.
    assert {"instance_id", "well_id", "well_kind"}.issubset(cols)
    # `event_class` is NOT in the body — it lives in the hive partition.
    assert "event_class" not in cols

    # Constant columns are actually constant within the file.
    rows = con.execute(
        f"SELECT DISTINCT instance_id, well_id, well_kind "
        f"FROM read_parquet('{target}', hive_partitioning=false)"
    ).fetchall()
    assert rows == [("WELL-00002_20120102000000", 2, "real")]


def test_observations_simulated_well_id_null(tmp_path: Path) -> None:
    """Simulated and drawn Instances carry NULL well_id in the body."""
    _, out_dir, _ = _run_pipeline(tmp_path)

    target = out_dir / "observations" / "event_class=8" / "SIMULATED_00001.parquet"
    con = duckdb.connect()
    rows = con.execute(
        f"SELECT DISTINCT well_id, well_kind FROM read_parquet('{target}')"
    ).fetchall()
    assert rows == [(None, "simulated")]


def test_observations_manifest_lists_every_file(tmp_path: Path) -> None:
    """`observations/_files.json` enumerates every published file in
    catalog order (sorted by event_class, then instance_id).
    """
    _, out_dir, _ = _run_pipeline(tmp_path)

    manifest = json.loads((out_dir / "observations" / "_files.json").read_text())

    # 5 primary + 37 padding = 42 published Observations files.
    assert len(manifest) == 42
    # Every entry resolves to an actual file.
    for rel in manifest:
        assert (out_dir / "observations" / rel).exists(), f"missing {rel}"
    # Manifest contains relative paths only (no http URLs leaking in).
    for rel in manifest:
        assert not rel.startswith("http"), rel
        assert rel.startswith("event_class="), rel
    # Manifest is sorted by (event_class, instance_id) — matches catalog order.
    assert manifest == sorted(manifest)


def test_observations_query_pattern_in_readme(tmp_path: Path) -> None:
    """The published README documents the hive-glob query pattern with
    `well_kind = 'real'` filtering (parallel to the acceptance criterion).
    """
    _, out_dir, _ = _run_pipeline(tmp_path)

    readme = (out_dir / "README.md").read_text()
    assert "observations/event_class=8/*.parquet" in readme
    assert "well_kind = 'real'" in readme


def test_observations_event_class_in_schema_sql_is_quoted_safely(
    tmp_path: Path,
) -> None:
    """The published schema.sql round-trips hyphenated identifiers."""
    _, out_dir, _ = _run_pipeline(tmp_path)
    schema_sql = (out_dir / "schema.sql").read_text()
    # The hyphenated sensor columns must be quoted in the DDL.
    assert '"P-PDG"' in schema_sql
    # The observations table CREATE TABLE is emitted.
    assert "CREATE TABLE observations" in schema_sql


def test_validator_rejects_observations_orphan(tmp_path: Path) -> None:
    """Rule 2: every observations `instance_id` must exist in `instances`."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    # Delete one Instance row but leave its staged parquet in place — the
    # observations view still sees it, so rule 2 trips.
    with duckdb.connect(str(db_path)) as con:
        con.execute("DELETE FROM instances WHERE instance_id = 'SIMULATED_00001'")

    with pytest.raises(validator.ObservationsInstanceFkError):
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


def test_validator_rejects_observations_row_count_mismatch(tmp_path: Path) -> None:
    """Rule 5: per-Instance row count must equal `instances.n_rows`."""
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    # Bump `n_rows` AND `n_rows_steady` by the same amount so the four
    # buckets still sum to n_rows (rule from #20 stays happy) but the
    # catalog claims one more row than the observations actually contain
    # — exactly the divergence rule 5 watches for.
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            "UPDATE instances "
            "SET n_rows = n_rows + 1, n_rows_steady = n_rows_steady + 1 "
            "WHERE instance_id = 'WELL-00001_20120101000000'"
        )

    with pytest.raises(validator.ObservationsRowCountError):
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


def _rewrite_staged_instance(staged_path: Path, mutate_sql: str) -> None:
    """Read the staged instance parquet, apply `mutate_sql` against the
    `staged` temp table, and overwrite the file in place.

    Used to surgically break a single per-Observation invariant *after*
    the transform pipeline has built the catalog, so the validator's
    catalog-side checks (bucket accounting, FK, etc.) still pass and
    the targeted Observation-side rule is the failing one.
    """
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TEMP TABLE staged AS "
            f"SELECT * FROM read_parquet('{staged_path}', hive_partitioning=false)"
        )
        con.execute(mutate_sql)
        con.execute(f"COPY staged TO '{staged_path}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_validator_rejects_observations_timestamp_gap(tmp_path: Path) -> None:
    """Rule 5: timestamps must be strictly monotonic at 1-second cadence.

    We run the transform pipeline first (so the catalog is clean), then
    push the last timestamp on one Instance forward by one extra second
    — this introduces a 2-second gap without changing the row count or
    bucket distribution.
    """
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    bad_path = staging / "dataset" / "1" / "WELL-00002_20120102000000.parquet"
    _rewrite_staged_instance(
        bad_path,
        # Push the latest timestamp 1 second further out, creating a gap
        # of 2 seconds between it and its predecessor.
        "UPDATE staged "
        'SET "timestamp" = "timestamp" + INTERVAL \'1 second\' '
        'WHERE "timestamp" = (SELECT MAX("timestamp") FROM staged)',
    )

    with pytest.raises(validator.ObservationsTimestampError):
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


def test_validator_rejects_observations_class_outside_domain(
    tmp_path: Path,
) -> None:
    """Rule 5: per-row `class` must lie in {NULL, 0, event_class, transient_code}.

    Replace one STEADY (class=1) row in an event-1 Instance with class=7
    (a code that belongs to a different event). Row count and bucket
    accounting on the catalog side are not affected by this in-place
    swap; only the per-observation class domain trips.
    """
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)

    bad_path = staging / "dataset" / "1" / "WELL-00002_20120102000000.parquet"
    _rewrite_staged_instance(
        bad_path,
        # Replace exactly one of the STEADY (class=1) rows with class=7.
        "UPDATE staged SET class = 7 "
        'WHERE "timestamp" = ('
        '    SELECT MIN("timestamp") FROM staged WHERE class = 1'
        ")",
    )

    with pytest.raises(validator.ObservationsClassDomainError):
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


def test_validator_rejects_observations_non_transient_class_zero(
    tmp_path: Path,
) -> None:
    """Rule 6: events 3 and 4 must carry no `class >= 100` and no `class = 0`.

    Mutating one row of an event-3 Instance to `class = 0` keeps the
    catalog's row count and bucket totals (the row was class = 3 = steady,
    becomes class = 0 = invalid for event 3 by rule 6) — wait, this
    changes the per-row class so the steady bucket count from the
    catalog would no longer match observations. To trip rule 6
    cleanly, we instead append a new event-3 Instance file by writing
    a single-row file with class = 0 and re-running transform so the
    catalog reflects the new file's 1-row count; rule 6 then fires.
    """
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)

    # Drop a new event-3 file with a single class=0 row, then build the
    # catalog from the modified staging. n_rows=1, buckets are all 0
    # except… well, none of the buckets count class=0 with event_class=3
    # because n_rows_normal excludes event 0/3/4-class instances? Let me
    # re-read CONTEXT.md: `n_rows_normal` is "rows where class=0 AND
    # event_class<>0". For event 3, class=0 row counts to normal=1.
    # Buckets: warmup=0, normal=1, transient=NULL (event 3 has_transient=
    # false), steady=0. Sum = 1 == n_rows. Catalog accounting OK.
    extra_path = staging / "dataset" / "3" / "WELL-00099_20990101000000.parquet"
    con = duckdb.connect()
    try:
        con.execute(
            "CREATE TEMP TABLE staged ("
            '    "timestamp" TIMESTAMP,'
            '    "class"     INTEGER,'
            '    "state"     INTEGER,'
            '    "P-PDG"     DOUBLE'
            ")"
        )
        con.execute(
            "INSERT INTO staged VALUES (TIMESTAMP '2099-01-01 00:00:00', 0, 0, 1.0e7)"
        )
        con.execute(f"COPY staged TO '{extra_path}' (FORMAT PARQUET)")
    finally:
        con.close()

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    # Adding a new well_id (99) bumps real-Well rowcount to 41 and trips
    # rule 7 before rule 6 — drop the freshly added wells row so rule 6
    # fires first. Also drop the corresponding instances row's well_id
    # FK so rule 3 stays happy. Easiest: also drop the new instance from
    # the wells master only; the instances table still references
    # well_id 99 which would trip rule 3 (wells FK). So delete the new
    # well_id 99 entirely from instances AND wells, leaving the staged
    # file in place so the observations view still sees it as an
    # orphan… that trips rule 2 first.
    #
    # Cleanest path: keep all the existing fixtures untouched and add
    # the new well_id to wells too, so rule 7's count becomes 41. To
    # keep rule 7 at 40, drop one padding well that has no instances
    # in `instances` table beyond its single-row event-0 fixture, then
    # delete that instance and its staged file.
    with duckdb.connect(str(db_path)) as con:
        # Remove well 42 (a single-instance padding fixture). Also
        # remove its instance from the catalog and its staged file from
        # disk, so the catalog stays consistent.
        con.execute("DELETE FROM wells WHERE well_id = 42")
        con.execute("DELETE FROM instances WHERE well_id = 42")
    (staging / "dataset" / "0" / "WELL-00042_20120101000000.parquet").unlink()

    with pytest.raises(validator.ObservationsNonTransientClassError):
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
        )


# ---------------------------------------------------------------------------
# Parity check suite vs upstream pinned tag (issue #23)
# ---------------------------------------------------------------------------


def _mutate_published_parquet(target: Path, mutate_sql: str) -> None:
    """Re-read a published Observations parquet, apply ``mutate_sql``
    against the ``staged`` temp table, and overwrite the file in place.

    Used to surgically break a single value or row in the published
    bytes *after* the export pipeline has run, so the parity suite
    operates against a real divergence rather than a synthetic input.
    Hive partitioning is disabled on the read so the body columns line
    up 1:1 with the source on disk.
    """
    con = duckdb.connect()
    try:
        con.execute(
            f"CREATE TEMP TABLE staged AS SELECT * FROM "
            f"read_parquet('{target}', hive_partitioning=false)"
        )
        con.execute(mutate_sql)
        con.execute(f"COPY staged TO '{target}' (FORMAT PARQUET)")
    finally:
        con.close()


def test_parity_passes_on_happy_path(tmp_path: Path) -> None:
    """All nine parity checks succeed against the fixture upstream tree.

    Asserts that the smoke-fixture run is end-to-end-consistent across
    upstream / catalog / published Observations. The pipeline's own
    success in `_run_pipeline` is *implicitly* this check, but exercising
    `parity.check` directly here documents the public entry point.
    """
    _, out_dir, staging = _run_pipeline(tmp_path)
    # Re-running parity outside the orchestrator must also succeed.
    parity.check(staging, out_dir)


def test_parity_detects_sensor_value_mutation(tmp_path: Path) -> None:
    """A single-value edit to a sensor column in a published parquet trips
    at least one parity check.

    Bumps the `P-PDG` value in one row of one published Observations
    file. The catalog and upstream stay untouched, so the catalog-side
    structural checks (row count, FK, timestamps) all match — only the
    sensor-aggregate checks see the divergence.
    """
    _, out_dir, staging = _run_pipeline(tmp_path)

    target = (
        out_dir / "observations" / "event_class=1" / "WELL-00002_20120102000000.parquet"
    )
    _mutate_published_parquet(
        target,
        # Bump the first row's `P-PDG` by 1.0 — keeps row count, NULL count,
        # and class distribution intact; only the SUM/AVG/MIN/MAX trip.
        'UPDATE staged SET "P-PDG" = "P-PDG" + 1.0 '
        'WHERE "timestamp" = (SELECT MIN("timestamp") FROM staged)',
    )

    with pytest.raises(parity.ParitySensorAggregatesError):
        parity.check(staging, out_dir)


def test_parity_detects_row_drop_in_published(tmp_path: Path) -> None:
    """Dropping a published Observations row trips a row-count parity check
    (the catalog still says n_rows=12 for that Instance; the published file
    now has 11 rows). The per-event-class check fires first in the suite
    order, but the acceptance criterion only requires *some* check to fire.
    """
    _, out_dir, staging = _run_pipeline(tmp_path)

    target = (
        out_dir / "observations" / "event_class=1" / "WELL-00002_20120102000000.parquet"
    )
    _mutate_published_parquet(
        target,
        'DELETE FROM staged WHERE "timestamp" = (SELECT MAX("timestamp") FROM staged)',
    )

    with pytest.raises(parity.ParityRowCountPerEventClassError):
        parity.check(staging, out_dir)


def test_parity_detects_per_instance_only_drift(tmp_path: Path) -> None:
    """Reordering rows across two published files in the same event class
    keeps the per-event-class row count intact (check 1 passes) but trips
    the per-instance row count check (check 2). This isolates check 2
    behind its dedicated exception class so the suite catches partition-
    internal drift, not just cross-partition mismatches.
    """
    _, out_dir, staging = _run_pipeline(tmp_path)

    # Both targets are event_class=0 padding fixtures (1 row each). We
    # drop one row from `target_lose` and synthesise an extra (duplicate-
    # timestamp-shifted) row in `target_gain` so the partition's total
    # row count is unchanged.
    base = out_dir / "observations" / "event_class=0"
    target_lose = base / "WELL-00004_20120101000000.parquet"
    target_gain = base / "WELL-00005_20120101000000.parquet"
    _mutate_published_parquet(target_lose, "DELETE FROM staged")
    _mutate_published_parquet(
        target_gain,
        # Append a synthetic second row 1 second later so the partition-
        # level total stays the same but this Instance now has 2 rows
        # instead of 1. `SELECT *` over the table re-uses the full column
        # set unchanged; the column-list-by-name approach would have to be
        # kept in lockstep with the fixture's sensor inventory.
        'INSERT INTO staged BY NAME SELECT * REPLACE ("timestamp" + '
        "INTERVAL '1 second' AS \"timestamp\") FROM staged",
    )

    with pytest.raises(parity.ParityRowCountPerInstanceError):
        parity.check(staging, out_dir)


def test_parity_detects_class_label_flip(tmp_path: Path) -> None:
    """Flipping one `class` value in a published file trips the class
    distribution check (the per-row class is preserved verbatim, so any
    edit is a parity break).
    """
    _, out_dir, staging = _run_pipeline(tmp_path)

    target = (
        out_dir / "observations" / "event_class=1" / "WELL-00002_20120102000000.parquet"
    )
    _mutate_published_parquet(
        target,
        # Replace one STEADY row's class (1) with a value that already
        # exists in the published distribution (101), so the global
        # multiset changes its histogram without introducing a new value.
        'UPDATE staged SET "class" = 101 '
        'WHERE "timestamp" = (SELECT MIN("timestamp") FROM staged WHERE "class" = 1)',
    )

    with pytest.raises(parity.ParityClassDistributionError):
        parity.check(staging, out_dir)


def test_orchestrator_aborts_publish_on_parity_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A parity divergence raised from `parity.check` propagates out of
    the orchestrator and skips the website-integration step.

    Patches `parity.check` (as imported into the orchestrator module) so
    it always raises. The website root is provided, so we can assert
    the integrator did NOT run by checking the stub README is unchanged.
    """
    db_path = tmp_path / "petrobras_3w.duckdb"
    out_dir = tmp_path / "parquet"
    staging = _populated_staging(tmp_path)
    site_root = _site_root(tmp_path)
    pristine_readme = (site_root / "README.md").read_text()

    def boom(*_args, **_kwargs) -> None:
        raise parity.ParitySensorAggregatesError("synthetic divergence")

    monkeypatch.setattr(export_orch.parity, "check", boom)

    dataset_ini = transform_orch.run(db_path=db_path, staging_dir=staging)
    with pytest.raises(parity.ParitySensorAggregatesError):
        export_orch.run(
            db_path=db_path,
            output_dir=out_dir,
            dataset_ini=dataset_ini,
            staging_dir=staging,
            website_root=site_root,
        )

    # The static site is untouched on a parity abort: the publish never
    # made it past `parity.check`.
    assert (site_root / "README.md").read_text() == pristine_readme
    assert "petrobras_3w" not in (site_root / "parquet" / "index.html").read_text()
