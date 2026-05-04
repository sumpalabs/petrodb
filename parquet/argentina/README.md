# Argentina Production Dataset

Producción mensual de pozos de gas y petróleo de Argentina (2006–presente), publicada en cuatro tablas Parquet con nombres de columnas en español.

## Archivos publicados

```
argentina/
├── wells.parquet                   # 1 fila por idpozo (~85.418)
├── well_operator_history.parquet   # 1 fila por corrida de operador
├── well_events.parquet             # 1 fila por mes-transición de estado
├── monthly_production/
│   ├── anio=2006/data.parquet
│   ├── anio=2007/data.parquet
│   ├── ...
│   └── _files.json                 # manifiesto de particiones
├── schema.md
├── schema.json
└── schema.sql
```

Los nombres de columnas se preservan en español tal como los publica la fuente (`idpozo`, `cuenca`, `sigla`, `formprod`, `prod_pet`, …). El glosario de códigos opacos como `tef` o `vida_util` vive en `schema.md`.

## Columnas eliminadas

Estas columnas de la fuente son administrativas/de auditoría y **no se publican**:

- `geojson`
- `observaciones`
- `idusuario`
- `rectificado`
- `habilitado`
- `fechaingreso`
- `fecha_data`

## Acceso vía DuckDB `httpfs`

Todos los ejemplos asumen DuckDB ≥ 1.0 con la extensión `httpfs` habilitada. Las consultas leen directamente desde el sitio sin descarga.

```sql
INSTALL httpfs; LOAD httpfs;
```

### 1. Pozo único por `idpozo`

Cada partición está ordenada por `(idpozo, fecha)`, por lo que las estadísticas de row-group de Parquet permiten que DuckDB pode los row-groups que no contienen el pozo solicitado: la consulta descarga rangos de bytes mínimos.

```sql
SELECT idpozo, fecha, prod_pet, prod_gas
FROM 'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet'
WHERE idpozo = 12345
ORDER BY fecha;
```

### 2. Rango de años

El particionado Hive por `anio` permite que DuckDB pode las particiones fuera del rango solicitado. Habilita `hive_partitioning` para que la columna `anio` aparezca derivada del path.

```sql
SELECT anio, COUNT(*) AS rows, SUM(prod_pet) AS prod_pet_total
FROM read_parquet(
  'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet',
  hive_partitioning = true
)
WHERE anio BETWEEN 2018 AND 2022
GROUP BY anio
ORDER BY anio;
```

### 3. Agregado por cuenca (join `wells` ↔ `monthly_production`)

La tabla maestra `wells` se carga una vez (es chica); `monthly_production` se reduce por `anio` antes del join.

```sql
SELECT w.cuenca,
       SUM(m.prod_pet) AS prod_pet_total,
       SUM(m.prod_gas) AS prod_gas_total
FROM 'https://dev-petrodb.ocortez.com/argentina/wells.parquet' w
JOIN read_parquet(
  'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=*/data.parquet',
  hive_partitioning = true
) m USING (idpozo)
WHERE m.anio = 2023
GROUP BY w.cuenca
ORDER BY prod_pet_total DESC;
```

### 4. Acceso por manifiesto + `generate_series`

El manifiesto `_files.json` lista las URLs relativas de cada partición. Si se prefiere evitar el patrón con asterisco (que requiere un LIST), se pueden generar las URLs con `generate_series` y leerlas vía un VALUES list — útil cuando el front-edge cachea por URL exacta.

```sql
WITH urls AS (
  SELECT
    'https://dev-petrodb.ocortez.com/argentina/monthly_production/anio=' || y || '/data.parquet' AS url
  FROM generate_series(2006, 2025) AS t(y)
)
SELECT m.idpozo, m.fecha, m.prod_pet
FROM read_parquet((SELECT LIST(url) FROM urls), hive_partitioning = true) m
WHERE m.idpozo = 12345
ORDER BY m.fecha;
```

Alternativamente, leer el manifiesto y construir la lista desde la aplicación cliente:

```python
import json, urllib.request, duckdb
manifest = json.load(urllib.request.urlopen('https://dev-petrodb.ocortez.com/argentina/monthly_production/_files.json'))
urls = [f'https://dev-petrodb.ocortez.com/argentina/monthly_production/' + p for p in manifest]
duckdb.sql("SELECT * FROM read_parquet(?, hive_partitioning = true) "
           "WHERE idpozo = 12345", params=[urls]).show()
```

## Esquema completo

Ver `schema.md` (legible) / `schema.json` (consumo programático) / `schema.sql` (DDL para reproducir la estructura localmente).
