# Argentina — Esquema del dataset

Producción de pozos de gas y petróleo de Argentina, organizada en cuatro tablas según volatilidad por `idpozo`. Los nombres de columnas se preservan en español tal como los publica la fuente.

## Cuatro buckets, cuatro tablas

El esquema separa por **frecuencia de cambio** dentro de cada `idpozo`: atributos estáticos, metadatos lentamente variables, eventos y series temporales numéricas. Esto evita redundancia en las ~17,6 M filas mensuales.

| Tabla | Bucket | Granularidad |
|-------|--------|--------------|
| `wells` | Maestro estático (< 0,3 % de pozos cambian) | 1 fila por `idpozo` |
| `well_operator_history` | Metadatos slowly-changing (~67 % cambian) | 1 fila por corrida de operador |
| `well_events` | Eventos de estado (~74 % cambian `tipoestado`) | 1 fila por mes-transición |
| `monthly_production` | Serie mensual numérica | 1 fila por `(idpozo, fecha)` |

## Tablas

### `wells`

Tabla maestra estática de pozos. Una fila por `idpozo` (~85.418 pozos, incluidos ~113 huérfanos en `capitulo-iv` marcados con `has_production = false`).

**Columnas:**

| Columna | Tipo | Nullable | PK | Descripción |
|---------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Identificador entero del pozo (wellbore × formación productiva). Clave primaria del modelo. |
| `sigla` | VARCHAR | Sí |  | Código humano del pozo (p. ej. `YPF.BLO.x-8`). Tratado como etiqueta, posiblemente mutable; no es PK. |
| `formprod` | VARCHAR | Sí |  | Formación productiva del pozo. Atributo estático del `idpozo` (codificado en el ID). |
| `codigopropio` | VARCHAR | Sí |  | Código interno asignado por la operadora en el padrón `listado`. |
| `nombrepropio` | VARCHAR | Sí |  | Nombre interno asignado por la operadora en el padrón `listado`. |
| `area` | VARCHAR | Sí |  | Área de permiso o concesión donde se ubica el pozo. |
| `cod_area` | VARCHAR | Sí |  | Código del área de permiso/concesión. |
| `yacimiento` | VARCHAR | Sí |  | Área de yacimiento donde se ubica el pozo. |
| `cod_yacimiento` | VARCHAR | Sí |  | Código del área de yacimiento. |
| `cuenca` | VARCHAR | Sí |  | Cuenca sedimentaria. |
| `provincia` | VARCHAR | Sí |  | Provincia argentina donde se ubica el pozo. |
| `idcuenca` | VARCHAR | Sí |  | Código de la cuenca. |
| `idprovincia` | VARCHAR | Sí |  | Código de la provincia. |
| `formacion` | VARCHAR | Sí |  | Formación geológica reportada. |
| `cota` | DOUBLE | Sí |  | Cota del terreno (m s.n.m.). |
| `profundidad` | DOUBLE | Sí |  | Profundidad final del pozo (m). |
| `clasificacion` | VARCHAR | Sí |  | Clasificación regulatoria del pozo (p. ej. `Petrolífero`, `Gasífero`). |
| `subclasificacion` | VARCHAR | Sí |  | Subclasificación regulatoria. |
| `tipo_recurso` | VARCHAR | Sí |  | Tipo de recurso (p. ej. `Convencional`, `No Convencional`). |
| `sub_tipo_recurso` | VARCHAR | Sí |  | Subtipo de recurso (p. ej. `Shale`, `Tight`). |
| `gasplus` | VARCHAR | Sí |  | Indicador del programa Gas Plus (capítulo IV). |
| `proyecto` | VARCHAR | Sí |  | Proyecto al que pertenece el pozo (campo de la fuente de producción). |
| `empresa` | VARCHAR | Sí |  | Operador asociado a la corrida (en `wells`: operador inicial del registro capítulo IV; en `well_operator_history`: nombre desplegado del intervalo). |
| `coordenadax` | DOUBLE | Sí |  | Coordenada X del pozo (sistema reportado en el padrón `listado`). |
| `coordenaday` | DOUBLE | Sí |  | Coordenada Y del pozo (sistema reportado en el padrón `listado`). |
| `geom` | BLOB | Sí |  | Geometría del pozo en formato WKB (BLOB). Decodificable con `ST_GeomFromWKB(geom)` (extensión `spatial`). |
| `adjiv_fecha_inicio_perf` | DATE | Sí |  | Fecha de inicio de perforación (capítulo IV). |
| `adjiv_fecha_fin_perf` | DATE | Sí |  | Fecha de fin de perforación (capítulo IV). |
| `adjiv_fecha_inicio_term` | DATE | Sí |  | Fecha de inicio de terminación (capítulo IV). |
| `adjiv_fecha_fin_term` | DATE | Sí |  | Fecha de fin de terminación (capítulo IV). |
| `adjiv_fecha_inicio` | DATE | Sí |  | Fecha de inicio reportada en el padrón `listado`. |
| `adjiv_fecha_fin` | DATE | Sí |  | Fecha de fin reportada en el padrón `listado`. |
| `adjiv_fecha_abandono` | DATE | Sí |  | Fecha de abandono del pozo, si aplica. |
| `adjiv_equipo_utilizar` | VARCHAR | Sí |  | Equipo de perforación utilizado. |
| `adjiv_capacidad_perf` | DOUBLE | Sí |  | Capacidad de perforación del equipo. |
| `pet_inicial` | DOUBLE | Sí |  | Caudal inicial de petróleo en el ensayo de descubrimiento (m³/d). |
| `gas_inicial` | DOUBLE | Sí |  | Caudal inicial de gas en el ensayo de descubrimiento (Mm³/d). |
| `agua_inicial` | DOUBLE | Sí |  | Caudal inicial de agua en el ensayo de descubrimiento (m³/d). |
| `iny_agua_inicial` | DOUBLE | Sí |  | Inyección inicial de agua reportada en el ensayo (m³/d). |
| `iny_gas_inicial` | DOUBLE | Sí |  | Inyección inicial de gas reportada en el ensayo (Mm³/d). |
| `iny_otros_inicial` | DOUBLE | Sí |  | Inyección inicial de otros fluidos reportada en el ensayo. |
| `iny_co2_inicial` | DOUBLE | Sí |  | Inyección inicial de CO₂ reportada en el ensayo. |
| `vida_util_inicial` | DOUBLE | Sí |  | Vida útil estimada al momento del ensayo inicial (meses). |
| `has_production` | BOOLEAN | Sí |  | `true` si el `idpozo` aparece alguna vez en producción mensual; `false` para los pozos huérfanos del capítulo IV que nunca produjeron. |

---

### `well_operator_history`

Histórico de operadores por pozo (slowly-changing dimension). Una fila por corrida contigua de `idempresa` por `idpozo`. Las corridas con `idempresa` NULL se preservan tal cual: la ausencia de operador es información de la fuente.

**Columnas:**

| Columna | Tipo | Nullable | PK | Descripción |
|---------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Identificador entero del pozo (wellbore × formación productiva). Clave primaria del modelo. |
| `idempresa` | VARCHAR | Sí |  | Código alfanumérico de la operadora (`Z001`, `APEA`, …). Almacenado como VARCHAR. |
| `empresa` | VARCHAR | Sí |  | Operador asociado a la corrida (en `wells`: operador inicial del registro capítulo IV; en `well_operator_history`: nombre desplegado del intervalo). |
| `valid_from` | DATE | No | ✓ | Primer mes de la corrida contigua de operador (DATE, primero de mes, inclusive). |
| `valid_to` | DATE | Sí |  | Último mes de la corrida contigua de operador (DATE, primero de mes, inclusive). |

**Claves foráneas:**

- `idpozo` → `wells.idpozo`

---

### `well_events`

Eventos de estado operacional. Una fila por mes en el que cualquiera de `(tipoestado, tipoextraccion, tipopozo)` cambió. Se incluye la fila inicial de cada pozo como transición a su estado de partida; los flips de un solo mes no se suavizan.

**Columnas:**

| Columna | Tipo | Nullable | PK | Descripción |
|---------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Identificador entero del pozo (wellbore × formación productiva). Clave primaria del modelo. |
| `event_date` | DATE | No | ✓ | Mes del snapshot de estado operacional (DATE, primero de mes). |
| `tipoestado` | VARCHAR | Sí |  | Estado operacional del pozo (p. ej. `Extracción Efectiva`, `Parado Transitoriamente`). |
| `tipoextraccion` | VARCHAR | Sí |  | Método de extracción (p. ej. `Bombeo Mecánico`, `Surgente`). |
| `tipopozo` | VARCHAR | Sí |  | Tipo de pozo en función del fluido (p. ej. `Petrolífero`, `Gasífero`, `Inyector`). |

**Claves foráneas:**

- `idpozo` → `wells.idpozo`

---

### `monthly_production`

Serie mensual de medidas numéricas. Una fila por `(idpozo, fecha)` para cada mes en `[primera_fila, última_fila]` por pozo (los huecos se rellenan con medidas NULL). Particionada por `anio` vía Hive (`monthly_production/anio=YYYY/data.parquet`) y ordenada internamente por `(idpozo, fecha)` para que las estadísticas de row-group permitan podar consultas single-well sobre `httpfs`.

**Columnas:**

| Columna | Tipo | Nullable | PK | Descripción |
|---------|------|----------|----|-------------|
| `idpozo` | BIGINT | No | ✓ | Identificador entero del pozo (wellbore × formación productiva). Clave primaria del modelo. |
| `fecha` | DATE | No | ✓ | Mes de la medida (DATE, primer día del mes, derivado de `anio`/`mes` de la fuente). |
| `prod_pet` | DOUBLE | Sí |  | Producción mensual de petróleo (m³). |
| `prod_gas` | DOUBLE | Sí |  | Producción mensual de gas (Mm³). |
| `prod_agua` | DOUBLE | Sí |  | Producción mensual de agua (m³). |
| `iny_agua` | DOUBLE | Sí |  | Inyección mensual de agua (m³). |
| `iny_gas` | DOUBLE | Sí |  | Inyección mensual de gas (Mm³). |
| `iny_co2` | DOUBLE | Sí |  | Inyección mensual de CO₂. |
| `iny_otro` | DOUBLE | Sí |  | Inyección mensual de otros fluidos. |
| `tef` | DOUBLE | Sí |  | Tiempo Efectivo de Producción del mes (horas). |
| `vida_util` | DOUBLE | Sí |  | Vida útil declarada del pozo en el mes (meses). |

**Claves foráneas:**

- `idpozo` → `wells.idpozo`

---

## Relaciones

```
well_operator_history.idpozo → wells.idpozo
well_events.idpozo → wells.idpozo
monthly_production.idpozo → wells.idpozo
```

## Glosario de códigos

Algunas siglas heredadas de la fuente no son evidentes a primera vista:

| Código | Significado |
|--------|-------------|
| `tef` | Tiempo Efectivo de Producción del mes (horas). |
| `vida_util` | Vida útil declarada del pozo en el mes (meses). |
| `formprod` | Formación productiva del `idpozo`. Atributo estático. |
| `idpozo` | Identidad canónica: wellbore × formación productiva. PK del modelo. |
| `sigla` | Código humano del pozo. Etiqueta, posiblemente mutable, no PK. |
| `idempresa` | Código alfanumérico de la operadora. **VARCHAR**, no INTEGER. |

## Columnas eliminadas

Las siguientes columnas de la fuente son administrativas/de auditoría y no se publican:

- `geojson`
- `observaciones`
- `idusuario`
- `rectificado`
- `habilitado`
- `fechaingreso`
- `fecha_data`
