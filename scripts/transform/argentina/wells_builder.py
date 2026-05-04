"""Build the Argentina static master table from staged sources.

Spine = capitulo-iv (~85,380 wells, 100% geometry coverage).
LEFT JOIN listado for enrichment columns capitulo-iv lacks.
For the ~37 wells that appear in production but not in capitulo-iv,
fall back to listado, then to per-`idpozo` modal values from production.
The 113 capitulo-iv-only orphans are retained with `has_production=false`.

Capitulo-iv wins on every overlapping field. The `geojson` column and the
six admin/audit columns (observaciones, idusuario, rectificado, habilitado,
fechaingreso, fecha_data) are dropped per CONTEXT.md. capitulo-iv's
operator-state triple (tipopozo, tipoextraccion, tipoestado) is dropped
here because it belongs to the events table, not the static master.

Source `geom` arrives as a hex-WKB string from CSV; it is decoded to
BLOB on the way in. The export validator parses every non-NULL `geom`
to verify WKB integrity before publish.
"""

import duckdb


def build(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE wells AS
        WITH
        prod_wells AS (
            SELECT DISTINCT idpozo FROM stg_production
        ),
        prod_modes AS (
            SELECT
                idpozo,
                mode(sigla)               AS sigla,
                mode(formprod)            AS formprod,
                mode(formacion)           AS formacion,
                mode(cuenca)              AS cuenca,
                mode(provincia)           AS provincia,
                mode(profundidad)         AS profundidad,
                mode(tipo_de_recurso)     AS tipo_recurso,
                mode(sub_tipo_recurso)    AS sub_tipo_recurso,
                mode(clasificacion)       AS clasificacion,
                mode(subclasificacion)    AS subclasificacion,
                mode(proyecto)            AS proyecto,
                mode(areapermisoconcesion)   AS area,
                mode(idareapermisoconcesion) AS cod_area,
                mode(areayacimiento)         AS yacimiento,
                mode(idareayacimiento)       AS cod_yacimiento
            FROM stg_production
            GROUP BY idpozo
        ),
        all_idpozos AS (
            SELECT idpozo FROM stg_capitulo_iv
            UNION
            SELECT idpozo FROM prod_wells
        )
        SELECT
            a.idpozo,
            -- Identity / labels (capitulo-iv wins; listado fallback for
            -- production-only wells; production-mode is last resort)
            COALESCE(c.sigla, l.sigla, p.sigla)                       AS sigla,
            l.formprod                                                AS formprod,
            l.codigopropio                                            AS codigopropio,
            l.nombrepropio                                            AS nombrepropio,
            -- Location codes (capitulo-iv name → listado/production fallback)
            COALESCE(c.area, l.areapermisoconcesion, p.area)          AS area,
            COALESCE(c.cod_area, l.idareapermisoconcesion, p.cod_area) AS cod_area,
            COALESCE(c.yacimiento, l.areayacimiento, p.yacimiento)    AS yacimiento,
            COALESCE(c.cod_yacimiento, l.idareayacimiento, p.cod_yacimiento) AS cod_yacimiento,
            COALESCE(c.cuenca, l.cuenca, p.cuenca)                    AS cuenca,
            COALESCE(c.provincia, l.provincia, p.provincia)           AS provincia,
            l.idcuenca                                                AS idcuenca,
            l.idprovincia                                             AS idprovincia,
            -- Geophysical
            COALESCE(c.formacion, p.formacion)                        AS formacion,
            COALESCE(c.cota, l.cota)                                  AS cota,
            COALESCE(c.profundidad, l.profundidad, p.profundidad)     AS profundidad,
            -- Classification
            COALESCE(c.clasificacion, p.clasificacion)                AS clasificacion,
            COALESCE(c.subclasificacion, p.subclasificacion)          AS subclasificacion,
            COALESCE(c.tipo_recurso, p.tipo_recurso)                  AS tipo_recurso,
            COALESCE(c.sub_tipo_recurso, p.sub_tipo_recurso)          AS sub_tipo_recurso,
            c.gasplus                                                 AS gasplus,
            -- Project (production-only column)
            p.proyecto                                                AS proyecto,
            -- Initial operator (capitulo-iv only — slowly-changing operator
            -- transfers live in well_operator_history)
            c.empresa                                                 AS empresa,
            -- Spatial
            l.coordenadax                                             AS coordenadax,
            l.coordenaday                                             AS coordenaday,
            unhex(c.geom)                                             AS geom,
            -- Drilling / completion / abandonment
            c.adjiv_fecha_inicio_perf                                 AS adjiv_fecha_inicio_perf,
            c.adjiv_fecha_fin_perf                                    AS adjiv_fecha_fin_perf,
            c.adjiv_fecha_inicio_term                                 AS adjiv_fecha_inicio_term,
            c.adjiv_fecha_fin_term                                    AS adjiv_fecha_fin_term,
            l.adjiv_fecha_inicio                                      AS adjiv_fecha_inicio,
            l.adjiv_fecha_fin                                         AS adjiv_fecha_fin,
            l.adjiv_fecha_abandono                                    AS adjiv_fecha_abandono,
            l.adjiv_equipo_utilizar                                   AS adjiv_equipo_utilizar,
            l.adjiv_capacidad_perf                                    AS adjiv_capacidad_perf,
            -- Initial test rates
            l.pet_inicial                                             AS pet_inicial,
            l.gas_inicial                                             AS gas_inicial,
            l.agua_inicial                                            AS agua_inicial,
            l.iny_agua_inicial                                        AS iny_agua_inicial,
            l.iny_gas_inicial                                         AS iny_gas_inicial,
            l.iny_otros_inicial                                       AS iny_otros_inicial,
            l.iny_co2_inicial                                         AS iny_co2_inicial,
            l.vida_util_inicial                                       AS vida_util_inicial,
            -- Production-presence flag
            (pw.idpozo IS NOT NULL)                                   AS has_production
        FROM all_idpozos a
        LEFT JOIN stg_capitulo_iv c ON a.idpozo = c.idpozo
        LEFT JOIN stg_listado     l ON a.idpozo = l.idpozo
        LEFT JOIN prod_modes      p ON a.idpozo = p.idpozo
        LEFT JOIN prod_wells     pw ON a.idpozo = pw.idpozo
        """
    )
