"""Unit tests for the Argentina export validator.

Exercises every PRD invariant: WKB-parseability, FK integrity for
`well_operator_history` / `well_events` / `monthly_production`,
PK uniqueness on `(idpozo, fecha)`, date-completeness, post-write
partition-count, and the 50 MB soft warning.
"""

from datetime import date
from pathlib import Path

import duckdb
import pytest

from scripts.export.argentina import parquet_writer, validator

VALID_WKB_HEX = "0101000020E61000000000000000405140000000000000C040"
INVALID_WKB_HEX = "DEADBEEFCAFEBABEDEADBEEFCAFEBABE"

MP_COLUMNS = (
    "idpozo INTEGER, fecha DATE, "
    "prod_pet DOUBLE, prod_gas DOUBLE, prod_agua DOUBLE, "
    "iny_agua DOUBLE, iny_gas DOUBLE, iny_co2 DOUBLE, iny_otro DOUBLE, "
    "tef DOUBLE, vida_util DOUBLE"
)


def _make_wells_with_geom(
    con: duckdb.DuckDBPyConnection, hex_values: list[str | None]
) -> None:
    con.execute("CREATE OR REPLACE TABLE wells (idpozo INTEGER, geom BLOB)")
    for i, hx in enumerate(hex_values, start=1):
        if hx is None:
            con.execute("INSERT INTO wells VALUES (?, NULL)", [i])
        else:
            con.execute(
                "INSERT INTO wells VALUES (?, unhex(?))",
                [i, hx],
            )
    con.execute(
        """
        CREATE OR REPLACE TABLE well_operator_history (
            idpozo INTEGER,
            idempresa VARCHAR,
            empresa VARCHAR,
            valid_from DATE,
            valid_to DATE
        )
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TABLE well_events (
            idpozo INTEGER,
            event_date DATE,
            tipoestado VARCHAR,
            tipoextraccion VARCHAR,
            tipopozo VARCHAR
        )
        """
    )
    con.execute(f"CREATE OR REPLACE TABLE monthly_production ({MP_COLUMNS})")


def _seed_operator_history(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO well_operator_history VALUES (?, ?, ?, ?, ?)", rows)


def _seed_well_events(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    con.executemany("INSERT INTO well_events VALUES (?, ?, ?, ?, ?)", rows)


def _mp_row(idpozo: int, fecha: date) -> tuple:
    """A monthly_production row with arbitrary measurements."""
    return (idpozo, fecha, 80.0, 1900.0, 7.0, 0.0, 0.0, 0.0, 0.0, 15.0, 1800.0)


def _seed_monthly_production(con: duckdb.DuckDBPyConnection, rows: list[tuple]) -> None:
    if not rows:
        return
    con.executemany(
        "INSERT INTO monthly_production VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def test_validator_passes_on_valid_wkb():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, VALID_WKB_HEX])
    validator.validate(con)


def test_validator_passes_when_geom_is_null():
    """NULL geom rows are skipped (the invariant only applies to non-NULL rows)."""
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, None, None])
    validator.validate(con)


def test_validator_raises_on_invalid_wkb():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, INVALID_WKB_HEX])
    with pytest.raises(Exception):
        validator.validate(con)


def test_operator_history_fk_passes_when_all_idpozos_in_wells():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, VALID_WKB_HEX])
    _seed_operator_history(
        con,
        [
            (1, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 12, 1)),
            (2, "APEA", "APEA OPERATOR", date(2006, 1, 1), date(2006, 12, 1)),
        ],
    )
    validator.validate(con)


def test_operator_history_fk_raises_on_orphan_idpozo():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])  # idpozo 1 only
    _seed_operator_history(
        con,
        [
            (1, "Z001", "OPERATOR Z", date(2006, 1, 1), date(2006, 12, 1)),
            (999, "APEA", "APEA OPERATOR", date(2006, 1, 1), date(2006, 12, 1)),
        ],
    )
    with pytest.raises(validator.FKIntegrityError, match="well_operator_history"):
        validator.validate(con)


def test_operator_history_fk_passes_when_history_empty():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    validator.validate(con)


def test_well_events_fk_passes_when_all_idpozos_in_wells():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, VALID_WKB_HEX])
    _seed_well_events(
        con,
        [
            (
                1,
                date(2006, 1, 1),
                "Extracción Efectiva",
                "Bombeo Mecánico",
                "Petrolífero",
            ),
            (
                2,
                date(2006, 1, 1),
                "Extracción Efectiva",
                "Surgencia Natural",
                "Gasífero",
            ),
        ],
    )
    validator.validate(con)


def test_well_events_fk_raises_on_orphan_idpozo():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])  # idpozo 1 only
    _seed_well_events(
        con,
        [
            (
                1,
                date(2006, 1, 1),
                "Extracción Efectiva",
                "Bombeo Mecánico",
                "Petrolífero",
            ),
            (999, date(2006, 1, 1), "Abandonado", "Surgencia Natural", "Gasífero"),
        ],
    )
    with pytest.raises(validator.FKIntegrityError, match="well_events"):
        validator.validate(con)


def test_well_events_fk_passes_when_events_empty():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    validator.validate(con)


# ---- monthly_production FK -------------------------------------------------


def test_monthly_production_fk_passes_when_all_idpozos_in_wells():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX, VALID_WKB_HEX])
    _seed_monthly_production(
        con,
        [
            _mp_row(1, date(2006, 1, 1)),
            _mp_row(2, date(2006, 1, 1)),
        ],
    )
    validator.validate(con)


def test_monthly_production_fk_raises_on_orphan_idpozo():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    _seed_monthly_production(
        con,
        [
            _mp_row(1, date(2006, 1, 1)),
            _mp_row(999, date(2006, 1, 1)),
        ],
    )
    with pytest.raises(validator.FKIntegrityError, match="monthly_production"):
        validator.validate(con)


# ---- monthly_production PK uniqueness --------------------------------------


def test_monthly_production_pk_passes_on_unique_keys():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    _seed_monthly_production(
        con,
        [
            _mp_row(1, date(2006, 1, 1)),
            _mp_row(1, date(2006, 2, 1)),
        ],
    )
    validator.validate(con)


def test_monthly_production_pk_raises_on_duplicate_keys():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    _seed_monthly_production(
        con,
        [
            _mp_row(1, date(2006, 1, 1)),
            _mp_row(1, date(2006, 1, 1)),
        ],
    )
    with pytest.raises(validator.PKUniquenessError, match="monthly_production"):
        validator.validate(con)


# ---- monthly_production date completeness ---------------------------------


def test_monthly_production_date_completeness_passes_on_dense_grid():
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    _seed_monthly_production(
        con,
        [
            _mp_row(1, date(2006, 1, 1)),
            _mp_row(1, date(2006, 2, 1)),
            _mp_row(1, date(2006, 3, 1)),
        ],
    )
    validator.validate(con)


def test_monthly_production_date_completeness_raises_on_missing_month():
    """Well 1 has Jan + Mar but no Feb — span is 3 months, count is 2."""
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    _seed_monthly_production(
        con,
        [
            _mp_row(1, date(2006, 1, 1)),
            _mp_row(1, date(2006, 3, 1)),
        ],
    )
    with pytest.raises(validator.DateCompletenessError):
        validator.validate(con)


def test_monthly_production_date_completeness_passes_on_single_row():
    """A single-row well has span 1 and count 1 — vacuously dense."""
    con = duckdb.connect()
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    _seed_monthly_production(con, [_mp_row(1, date(2006, 1, 1))])
    validator.validate(con)


# ---- partition counts (post-write) -----------------------------------------


def _setup_for_partition_test(
    con: duckdb.DuckDBPyConnection, rows: list[tuple]
) -> None:
    _make_wells_with_geom(con, [VALID_WKB_HEX])
    _seed_monthly_production(con, rows)


def test_partition_count_passes_when_files_match_source(tmp_path: Path):
    con = duckdb.connect()
    _setup_for_partition_test(
        con,
        [_mp_row(1, date(2006, 1, 1)), _mp_row(1, date(2007, 1, 1))],
    )
    parquet_writer.write_monthly_production(con, tmp_path)
    validator.validate_partitions(con, tmp_path)


def test_partition_count_raises_when_partition_file_missing(tmp_path: Path):
    """Delete one partition file post-write; the validator must catch it."""
    con = duckdb.connect()
    _setup_for_partition_test(
        con,
        [_mp_row(1, date(2006, 1, 1)), _mp_row(1, date(2007, 1, 1))],
    )
    parquet_writer.write_monthly_production(con, tmp_path)
    (tmp_path / "monthly_production" / "anio=2007" / "data.parquet").unlink()
    with pytest.raises(validator.PartitionCountError, match="partition count"):
        validator.validate_partitions(con, tmp_path)


def test_partition_count_passes_on_empty_table(tmp_path: Path):
    """Empty source => 0 partition files; partition root may not even exist."""
    con = duckdb.connect()
    _setup_for_partition_test(con, [])
    parquet_writer.write_monthly_production(con, tmp_path)
    validator.validate_partitions(con, tmp_path)


def test_oversized_partition_emits_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Set the threshold low so the fixture trips the soft warning."""
    con = duckdb.connect()
    _setup_for_partition_test(con, [_mp_row(1, date(2006, i, 1)) for i in range(1, 13)])
    parquet_writer.write_monthly_production(con, tmp_path)
    monkeypatch.setattr(validator, "PARTITION_SIZE_WARN_BYTES", 1)
    with pytest.warns(UserWarning, match="50 MB Cloudflare headroom"):
        validator.validate_partitions(con, tmp_path)
