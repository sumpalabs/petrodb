"""Surface the Argentina dataset on the static site.

Two idempotent patches:

- Root ``README.md``: add an Argentina entry under the ``## Datasets``
  section with a copy-pasteable DuckDB query example.
- ``parquet/index.html``: add an Argentina tab alongside Volve and FORCE
  2020, listing the three single-file tables, the partitioned
  ``monthly_production`` series (manifest + per-year direct downloads),
  and the schema documents.

Both patches bracket the inserted region with sentinel HTML comments so
re-running the export replaces the block in place rather than appending
a duplicate.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Sentinel markers
# ---------------------------------------------------------------------------

README_BEGIN = "<!-- argentina:begin -->"
README_END = "<!-- argentina:end -->"

INDEX_TAB_BUTTON_BEGIN = "<!-- argentina-tab-button:begin -->"
INDEX_TAB_BUTTON_END = "<!-- argentina-tab-button:end -->"
INDEX_TAB_CONTENT_BEGIN = "<!-- argentina-tab-content:begin -->"
INDEX_TAB_CONTENT_END = "<!-- argentina-tab-content:end -->"

# ---------------------------------------------------------------------------
# Anchors (only used on the first run; subsequent runs find the sentinels)
# ---------------------------------------------------------------------------

# Insert the README blurb above this header so it sits between FORCE 2020
# and the Access Data section.
README_ANCHOR = "## Access Data"

# Insert the new tab button immediately before the closing </div> of the
# tab-navigation block. Using the multi-line anchor avoids matching any of
# the many other </div> tags in the file.
INDEX_TAB_BUTTON_ANCHOR = "        </div>\n\n        <!-- Volve Tab Content -->"

# Insert the new tab content immediately before <footer>, after the
# force2020-tab block closes.
INDEX_TAB_CONTENT_ANCHOR = "        <footer>"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def integrate(website_root: Path, years: list[int]) -> None:
    """Idempotently inject the Argentina dataset entry into the static site.

    ``website_root`` is the repo root: the directory that contains
    ``README.md`` and ``parquet/index.html``. ``years`` is the list of
    monthly_production hive partitions, used to render the per-year
    download buttons. Re-running with the same inputs produces
    byte-identical output.
    """
    website_root = Path(website_root)
    _patch_root_readme(website_root / "README.md")
    _patch_index_html(website_root / "parquet" / "index.html", sorted(years))


# ---------------------------------------------------------------------------
# Root README
# ---------------------------------------------------------------------------


def _readme_payload() -> str:
    return """\

### Argentina Production Data
Monthly oil and gas production for ~85,418 wells in Argentina (2006–present),
sourced from the Secretaría de Energía public datasets:
- **wells.parquet** — static well master (~85K rows, Spanish column names)
- **well_operator_history.parquet** — slowly-changing operator transfers
- **well_events.parquet** — operational state transitions
- **monthly_production/** — hive-partitioned by `anio`, ~17.6M rows total

Aggregate 2023 production by basin, joining `wells` to the partitioned
monthly time series:

```python
import duckdb

result = duckdb.sql(\"\"\"
    SELECT w.cuenca,
           SUM(m.prod_pet) AS oil_m3,
           SUM(m.prod_gas) AS gas_mm3
    FROM 'https://dev-petrodb.ocortez.com/argentina/wells.parquet' w
    JOIN read_parquet(
      'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet',
      hive_partitioning = true
    ) m USING (idpozo)
    WHERE m.anio = 2023
    GROUP BY w.cuenca
    ORDER BY oil_m3 DESC
\"\"\").df()
```

Full per-column English docs (Spanish column identifiers preserved), the
four-bucket rationale, and three more canonical query patterns live in
[`parquet/argentina/README.md`](parquet/argentina/README.md).

"""


def _patch_root_readme(path: Path) -> None:
    text = path.read_text()
    # Trailing blank line so the next markdown heading retains its required
    # blank-line separator.
    block = f"{README_BEGIN}\n{_readme_payload()}{README_END}\n\n"
    new_text = _replace_block_or_insert_before(
        text, README_BEGIN, README_END, README_ANCHOR, block
    )
    if new_text != text:
        path.write_text(new_text)


# ---------------------------------------------------------------------------
# parquet/index.html
# ---------------------------------------------------------------------------


def _index_tab_button_payload() -> str:
    return """\
            <button class="tab-button" data-tab="argentina">
                Argentina Production
                <span class="tab-count">4 files</span>
            </button>
"""


def _index_tab_content_payload(years: list[int]) -> str:
    year_buttons = "\n".join(
        f'                        <a href="argentina/monthly_production/anio={y}/data.parquet"'
        f' download="monthly_production_{y}.parquet" class="download-button">\n'
        f"                            <span>{y}</span>\n"
        f'                            <span class="download-icon">⬇</span>\n'
        f"                        </a>"
        for y in years
    )
    year_range = f"{years[0]}–{years[-1]}" if years else "2006–present"
    return f"""\
        <!-- Argentina Tab Content -->
        <div id="argentina-tab" class="tab-content">
            <!-- Download Section -->
            <div class="download-section">
                <h2>Download Argentina Files</h2>
                <p style="margin-bottom: 24px; color: var(--text-secondary);">
                    Monthly production data for ~85,418 oil and gas wells in Argentina
                    ({year_range}). Spanish column names preserved from source.
                </p>
                <div class="download-grid">
                    <a href="argentina/wells.parquet" class="download-button" download>
                        <span>wells.parquet</span>
                        <span class="download-icon">⬇</span>
                    </a>
                    <a href="argentina/well_operator_history.parquet" class="download-button" download>
                        <span>well_operator_history.parquet</span>
                        <span class="download-icon">⬇</span>
                    </a>
                    <a href="argentina/well_events.parquet" class="download-button" download>
                        <span>well_events.parquet</span>
                        <span class="download-icon">⬇</span>
                    </a>
                </div>

                <h3 style="margin-top: 8px; margin-bottom: 12px;">
                    monthly_production
                    <span style="font-weight: normal; color: var(--text-secondary); font-size: 0.9em;">(hive-partitioned by year)</span>
                </h3>
                <div class="download-grid" style="margin-bottom: 12px;">
                    <a href="argentina/monthly_production/_files.json" class="download-button">
                        <span>_files.json &nbsp;·&nbsp; manifest for read_parquet / httpfs</span>
                        <span class="download-icon">{{}}</span>
                    </a>
                </div>
                <details style="margin-bottom: 32px;">
                    <summary style="cursor: pointer; padding: 8px 0; color: var(--text-secondary); font-family: 'IBM Plex Mono', monospace;">
                        Download a specific year
                    </summary>
                    <div class="download-grid" style="grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; margin-top: 12px; margin-bottom: 0;">
{year_buttons}
                    </div>
                </details>

                <div class="download-grid" style="margin-top: 16px;">
                    <a href="argentina/README.md" class="download-button">
                        <span>README.md</span>
                        <span class="download-icon">📖</span>
                    </a>
                    <a href="argentina/schema.md" class="download-button">
                        <span>schema.md</span>
                        <span class="download-icon">📖</span>
                    </a>
                    <a href="argentina/schema.json" class="download-button">
                        <span>schema.json</span>
                        <span class="download-icon">{{}}</span>
                    </a>
                    <a href="argentina/schema.sql" class="download-button">
                        <span>schema.sql</span>
                        <span class="download-icon">⌘</span>
                    </a>
                </div>
                <p class="file-size">Three single-file tables · {len(years)}-year partitioned monthly series · Spanish column names</p>
            </div>

            <!-- About Section -->
            <section>
                <h2>About This Dataset</h2>
                <p>
                    Monthly production data for the Argentine oil and gas industry,
                    sourced from the <strong>Secretaría de Energía</strong> public datasets.
                    Organized into four tables by per-well change frequency: a static well
                    master, slowly-changing operator history, operational state events, and
                    a gap-filled monthly time series of ~17.6 million rows.
                </p>
                <p>
                    Spanish column names are preserved from the source
                    (<code>idpozo</code>, <code>cuenca</code>, <code>prod_pet</code>, …).
                    The full glossary of opaque codes (<code>tef</code>, <code>vida_util</code>,
                    <code>formprod</code>) lives in <code>schema.md</code>.
                </p>
            </section>

            <!-- Query Example Section -->
            <section>
                <h2>Quick Start with DuckDB</h2>
                <p>
                    Aggregate 2023 production by basin, joining the static well master
                    to the hive-partitioned monthly series:
                </p>
                <div class="code-block">
                    <div class="code-header">
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                        <span class="code-dot"></span>
                    </div>
                    <pre><span class="keyword">import</span> duckdb

<span class="comment"># Aggregate 2023 production by basin</span>
result = duckdb.<span class="function">sql</span>(<span class="string">\"\"\"
    SELECT w.cuenca,
           SUM(m.prod_pet) AS oil_m3,
           SUM(m.prod_gas) AS gas_mm3
    FROM 'argentina/wells.parquet' w
    JOIN read_parquet(
      'argentina/monthly_production/anio=*/data.parquet',
      hive_partitioning = true
    ) m USING (idpozo)
    WHERE m.anio = 2023
    GROUP BY w.cuenca
    ORDER BY oil_m3 DESC
\"\"\"</span>).<span class="function">df</span>()</pre>
                </div>
                <p>
                    Three more canonical patterns (single-well lookup, year-range
                    aggregation, manifest-driven access via <code>_files.json</code>) live
                    in the dataset README.
                </p>
            </section>

            <!-- Schema Documents Section -->
            <section>
                <h2>Schema Documents</h2>
                <p>
                    Full per-column documentation is published alongside the parquets:
                </p>
                <div class="schema-grid">
                    <div class="table-card">
                        <h3 class="table-name">README.md</h3>
                        <p class="table-meta">Dataset overview + four canonical query examples</p>
                        <div class="foreign-key-note">
                            → <a href="argentina/README.md">Open README.md</a>
                        </div>
                    </div>
                    <div class="table-card">
                        <h3 class="table-name">schema.md</h3>
                        <p class="table-meta">English column docs (Spanish identifiers preserved), four-bucket rationale, glossary</p>
                        <div class="foreign-key-note">
                            → <a href="argentina/schema.md">Open schema.md</a>
                        </div>
                    </div>
                    <div class="table-card">
                        <h3 class="table-name">schema.json</h3>
                        <p class="table-meta">Machine-readable column list, types, primary &amp; foreign keys</p>
                        <div class="foreign-key-note">
                            → <a href="argentina/schema.json">Open schema.json</a>
                        </div>
                    </div>
                    <div class="table-card">
                        <h3 class="table-name">schema.sql</h3>
                        <p class="table-meta">DDL that mirrors the published structure in a fresh DuckDB</p>
                        <div class="foreign-key-note">
                            → <a href="argentina/schema.sql">Open schema.sql</a>
                        </div>
                    </div>
                </div>
            </section>

            <!-- Source & License -->
            <section class="dataset-attribution">
                <h2>Source &amp; License</h2>
                <p>
                    Data from <a href="https://datos.energia.gob.ar/dataset/produccion-de-petroleo-y-gas-por-pozo" target="_blank" rel="noopener">Producción de petróleo y gas por pozo (Capítulo IV)</a>,
                    published by the <strong>Secretaría de Energía</strong> on the Argentine open data portal (<a href="https://datos.energia.gob.ar/" target="_blank" rel="noopener">datos.energia.gob.ar</a>).
                </p>
                <p>
                    All three source CSVs (<code>produccin-de-pozos-de-gas-y-petrleo-*</code>, <code>capitulo-iv-pozos</code>, <code>listado-de-pozos-cargados-por-empresas-operadoras</code>) are resources of this same dataset package.
                </p>
                <p>
                    Licensed under <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">Creative Commons Attribution 4.0</a> (as declared on the dataset's portal page).
                </p>
            </section>
        </div>

"""


def _patch_index_html(path: Path, years: list[int]) -> None:
    original = path.read_text()

    button_block = (
        f"{INDEX_TAB_BUTTON_BEGIN}\n{_index_tab_button_payload()}"
        f"{INDEX_TAB_BUTTON_END}\n"
    )
    text = _replace_block_or_insert_before(
        original,
        INDEX_TAB_BUTTON_BEGIN,
        INDEX_TAB_BUTTON_END,
        INDEX_TAB_BUTTON_ANCHOR,
        button_block,
    )

    content_block = (
        f"{INDEX_TAB_CONTENT_BEGIN}\n{_index_tab_content_payload(years)}"
        f"{INDEX_TAB_CONTENT_END}\n\n"
    )
    text = _replace_block_or_insert_before(
        text,
        INDEX_TAB_CONTENT_BEGIN,
        INDEX_TAB_CONTENT_END,
        INDEX_TAB_CONTENT_ANCHOR,
        content_block,
    )

    if text != original:
        path.write_text(text)


# ---------------------------------------------------------------------------
# Idempotent insert/replace helper
# ---------------------------------------------------------------------------


def _replace_block_or_insert_before(
    text: str, begin: str, end: str, anchor: str, block: str
) -> str:
    """Replace the region between ``begin`` and ``end`` with ``block`` if the
    sentinels exist; otherwise insert ``block`` immediately before ``anchor``.

    ``block`` must already include the ``begin`` and ``end`` markers and
    must end with the desired trailing whitespace before ``anchor``. On the
    replace branch we strip leading newlines from the suffix because they
    were inserted by the previous run as part of the block; the new block
    re-supplies them. This makes re-runs byte-identical to the first
    insertion.
    """
    if begin in text and end in text:
        prefix, _, rest = text.partition(begin)
        _, _, suffix = rest.partition(end)
        suffix = suffix.lstrip("\n")
        return prefix + block + suffix
    pos = text.index(anchor)
    return text[:pos] + block + text[pos:]
