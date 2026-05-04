"""Unit tests for the Argentina wells_builder.

Synthetic in-memory DuckDB connections seed the three staged source
tables and exercise wells_builder.build directly. This isolates
master-assembly logic from the end-to-end smoke harness.
"""

import duckdb
import pytest

from scripts.transform.argentina import wells_builder


def _stage_capitulo_iv(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE stg_capitulo_iv (
            sigla VARCHAR,
            idpozo INTEGER,
            area VARCHAR,
            cod_area VARCHAR,
            empresa VARCHAR,
            yacimiento VARCHAR,
            cod_yacimiento VARCHAR,
            formacion VARCHAR,
            cuenca VARCHAR,
            provincia VARCHAR,
            cota DOUBLE,
            profundidad DOUBLE,
            clasificacion VARCHAR,
            subclasificacion VARCHAR,
            tipo_recurso VARCHAR,
            sub_tipo_recurso VARCHAR,
            gasplus VARCHAR,
            tipopozo VARCHAR,
            tipoextraccion VARCHAR,
            tipoestado VARCHAR,
            adjiv_fecha_inicio_perf DATE,
            adjiv_fecha_fin_perf DATE,
            adjiv_fecha_inicio_term DATE,
            adjiv_fecha_fin_term DATE,
            geojson VARCHAR,
            geom VARCHAR
        )
        """
    )
    if rows:
        con.executemany(
            "INSERT INTO stg_capitulo_iv VALUES (" + ",".join(["?"] * 26) + ")",
            rows,
        )


def _stage_listado(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE stg_listado (
            idpozo INTEGER,
            sigla VARCHAR,
            formprod VARCHAR,
            idempresa VARCHAR,
            idareapermisoconcesion VARCHAR,
            idareayacimiento VARCHAR,
            idcuenca VARCHAR,
            idprovincia VARCHAR,
            codigopropio VARCHAR,
            nombrepropio VARCHAR,
            coordenadax DOUBLE,
            coordenaday DOUBLE,
            cota DOUBLE,
            profundidad DOUBLE,
            pet_inicial DOUBLE,
            gas_inicial DOUBLE,
            agua_inicial DOUBLE,
            iny_agua_inicial DOUBLE,
            iny_gas_inicial DOUBLE,
            iny_otros_inicial DOUBLE,
            iny_co2_inicial DOUBLE,
            vida_util_inicial DOUBLE,
            adjiv_fecha_inicio DATE,
            adjiv_equipo_utilizar VARCHAR,
            adjiv_capacidad_perf VARCHAR,
            adjiv_fecha_fin DATE,
            adjiv_fecha_abandono DATE,
            areapermisoconcesion VARCHAR,
            areayacimiento VARCHAR,
            cuenca VARCHAR,
            provincia VARCHAR
        )
        """
    )
    if rows:
        con.executemany(
            "INSERT INTO stg_listado VALUES (" + ",".join(["?"] * 31) + ")",
            rows,
        )


def _stage_production(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.execute(
        """
        CREATE OR REPLACE TABLE stg_production (
            idpozo INTEGER,
            anio INTEGER,
            mes INTEGER,
            sigla VARCHAR,
            formprod VARCHAR,
            formacion VARCHAR,
            cuenca VARCHAR,
            provincia VARCHAR,
            profundidad DOUBLE,
            idareapermisoconcesion VARCHAR,
            areapermisoconcesion VARCHAR,
            idareayacimiento VARCHAR,
            areayacimiento VARCHAR,
            tipo_de_recurso VARCHAR,
            sub_tipo_recurso VARCHAR,
            clasificacion VARCHAR,
            subclasificacion VARCHAR,
            proyecto VARCHAR
        )
        """
    )
    if rows:
        con.executemany(
            "INSERT INTO stg_production VALUES (" + ",".join(["?"] * 18) + ")",
            rows,
        )


HEX_WKB = "0101000020E61000000000000000405140000000000000C040"


def _capitulo_row(idpozo: int, sigla: str, **overrides) -> tuple:
    """Build a capitulo-iv row tuple, with overrides for key fields."""
    base = {
        "sigla": sigla,
        "idpozo": idpozo,
        "area": f"AREA-{idpozo}",
        "cod_area": f"COD-{idpozo}",
        "empresa": "OPERATOR",
        "yacimiento": f"YAC-{idpozo}",
        "cod_yacimiento": f"YC-{idpozo}",
        "formacion": "fm",
        "cuenca": "NEUQUINA",
        "provincia": "Neuquén",
        "cota": 500.0,
        "profundidad": 2000.0,
        "clasificacion": "EXPLORACION",
        "subclasificacion": "EXPLORACION",
        "tipo_recurso": "CONVENCIONAL",
        "sub_tipo_recurso": "No informado",
        "gasplus": "no",
        "tipopozo": "Petrolífero",
        "tipoextraccion": "Bombeo Mecánico",
        "tipoestado": "Extracción Efectiva",
        "adjiv_fecha_inicio_perf": "2006-01-01",
        "adjiv_fecha_fin_perf": "2006-01-15",
        "adjiv_fecha_inicio_term": "2006-01-20",
        "adjiv_fecha_fin_term": "2006-02-01",
        "geojson": '{"type":"Point"}',
        "geom": HEX_WKB,
    }
    base.update(overrides)
    return tuple(base.values())


def _listado_row(idpozo: int, **overrides) -> tuple:
    base = {
        "idpozo": idpozo,
        "sigla": f"LST.{idpozo}",
        "formprod": "TFM",
        "idempresa": "Z001",
        "idareapermisoconcesion": f"COD-{idpozo}",
        "idareayacimiento": f"YC-{idpozo}",
        "idcuenca": "NEU",
        "idprovincia": "Q",
        "codigopropio": f"CP-{idpozo}",
        "nombrepropio": f"NP-{idpozo}",
        "coordenadax": -69.0,
        "coordenaday": -38.0,
        "cota": 500.0,
        "profundidad": 2000.0,
        "pet_inicial": 10.0,
        "gas_inicial": 100.0,
        "agua_inicial": 5.0,
        "iny_agua_inicial": 0.0,
        "iny_gas_inicial": 0.0,
        "iny_otros_inicial": 0.0,
        "iny_co2_inicial": 0.0,
        "vida_util_inicial": 15.0,
        "adjiv_fecha_inicio": "2006-01-01",
        "adjiv_equipo_utilizar": None,
        "adjiv_capacidad_perf": None,
        "adjiv_fecha_fin": "2006-01-15",
        "adjiv_fecha_abandono": None,
        "areapermisoconcesion": f"AREA-{idpozo}",
        "areayacimiento": f"YAC-{idpozo}",
        "cuenca": "NEUQUINA",
        "provincia": "Neuquén",
    }
    base.update(overrides)
    return tuple(base.values())


def _production_row(idpozo: int, anio: int = 2006, mes: int = 1, **overrides) -> tuple:
    base = {
        "idpozo": idpozo,
        "anio": anio,
        "mes": mes,
        "sigla": f"PRD.{idpozo}",
        "formprod": "TFM",
        "formacion": "prod_fm",
        "cuenca": "NEUQUINA",
        "provincia": "Neuquén",
        "profundidad": 2000.0,
        "idareapermisoconcesion": f"COD-{idpozo}",
        "areapermisoconcesion": f"AREA-{idpozo}",
        "idareayacimiento": f"YC-{idpozo}",
        "areayacimiento": f"YAC-{idpozo}",
        "tipo_de_recurso": "CONVENCIONAL",
        "sub_tipo_recurso": "No informado",
        "clasificacion": "EXPLORACION",
        "subclasificacion": "EXPLORACION",
        "proyecto": "Sin Proyecto",
    }
    base.update(overrides)
    return tuple(base.values())


@pytest.fixture
def con():
    c = duckdb.connect()
    yield c
    c.close()


def test_capitulo_iv_well_with_production(con):
    """A well in capitulo-iv with matching production rows is emitted with has_production=true."""
    _stage_capitulo_iv(con, [_capitulo_row(1001, "TST.AAA.x-1")])
    _stage_listado(con, [_listado_row(1001, sigla="LST.1001")])
    _stage_production(con, [_production_row(1001)])

    wells_builder.build(con)

    rows = con.execute(
        "SELECT idpozo, has_production FROM wells ORDER BY idpozo"
    ).fetchall()
    assert rows == [(1001, True)]


def test_orphan_capitulo_iv_well_has_production_false(con):
    """A well in capitulo-iv with no production gets has_production=false."""
    _stage_capitulo_iv(con, [_capitulo_row(2001, "TST.ORPHAN.x-1")])
    _stage_listado(con, [])
    _stage_production(con, [])

    wells_builder.build(con)

    rows = con.execute(
        "SELECT idpozo, has_production FROM wells ORDER BY idpozo"
    ).fetchall()
    assert rows == [(2001, False)]


def test_production_only_well_falls_back_to_listado(con):
    """A well absent from capitulo-iv but present in listado + production
    is emitted with values from listado, not production."""
    _stage_capitulo_iv(con, [])
    _stage_listado(con, [_listado_row(3001, sigla="LISTADO.SIGLA")])
    _stage_production(con, [_production_row(3001, sigla="PROD.SIGLA")])

    wells_builder.build(con)

    rows = con.execute("SELECT idpozo, sigla, has_production FROM wells").fetchall()
    assert rows == [(3001, "LISTADO.SIGLA", True)]


def test_production_only_well_falls_back_to_production_modes(con):
    """A well absent from capitulo-iv AND listado falls back to
    production-derived modal values."""
    _stage_capitulo_iv(con, [])
    _stage_listado(con, [])
    # Two production rows; mode of sigla is "PROD.SIGLA"
    _stage_production(
        con,
        [
            _production_row(4001, anio=2006, mes=1, sigla="PROD.SIGLA"),
            _production_row(4001, anio=2006, mes=2, sigla="PROD.SIGLA"),
        ],
    )

    wells_builder.build(con)

    rows = con.execute("SELECT idpozo, sigla, has_production FROM wells").fetchall()
    assert rows == [(4001, "PROD.SIGLA", True)]


def test_capitulo_iv_wins_on_field_conflict(con):
    """Where capitulo-iv and listado disagree on a shared column,
    capitulo-iv wins (it's the regulatory source)."""
    _stage_capitulo_iv(con, [_capitulo_row(5001, "CAPIV.SIGLA")])
    _stage_listado(con, [_listado_row(5001, sigla="LISTADO.SIGLA")])
    _stage_production(con, [_production_row(5001, sigla="PROD.SIGLA")])

    wells_builder.build(con)

    sigla = con.execute("SELECT sigla FROM wells WHERE idpozo = 5001").fetchone()[0]
    assert sigla == "CAPIV.SIGLA"


def test_dropped_admin_audit_columns_absent(con):
    """The 6 admin/audit columns plus geojson must not appear in the wells table."""
    _stage_capitulo_iv(con, [_capitulo_row(6001, "TST.X")])
    _stage_listado(con, [_listado_row(6001)])
    _stage_production(con, [_production_row(6001)])

    wells_builder.build(con)

    cols = {row[0] for row in con.execute("DESCRIBE wells").fetchall()}
    forbidden = {
        "geojson",
        "observaciones",
        "idusuario",
        "rectificado",
        "habilitado",
        "fechaingreso",
        "fecha_data",
    }
    leaked = cols & forbidden
    assert not leaked, f"forbidden columns leaked into wells: {leaked}"


def test_geom_stored_as_blob(con):
    """capitulo-iv ships geom as hex-WKB string; the wells table stores BLOB."""
    _stage_capitulo_iv(con, [_capitulo_row(7001, "TST.X")])
    _stage_listado(con, [])
    _stage_production(con, [])

    wells_builder.build(con)

    geom_type = con.execute(
        "SELECT typeof(geom) FROM wells WHERE idpozo = 7001"
    ).fetchone()[0]
    assert geom_type == "BLOB"


def test_production_only_well_has_null_geom(con):
    """A production-only well has no capitulo-iv row → geom is NULL."""
    _stage_capitulo_iv(con, [])
    _stage_listado(con, [_listado_row(8001)])
    _stage_production(con, [_production_row(8001)])

    wells_builder.build(con)

    geom = con.execute("SELECT geom FROM wells WHERE idpozo = 8001").fetchone()[0]
    assert geom is None


def test_static_master_columns_present(con):
    """The wells table exposes the columns enumerated in CONTEXT.md."""
    _stage_capitulo_iv(con, [_capitulo_row(9001, "TST.X")])
    _stage_listado(con, [_listado_row(9001)])
    _stage_production(con, [_production_row(9001)])

    wells_builder.build(con)

    cols = {row[0] for row in con.execute("DESCRIBE wells").fetchall()}
    expected = {
        "idpozo",
        "sigla",
        "formprod",
        "formacion",
        "profundidad",
        "cuenca",
        "provincia",
        "tipo_recurso",
        "sub_tipo_recurso",
        "clasificacion",
        "subclasificacion",
        "proyecto",
        "coordenadax",
        "coordenaday",
        "geom",
        "codigopropio",
        "nombrepropio",
        "pet_inicial",
        "gas_inicial",
        "agua_inicial",
        "vida_util_inicial",
        "has_production",
    }
    missing = expected - cols
    assert not missing, f"expected columns missing from wells: {missing}"
