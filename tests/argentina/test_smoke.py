"""End-to-end smoke test for the Argentina pipeline.

Runs the transform and export orchestrators against the fixture CSVs
(~3 wells × 2 years) and asserts that a placeholder wells.parquet is
emitted with the expected row count.
"""

from pathlib import Path

import duckdb
import pytest

from scripts.explore.argentina import eda_plotter
from scripts.explore.argentina import orchestrator as explore_orch
from scripts.export.argentina import orchestrator as export_orch
from scripts.export.argentina import validator
from scripts.transform.argentina import orchestrator as transform_orch

FIXTURES = Path(__file__).parent.parent / "fixtures" / "argentina"


def test_pipeline_emits_wells_parquet(tmp_path: Path) -> None:
    db_path = tmp_path / "argentina.duckdb"
    out_dir = tmp_path / "parquet"

    transform_orch.run(db_path=db_path, csv_dir=FIXTURES)
    export_orch.run(db_path=db_path, output_dir=out_dir)

    wells_parquet = out_dir / "wells.parquet"
    assert wells_parquet.exists(), "wells.parquet was not written"

    con = duckdb.connect()
    row_count = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{wells_parquet}')"
    ).fetchone()[0]
    assert row_count == 3, f"expected 3 wells in fixture output, got {row_count}"


def test_export_aborts_when_validator_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The validator hook must run unconditionally before any parquet write."""
    db_path = tmp_path / "argentina.duckdb"
    out_dir = tmp_path / "parquet"

    transform_orch.run(db_path=db_path, csv_dir=FIXTURES)

    def boom(_con: duckdb.DuckDBPyConnection) -> None:
        raise RuntimeError("validation failed")

    monkeypatch.setattr(validator, "validate", boom)

    with pytest.raises(RuntimeError, match="validation failed"):
        export_orch.run(db_path=db_path, output_dir=out_dir)

    assert not (out_dir / "wells.parquet").exists()


def test_explore_phase_writes_all_outputs(tmp_path: Path) -> None:
    """Explore orchestrator runs end-to-end against the fixture and emits
    every documented output (machine-readable Parquets, 12 PNGs, FINDINGS.md).

    The fixture is too small to reproduce the headline volatility numbers
    from CONTEXT.md — this test only exercises the wiring."""
    db_path = tmp_path / "argentina.duckdb"
    output_dir = tmp_path / "explore_out"

    explore_orch.run(db_path=db_path, csv_dir=FIXTURES, output_dir=output_dir)

    expected_tabular = (
        "volatility_report.parquet",
        "master_coverage.parquet",
        "master_field_agreement.parquet",
        "production_only_wells.parquet",
        "capitulo_iv_only_orphans.parquet",
        "gap_audit.parquet",
    )
    for name in expected_tabular:
        assert (output_dir / name).exists(), f"{name} was not written"

    for png in eda_plotter.PLOTS:
        path = output_dir / png
        assert path.exists(), f"{png} was not written"
        assert path.stat().st_size > 0, f"{png} is empty"
    assert len(eda_plotter.PLOTS) == 12

    findings = output_dir / "FINDINGS.md"
    assert findings.exists()
    body = findings.read_text()
    assert "Volatility scan" in body
    assert "Master reconciliation" in body
    assert "Gap audit" in body


def test_explore_phase_is_idempotent(tmp_path: Path) -> None:
    """Re-running the explore phase overwrites prior outputs deterministically."""
    db_path = tmp_path / "argentina.duckdb"
    output_dir = tmp_path / "explore_out"

    explore_orch.run(db_path=db_path, csv_dir=FIXTURES, output_dir=output_dir)
    first_findings = (output_dir / "FINDINGS.md").read_text()

    explore_orch.run(db_path=db_path, csv_dir=FIXTURES, output_dir=output_dir)
    second_findings = (output_dir / "FINDINGS.md").read_text()

    assert first_findings == second_findings
