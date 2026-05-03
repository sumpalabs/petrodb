"""Compose FINDINGS.md from the volatility / reconciliation / gap outputs.

Reads the Parquets emitted by the other explore modules from the same
`output_dir` and writes a single Markdown summary that links the embedded
PNGs and lists the bucket assignments, master-coverage figures, sigla/cota
disagreements (when present), and the gap-audit headline numbers.
"""

from pathlib import Path

import duckdb

from scripts.explore.argentina import eda_plotter

OUTPUT_FILENAME = "FINDINGS.md"


def _fmt_pct(value: float | None) -> str:
    return f"{value:.3f}%" if value is not None else "n/a"


def write(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    volatility_path = output_dir / "volatility_report.parquet"
    coverage_path = output_dir / "master_coverage.parquet"
    field_agreement_path = output_dir / "master_field_agreement.parquet"
    production_only_path = output_dir / "production_only_wells.parquet"
    orphans_path = output_dir / "capitulo_iv_only_orphans.parquet"
    gap_audit_path = output_dir / "gap_audit.parquet"

    lines: list[str] = []
    lines.append("# Argentina dataset — explore-phase findings")
    lines.append("")
    lines.append(
        "Reproducible evidence behind the four-bucket schema and the "
        "master-assembly rule documented in `CONTEXT.md`. Re-run the "
        "explore orchestrator to refresh."
    )
    lines.append("")

    lines.append("## Volatility scan")
    lines.append("")
    lines.append(
        "Per-`idpozo` cross-year `COUNT(DISTINCT)` over the staged "
        "production rows. NULLs are excluded; a well is counted as "
        '"changed" only if it has more than one distinct non-null value.'
    )
    lines.append("")
    if volatility_path.exists():
        rows = con.execute(
            f"""
            SELECT expected_bucket, column_name, wells_with_change,
                   wells_with_value, total_wells, pct_changed
            FROM read_parquet('{volatility_path}')
            ORDER BY expected_bucket, column_name
            """
        ).fetchall()
        lines.append(
            "| Bucket | Column | Wells changed | Wells w/ value | "
            "Total wells | % changed |"
        )
        lines.append("| --- | --- | ---: | ---: | ---: | ---: |")
        for bucket, col, changed, with_value, total, pct in rows:
            lines.append(
                f"| {bucket} | `{col}` | {changed} | {with_value} | "
                f"{total} | {_fmt_pct(pct)} |"
            )
    lines.append("")

    lines.append("## Master reconciliation")
    lines.append("")
    if coverage_path.exists():
        rows = con.execute(
            f"""
            SELECT source, row_count, distinct_idpozo
            FROM read_parquet('{coverage_path}') ORDER BY source
            """
        ).fetchall()
        lines.append("| Source | Rows | Distinct `idpozo` |")
        lines.append("| --- | ---: | ---: |")
        for src, row_count, distinct in rows:
            row_str = "n/a" if row_count is None else str(row_count)
            lines.append(f"| {src} | {row_str} | {distinct} |")
        lines.append("")

    if production_only_path.exists():
        (n_prod_only,) = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{production_only_path}')"
        ).fetchone()
        lines.append(
            f"- **Production-only wells (absent from capitulo-iv):** "
            f"{n_prod_only}. See `production_only_wells.parquet`."
        )
    if orphans_path.exists():
        (n_orphans,) = con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{orphans_path}')"
        ).fetchone()
        lines.append(
            f"- **Capitulo-iv-only orphan wells (never in production):** "
            f"{n_orphans}. Emitted with `has_production = false`. See "
            f"`capitulo_iv_only_orphans.parquet`."
        )
    lines.append("")

    if field_agreement_path.exists():
        lines.append("### Field agreement (capitulo-iv vs listado, overlap rows)")
        lines.append("")
        rows = con.execute(
            f"""
            SELECT column_name, agreement_count, disagreement_count,
                   overlap_well_count
            FROM read_parquet('{field_agreement_path}')
            ORDER BY disagreement_count DESC, column_name
            """
        ).fetchall()
        lines.append("| Column | Agreement | Disagreement | Overlap rows |")
        lines.append("| --- | ---: | ---: | ---: |")
        for col, agree, disagree, overlap in rows:
            lines.append(f"| `{col}` | {agree} | {disagree} | {overlap} |")
        lines.append("")
        lines.append(
            "Trust rule: `capitulo-iv` wins on every overlapping field "
            "(regulatory file). The disagreements above — typically "
            "concentrated in `sigla` and `cota` — are documented evidence "
            "for that rule, not an issue to auto-resolve."
        )
        lines.append("")

    lines.append("## Gap audit")
    lines.append("")
    if gap_audit_path.exists():
        row = con.execute(
            f"""
            SELECT
                COUNT(*) AS wells,
                SUM(CASE WHEN gap_count > 0 THEN 1 ELSE 0 END) AS wells_with_gaps,
                MAX(gap_count) AS max_gap_count,
                MAX(longest_gap_months) AS max_longest_gap
            FROM read_parquet('{gap_audit_path}')
            """
        ).fetchone()
        wells, wells_with_gaps, max_gap_count, max_longest_gap = row
        lines.append(f"- Wells in production: **{wells}**")
        lines.append(
            f"- Wells with one or more source-month gaps in [first, last]: "
            f"**{wells_with_gaps or 0}**"
        )
        lines.append(f"- Maximum gap-count seen on any well: **{max_gap_count or 0}**")
        lines.append(
            f"- Longest single gap seen on any well: **{max_longest_gap or 0} months**"
        )
        lines.append("")
        lines.append(
            "These gaps justify the date-completeness rule for "
            "`monthly_production` (the time-series destination is "
            "gap-filled with NULL measurement rows). The operator-history "
            "and event tables preserve the gaps as NULL intervals — there "
            "the gap is the data."
        )
        lines.append("")

    lines.append("## Plots")
    lines.append("")
    for png in eda_plotter.PLOTS:
        lines.append(f"![{png}]({png})")
    lines.append("")

    (output_dir / OUTPUT_FILENAME).write_text("\n".join(lines))
