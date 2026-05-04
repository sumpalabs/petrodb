"""Generate the Volve/FORCE-style documentation deliverables for Argentina.

Produces four artifacts under the dataset root:

- `schema.json` — machine-readable column list, types, nullability, PKs, FKs.
- `schema.sql` — DDL that mirrors the published structure in a fresh DuckDB.
- `schema.md`  — human-readable column docs (Spanish), table relationships,
  the four-bucket rationale, plus a glossary covering opaque codes such as
  `tef` and `vida_util`.
- `README.md`  — dataset overview + four canonical DuckDB query examples
  (single-well, year-range, basin-aggregate, manifest-driven via
  `generate_series`).

The column list and types are reflected from the published Parquets via
`DESCRIBE SELECT * FROM read_parquet(...)` so the published schema cannot
drift from the data. Primary keys, foreign keys, and Spanish-language
column descriptions are not derivable from Parquet metadata, so they live
as module-level constants here — the single source of truth for the
documented contract.
"""

import json
from pathlib import Path

import duckdb

TABLE_ORDER = (
    "wells",
    "well_operator_history",
    "well_events",
    "monthly_production",
)

TABLE_DESCRIPTIONS = {
    "wells": (
        "Tabla maestra estática de pozos. Una fila por `idpozo` "
        "(~85.418 pozos, incluidos ~113 huérfanos en `capitulo-iv` "
        "marcados con `has_production = false`)."
    ),
    "well_operator_history": (
        "Histórico de operadores por pozo (slowly-changing dimension). "
        "Una fila por corrida contigua de `idempresa` por `idpozo`. "
        "Las corridas con `idempresa` NULL se preservan tal cual: la "
        "ausencia de operador es información de la fuente."
    ),
    "well_events": (
        "Eventos de estado operacional. Una fila por mes en el que "
        "cualquiera de `(tipoestado, tipoextraccion, tipopozo)` cambió. "
        "Se incluye la fila inicial de cada pozo como transición a su "
        "estado de partida; los flips de un solo mes no se suavizan."
    ),
    "monthly_production": (
        "Serie mensual de medidas numéricas. Una fila por `(idpozo, fecha)` "
        "para cada mes en `[primera_fila, última_fila]` por pozo (los "
        "huecos se rellenan con medidas NULL). Particionada por `anio` "
        "vía Hive (`monthly_production/anio=YYYY/data.parquet`) y ordenada "
        "internamente por `(idpozo, fecha)` para que las estadísticas de "
        "row-group permitan podar consultas single-well sobre `httpfs`."
    ),
}

PRIMARY_KEYS = {
    "wells": ("idpozo",),
    "well_operator_history": ("idpozo", "valid_from"),
    "well_events": ("idpozo", "event_date"),
    "monthly_production": ("idpozo", "fecha"),
}

FOREIGN_KEYS = {
    "well_operator_history": (
        {
            "column": "idpozo",
            "references_table": "wells",
            "references_column": "idpozo",
        },
    ),
    "well_events": (
        {
            "column": "idpozo",
            "references_table": "wells",
            "references_column": "idpozo",
        },
    ),
    "monthly_production": (
        {
            "column": "idpozo",
            "references_table": "wells",
            "references_column": "idpozo",
        },
    ),
}

# Spanish, plain-language descriptions for every published column. The
# glossary in `schema.md` is generated from this table, so opaque codes
# like `tef` and `vida_util` get a one-shot definition.
COLUMN_DESCRIPTIONS = {
    # wells — identidad y etiquetas
    "idpozo": "Identificador entero del pozo (wellbore × formación productiva). Clave primaria del modelo.",
    "sigla": "Código humano del pozo (p. ej. `YPF.BLO.x-8`). Tratado como etiqueta, posiblemente mutable; no es PK.",
    "formprod": "Formación productiva del pozo. Atributo estático del `idpozo` (codificado en el ID).",
    "codigopropio": "Código interno asignado por la operadora en el padrón `listado`.",
    "nombrepropio": "Nombre interno asignado por la operadora en el padrón `listado`.",
    # wells — ubicación
    "area": "Área de permiso o concesión donde se ubica el pozo.",
    "cod_area": "Código del área de permiso/concesión.",
    "yacimiento": "Área de yacimiento donde se ubica el pozo.",
    "cod_yacimiento": "Código del área de yacimiento.",
    "cuenca": "Cuenca sedimentaria.",
    "provincia": "Provincia argentina donde se ubica el pozo.",
    "idcuenca": "Código de la cuenca.",
    "idprovincia": "Código de la provincia.",
    # wells — geofísica
    "formacion": "Formación geológica reportada.",
    "cota": "Cota del terreno (m s.n.m.).",
    "profundidad": "Profundidad final del pozo (m).",
    # wells — clasificación
    "clasificacion": "Clasificación regulatoria del pozo (p. ej. `Petrolífero`, `Gasífero`).",
    "subclasificacion": "Subclasificación regulatoria.",
    "tipo_recurso": "Tipo de recurso (p. ej. `Convencional`, `No Convencional`).",
    "sub_tipo_recurso": "Subtipo de recurso (p. ej. `Shale`, `Tight`).",
    "gasplus": "Indicador del programa Gas Plus (capítulo IV).",
    "proyecto": "Proyecto al que pertenece el pozo (campo de la fuente de producción).",
    # wells — operador inicial
    "empresa": (
        "Operador asociado a la corrida (en `wells`: operador inicial del registro "
        "capítulo IV; en `well_operator_history`: nombre desplegado del intervalo)."
    ),
    # wells — espacial
    "coordenadax": "Coordenada X del pozo (sistema reportado en el padrón `listado`).",
    "coordenaday": "Coordenada Y del pozo (sistema reportado en el padrón `listado`).",
    "geom": "Geometría del pozo en formato WKB (BLOB). Decodificable con `ST_GeomFromWKB(geom)` (extensión `spatial`).",
    # wells — fechas
    "adjiv_fecha_inicio_perf": "Fecha de inicio de perforación (capítulo IV).",
    "adjiv_fecha_fin_perf": "Fecha de fin de perforación (capítulo IV).",
    "adjiv_fecha_inicio_term": "Fecha de inicio de terminación (capítulo IV).",
    "adjiv_fecha_fin_term": "Fecha de fin de terminación (capítulo IV).",
    "adjiv_fecha_inicio": "Fecha de inicio reportada en el padrón `listado`.",
    "adjiv_fecha_fin": "Fecha de fin reportada en el padrón `listado`.",
    "adjiv_fecha_abandono": "Fecha de abandono del pozo, si aplica.",
    "adjiv_equipo_utilizar": "Equipo de perforación utilizado.",
    "adjiv_capacidad_perf": "Capacidad de perforación del equipo.",
    # wells — caudales iniciales (test inicial estático)
    "pet_inicial": "Caudal inicial de petróleo en el ensayo de descubrimiento (m³/d).",
    "gas_inicial": "Caudal inicial de gas en el ensayo de descubrimiento (Mm³/d).",
    "agua_inicial": "Caudal inicial de agua en el ensayo de descubrimiento (m³/d).",
    "iny_agua_inicial": "Inyección inicial de agua reportada en el ensayo (m³/d).",
    "iny_gas_inicial": "Inyección inicial de gas reportada en el ensayo (Mm³/d).",
    "iny_otros_inicial": "Inyección inicial de otros fluidos reportada en el ensayo.",
    "iny_co2_inicial": "Inyección inicial de CO₂ reportada en el ensayo.",
    "vida_util_inicial": "Vida útil estimada al momento del ensayo inicial (meses).",
    "has_production": (
        "`true` si el `idpozo` aparece alguna vez en producción mensual; "
        "`false` para los pozos huérfanos del capítulo IV que nunca produjeron."
    ),
    # well_operator_history
    "idempresa": "Código alfanumérico de la operadora (`Z001`, `APEA`, …). Almacenado como VARCHAR.",
    "valid_from": "Primer mes de la corrida contigua de operador (DATE, primero de mes, inclusive).",
    "valid_to": "Último mes de la corrida contigua de operador (DATE, primero de mes, inclusive).",
    # well_events
    "event_date": "Mes del snapshot de estado operacional (DATE, primero de mes).",
    "tipoestado": "Estado operacional del pozo (p. ej. `Extracción Efectiva`, `Parado Transitoriamente`).",
    "tipoextraccion": "Método de extracción (p. ej. `Bombeo Mecánico`, `Surgente`).",
    "tipopozo": "Tipo de pozo en función del fluido (p. ej. `Petrolífero`, `Gasífero`, `Inyector`).",
    # monthly_production
    "fecha": "Mes de la medida (DATE, primer día del mes, derivado de `anio`/`mes` de la fuente).",
    "prod_pet": "Producción mensual de petróleo (m³).",
    "prod_gas": "Producción mensual de gas (Mm³).",
    "prod_agua": "Producción mensual de agua (m³).",
    "iny_agua": "Inyección mensual de agua (m³).",
    "iny_gas": "Inyección mensual de gas (Mm³).",
    "iny_co2": "Inyección mensual de CO₂.",
    "iny_otro": "Inyección mensual de otros fluidos.",
    "tef": "Tiempo Efectivo de Producción del mes (horas).",
    "vida_util": "Vida útil declarada del pozo en el mes (meses).",
}

DROPPED_COLUMNS = (
    "geojson",
    "observaciones",
    "idusuario",
    "rectificado",
    "habilitado",
    "fechaingreso",
    "fecha_data",
)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate(con: duckdb.DuckDBPyConnection, output_dir: Path) -> None:
    """Reflect the published Parquets and write the four documentation artifacts.

    `output_dir` is the dataset root (i.e. where `wells.parquet` lives).
    All writes are full overwrites so the call is idempotent.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    schemas = _reflect_schemas(con, output_dir)
    _write_schema_json(schemas, output_dir / "schema.json")
    _write_schema_sql(schemas, output_dir / "schema.sql")
    _write_schema_md(schemas, output_dir / "schema.md")
    _write_readme(schemas, output_dir / "README.md")


# ---------------------------------------------------------------------------
# Reflection from published parquets
# ---------------------------------------------------------------------------


def _parquet_path(table: str, output_dir: Path) -> str:
    """Resolve the read path for `read_parquet` per published table.

    `monthly_production` is hive-partitioned, so we reflect from one
    partition file with `hive_partitioning = false` to see only the
    columns physically stored in the file (the partition column reappears
    via directory inference and is not part of the file schema).
    """
    if table == "monthly_production":
        partition = next(
            iter(
                sorted((output_dir / "monthly_production").glob("anio=*/data.parquet"))
            )
        )
        return f"read_parquet('{partition}', hive_partitioning = false)"
    return f"read_parquet('{output_dir / f'{table}.parquet'}')"


def _reflect_schemas(
    con: duckdb.DuckDBPyConnection, output_dir: Path
) -> dict[str, dict]:
    """For every published table, reflect column list + types from the parquet.

    Returns a dict keyed by table name with values of the form:
        {"columns": [{"name", "type", "not_null", "primary_key"}, ...],
         "primary_key": ("col1", ...),
         "foreign_keys": (...,),
         "description": "..."}
    PKs cannot be NULL, so the PK declaration overrides whatever DESCRIBE
    reports for those columns.
    """
    schemas: dict[str, dict] = {}
    for table in TABLE_ORDER:
        described = con.execute(
            f"DESCRIBE SELECT * FROM {_parquet_path(table, output_dir)}"
        ).fetchall()
        pk = PRIMARY_KEYS[table]
        columns = [
            {
                "name": row[0],
                "type": row[1],
                "not_null": row[0] in pk or row[2] == "NO",
                "primary_key": row[0] in pk,
            }
            for row in described
        ]
        schemas[table] = {
            "columns": columns,
            "primary_key": pk,
            "foreign_keys": FOREIGN_KEYS.get(table, ()),
            "description": TABLE_DESCRIPTIONS[table],
        }
    return schemas


# ---------------------------------------------------------------------------
# schema.json
# ---------------------------------------------------------------------------


def _write_schema_json(schemas: dict[str, dict], path: Path) -> None:
    payload = {
        "dataset": "argentina",
        "description": (
            "Producción de pozos de gas y petróleo de Argentina (2006–presente)."
        ),
        "tables": {
            table: {
                "description": meta["description"],
                "columns": meta["columns"],
                "primary_key": list(meta["primary_key"]),
                "foreign_keys": [dict(fk) for fk in meta["foreign_keys"]],
            }
            for table, meta in schemas.items()
        },
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# schema.sql
# ---------------------------------------------------------------------------


def _write_schema_sql(schemas: dict[str, dict], path: Path) -> None:
    """Emit DDL that recreates the published structure in a fresh DuckDB.

    PRIMARY KEY constraints are inlined; FOREIGN KEY constraints reference
    the parent `wells` table. Types are reproduced verbatim from the
    DESCRIBE output, so the DDL is round-trippable against the published
    parquets.
    """
    lines = [
        "-- Argentina production dataset — DDL",
        "-- Auto-generated from the published Parquet schemas. Do not edit by hand.",
        "",
    ]
    for table in TABLE_ORDER:
        meta = schemas[table]
        col_defs = []
        for col in meta["columns"]:
            null_clause = " NOT NULL" if col["not_null"] else ""
            col_defs.append(f"  {col['name']} {col['type']}{null_clause}")
        pk_cols = ", ".join(meta["primary_key"])
        col_defs.append(f"  PRIMARY KEY ({pk_cols})")
        for fk in meta["foreign_keys"]:
            col_defs.append(
                f"  FOREIGN KEY ({fk['column']}) REFERENCES "
                f"{fk['references_table']} ({fk['references_column']})"
            )
        lines.append(f"CREATE TABLE {table} (")
        lines.append(",\n".join(col_defs))
        lines.append(");")
        lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# schema.md
# ---------------------------------------------------------------------------


def _write_schema_md(schemas: dict[str, dict], path: Path) -> None:
    """Human-readable Spanish docs covering every column + the four-bucket
    rationale + a glossary of opaque codes.
    """
    lines: list[str] = []
    lines.append("# Argentina — Esquema del dataset")
    lines.append("")
    lines.append(
        "Producción de pozos de gas y petróleo de Argentina, organizada en "
        "cuatro tablas según volatilidad por `idpozo`. Los nombres de columnas "
        "se preservan en español tal como los publica la fuente."
    )
    lines.append("")
    lines.append("## Cuatro buckets, cuatro tablas")
    lines.append("")
    lines.append(
        "El esquema separa por **frecuencia de cambio** dentro de cada `idpozo`: "
        "atributos estáticos, metadatos lentamente variables, eventos y series "
        "temporales numéricas. Esto evita redundancia en las ~17,6 M filas mensuales."
    )
    lines.append("")
    lines.append("| Tabla | Bucket | Granularidad |")
    lines.append("|-------|--------|--------------|")
    lines.append(
        "| `wells` | Maestro estático (< 0,3 % de pozos cambian) | 1 fila por `idpozo` |"
    )
    lines.append(
        "| `well_operator_history` | Metadatos slowly-changing (~67 % cambian) | 1 fila por corrida de operador |"
    )
    lines.append(
        "| `well_events` | Eventos de estado (~74 % cambian `tipoestado`) | 1 fila por mes-transición |"
    )
    lines.append(
        "| `monthly_production` | Serie mensual numérica | 1 fila por `(idpozo, fecha)` |"
    )
    lines.append("")
    lines.append("## Tablas")
    lines.append("")
    for table in TABLE_ORDER:
        meta = schemas[table]
        lines.append(f"### `{table}`")
        lines.append("")
        lines.append(meta["description"])
        lines.append("")
        lines.append("**Columnas:**")
        lines.append("")
        lines.append("| Columna | Tipo | Nullable | PK | Descripción |")
        lines.append("|---------|------|----------|----|-------------|")
        for col in meta["columns"]:
            nullable = "No" if col["not_null"] else "Sí"
            pk = "✓" if col["primary_key"] else ""
            desc = COLUMN_DESCRIPTIONS.get(col["name"], "")
            lines.append(
                f"| `{col['name']}` | {col['type']} | {nullable} | {pk} | {desc} |"
            )
        lines.append("")
        if meta["foreign_keys"]:
            lines.append("**Claves foráneas:**")
            lines.append("")
            for fk in meta["foreign_keys"]:
                lines.append(
                    f"- `{fk['column']}` → "
                    f"`{fk['references_table']}.{fk['references_column']}`"
                )
            lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("## Relaciones")
    lines.append("")
    lines.append("```")
    for table in TABLE_ORDER:
        for fk in schemas[table]["foreign_keys"]:
            lines.append(
                f"{table}.{fk['column']} → "
                f"{fk['references_table']}.{fk['references_column']}"
            )
    lines.append("```")
    lines.append("")
    lines.append("## Glosario de códigos")
    lines.append("")
    lines.append(
        "Algunas siglas heredadas de la fuente no son evidentes a primera vista:"
    )
    lines.append("")
    lines.append("| Código | Significado |")
    lines.append("|--------|-------------|")
    lines.append("| `tef` | Tiempo Efectivo de Producción del mes (horas). |")
    lines.append("| `vida_util` | Vida útil declarada del pozo en el mes (meses). |")
    lines.append(
        "| `formprod` | Formación productiva del `idpozo`. Atributo estático. |"
    )
    lines.append(
        "| `idpozo` | Identidad canónica: wellbore × formación productiva. PK del modelo. |"
    )
    lines.append(
        "| `sigla` | Código humano del pozo. Etiqueta, posiblemente mutable, no PK. |"
    )
    lines.append(
        "| `idempresa` | Código alfanumérico de la operadora. **VARCHAR**, no INTEGER. |"
    )
    lines.append("")
    lines.append("## Columnas eliminadas")
    lines.append("")
    lines.append(
        "Las siguientes columnas de la fuente son administrativas/de auditoría y "
        "no se publican:"
    )
    lines.append("")
    for col in DROPPED_COLUMNS:
        lines.append(f"- `{col}`")
    lines.append("")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# README.md
# ---------------------------------------------------------------------------


def _write_readme(schemas: dict[str, dict], path: Path) -> None:
    """Dataset overview + the four canonical DuckDB query examples.

    Examples cover: single-well lookup (row-group pruning), year-range
    across hive partitions, basin aggregate joining `wells` to
    `monthly_production`, and manifest/`generate_series` URL-template
    access against `_files.json`.
    """
    base_url = "https://dev-petrodb.ocortez.com/argentina"
    years = [
        col["name"] for col in schemas["monthly_production"]["columns"]
    ]  # not used; placeholder for future schema-driven examples
    del years
    lines: list[str] = []
    lines.append("# Argentina Production Dataset")
    lines.append("")
    lines.append(
        "Producción mensual de pozos de gas y petróleo de Argentina (2006–presente), "
        "publicada en cuatro tablas Parquet con nombres de columnas en español."
    )
    lines.append("")
    lines.append("## Archivos publicados")
    lines.append("")
    lines.append("```")
    lines.append("argentina/")
    lines.append("├── wells.parquet                   # 1 fila por idpozo (~85.418)")
    lines.append("├── well_operator_history.parquet   # 1 fila por corrida de operador")
    lines.append(
        "├── well_events.parquet             # 1 fila por mes-transición de estado"
    )
    lines.append("├── monthly_production/")
    lines.append("│   ├── anio=2006/data.parquet")
    lines.append("│   ├── anio=2007/data.parquet")
    lines.append("│   ├── ...")
    lines.append("│   └── _files.json                 # manifiesto de particiones")
    lines.append("├── schema.md")
    lines.append("├── schema.json")
    lines.append("└── schema.sql")
    lines.append("```")
    lines.append("")
    lines.append(
        "Los nombres de columnas se preservan en español tal como los publica la "
        "fuente (`idpozo`, `cuenca`, `sigla`, `formprod`, `prod_pet`, …). El glosario "
        "de códigos opacos como `tef` o `vida_util` vive en `schema.md`."
    )
    lines.append("")
    lines.append("## Columnas eliminadas")
    lines.append("")
    lines.append(
        "Estas columnas de la fuente son administrativas/de auditoría y **no se "
        "publican**:"
    )
    lines.append("")
    for col in DROPPED_COLUMNS:
        lines.append(f"- `{col}`")
    lines.append("")
    lines.append("## Acceso vía DuckDB `httpfs`")
    lines.append("")
    lines.append(
        "Todos los ejemplos asumen DuckDB ≥ 1.0 con la extensión `httpfs` "
        "habilitada. Las consultas leen directamente desde el sitio sin descarga."
    )
    lines.append("")
    lines.append("```sql")
    lines.append("INSTALL httpfs; LOAD httpfs;")
    lines.append("```")
    lines.append("")
    lines.append("### 1. Pozo único por `idpozo`")
    lines.append("")
    lines.append(
        "Cada partición está ordenada por `(idpozo, fecha)`, por lo que las "
        "estadísticas de row-group de Parquet permiten que DuckDB pode los "
        "row-groups que no contienen el pozo solicitado: la consulta descarga "
        "rangos de bytes mínimos."
    )
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT idpozo, fecha, prod_pet, prod_gas")
    lines.append(f"FROM '{base_url}/monthly_production/anio=*/data.parquet'")
    lines.append("WHERE idpozo = 12345")
    lines.append("ORDER BY fecha;")
    lines.append("```")
    lines.append("")
    lines.append("### 2. Rango de años")
    lines.append("")
    lines.append(
        "El particionado Hive por `anio` permite que DuckDB pode las particiones "
        "fuera del rango solicitado. Habilita `hive_partitioning` para que la "
        "columna `anio` aparezca derivada del path."
    )
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT anio, COUNT(*) AS rows, SUM(prod_pet) AS prod_pet_total")
    lines.append("FROM read_parquet(")
    lines.append(f"  '{base_url}/monthly_production/anio=*/data.parquet',")
    lines.append("  hive_partitioning = true")
    lines.append(")")
    lines.append("WHERE anio BETWEEN 2018 AND 2022")
    lines.append("GROUP BY anio")
    lines.append("ORDER BY anio;")
    lines.append("```")
    lines.append("")
    lines.append("### 3. Agregado por cuenca (join `wells` ↔ `monthly_production`)")
    lines.append("")
    lines.append(
        "La tabla maestra `wells` se carga una vez (es chica); `monthly_production` "
        "se reduce por `anio` antes del join."
    )
    lines.append("")
    lines.append("```sql")
    lines.append("SELECT w.cuenca,")
    lines.append("       SUM(m.prod_pet) AS prod_pet_total,")
    lines.append("       SUM(m.prod_gas) AS prod_gas_total")
    lines.append(f"FROM '{base_url}/wells.parquet' w")
    lines.append("JOIN read_parquet(")
    lines.append(f"  '{base_url}/monthly_production/anio=*/data.parquet',")
    lines.append("  hive_partitioning = true")
    lines.append(") m USING (idpozo)")
    lines.append("WHERE m.anio = 2023")
    lines.append("GROUP BY w.cuenca")
    lines.append("ORDER BY prod_pet_total DESC;")
    lines.append("```")
    lines.append("")
    lines.append("### 4. Acceso por manifiesto + `generate_series`")
    lines.append("")
    lines.append(
        "El manifiesto `_files.json` lista las URLs relativas de cada partición. "
        "Si se prefiere evitar el patrón con asterisco (que requiere un LIST), se "
        "pueden generar las URLs con `generate_series` y leerlas vía un VALUES "
        "list — útil cuando el front-edge cachea por URL exacta."
    )
    lines.append("")
    lines.append("```sql")
    lines.append("WITH urls AS (")
    lines.append("  SELECT")
    lines.append(
        f"    '{base_url}/monthly_production/anio=' || y || '/data.parquet' AS url"
    )
    lines.append("  FROM generate_series(2006, 2025) AS t(y)")
    lines.append(")")
    lines.append("SELECT m.idpozo, m.fecha, m.prod_pet")
    lines.append(
        "FROM read_parquet((SELECT LIST(url) FROM urls), hive_partitioning = true) m"
    )
    lines.append("WHERE m.idpozo = 12345")
    lines.append("ORDER BY m.fecha;")
    lines.append("```")
    lines.append("")
    lines.append(
        "Alternativamente, leer el manifiesto y construir la lista desde la "
        "aplicación cliente:"
    )
    lines.append("")
    lines.append("```python")
    lines.append("import json, urllib.request, duckdb")
    lines.append(
        f"manifest = json.load(urllib.request.urlopen("
        f"'{base_url}/monthly_production/_files.json'))"
    )
    lines.append(f"urls = [f'{base_url}/monthly_production/' + p for p in manifest]")
    lines.append(
        'duckdb.sql("SELECT * FROM read_parquet(?, hive_partitioning = true) "'
    )
    lines.append('           "WHERE idpozo = 12345", params=[urls]).show()')
    lines.append("```")
    lines.append("")
    lines.append("## Esquema completo")
    lines.append("")
    lines.append(
        "Ver `schema.md` (legible) / `schema.json` (consumo programático) / "
        "`schema.sql` (DDL para reproducir la estructura localmente)."
    )
    lines.append("")
    path.write_text("\n".join(lines))
