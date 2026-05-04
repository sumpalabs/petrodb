-- Argentina production dataset — DDL
-- Auto-generated from the published Parquet schemas. Do not edit by hand.

CREATE TABLE wells (
  idpozo BIGINT NOT NULL,
  sigla VARCHAR,
  formprod VARCHAR,
  codigopropio VARCHAR,
  nombrepropio VARCHAR,
  area VARCHAR,
  cod_area VARCHAR,
  yacimiento VARCHAR,
  cod_yacimiento VARCHAR,
  cuenca VARCHAR,
  provincia VARCHAR,
  idcuenca VARCHAR,
  idprovincia VARCHAR,
  formacion VARCHAR,
  cota DOUBLE,
  profundidad DOUBLE,
  clasificacion VARCHAR,
  subclasificacion VARCHAR,
  tipo_recurso VARCHAR,
  sub_tipo_recurso VARCHAR,
  gasplus VARCHAR,
  proyecto VARCHAR,
  empresa VARCHAR,
  coordenadax DOUBLE,
  coordenaday DOUBLE,
  geom BLOB,
  adjiv_fecha_inicio_perf DATE,
  adjiv_fecha_fin_perf DATE,
  adjiv_fecha_inicio_term DATE,
  adjiv_fecha_fin_term DATE,
  adjiv_fecha_inicio DATE,
  adjiv_fecha_fin DATE,
  adjiv_fecha_abandono DATE,
  adjiv_equipo_utilizar VARCHAR,
  adjiv_capacidad_perf DOUBLE,
  pet_inicial DOUBLE,
  gas_inicial DOUBLE,
  agua_inicial DOUBLE,
  iny_agua_inicial DOUBLE,
  iny_gas_inicial DOUBLE,
  iny_otros_inicial DOUBLE,
  iny_co2_inicial DOUBLE,
  vida_util_inicial DOUBLE,
  has_production BOOLEAN,
  PRIMARY KEY (idpozo)
);

CREATE TABLE well_operator_history (
  idpozo BIGINT NOT NULL,
  idempresa VARCHAR,
  empresa VARCHAR,
  valid_from DATE NOT NULL,
  valid_to DATE,
  PRIMARY KEY (idpozo, valid_from),
  FOREIGN KEY (idpozo) REFERENCES wells (idpozo)
);

CREATE TABLE well_events (
  idpozo BIGINT NOT NULL,
  event_date DATE NOT NULL,
  tipoestado VARCHAR,
  tipoextraccion VARCHAR,
  tipopozo VARCHAR,
  PRIMARY KEY (idpozo, event_date),
  FOREIGN KEY (idpozo) REFERENCES wells (idpozo)
);

CREATE TABLE monthly_production (
  idpozo BIGINT NOT NULL,
  fecha DATE NOT NULL,
  prod_pet DOUBLE,
  prod_gas DOUBLE,
  prod_agua DOUBLE,
  iny_agua DOUBLE,
  iny_gas DOUBLE,
  iny_co2 DOUBLE,
  iny_otro DOUBLE,
  tef DOUBLE,
  vida_util DOUBLE,
  PRIMARY KEY (idpozo, fecha),
  FOREIGN KEY (idpozo) REFERENCES wells (idpozo)
);
