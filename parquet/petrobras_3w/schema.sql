-- Petrobras 3W dataset — DDL
-- Auto-generated from the published Parquet schemas. Do not edit by hand.
-- Upstream: https://github.com/petrobras/3W.git
-- Pinned git tag: v.1.70.0
-- Upstream dataset version: 2.0.0

CREATE TABLE event_types (
  event_class INTEGER NOT NULL,
  name VARCHAR,
  description VARCHAR,
  has_transient BOOLEAN,
  transient_code INTEGER,
  has_normal_prefix BOOLEAN,
  PRIMARY KEY (event_class)
);

CREATE TABLE wells (
  well_id INTEGER NOT NULL,
  n_instances BIGINT,
  first_ts TIMESTAMP,
  last_ts TIMESTAMP,
  n_observations BIGINT,
  PRIMARY KEY (well_id)
);

CREATE TABLE instances (
  instance_id VARCHAR NOT NULL,
  well_kind VARCHAR,
  well_id INTEGER,
  event_class INTEGER,
  start_ts TIMESTAMP,
  end_ts TIMESTAMP,
  duration_s BIGINT,
  n_rows BIGINT,
  n_rows_warmup_null DOUBLE,
  n_rows_normal DOUBLE,
  n_rows_transient DOUBLE,
  n_rows_steady DOUBLE,
  source_file VARCHAR,
  source_url VARCHAR,
  PRIMARY KEY (instance_id),
  FOREIGN KEY (event_class) REFERENCES event_types (event_class),
  FOREIGN KEY (well_id) REFERENCES wells (well_id)
);

-- `observations` is published as a hive-partitioned tree:
--   observations/event_class=N/<instance_id>.parquet
-- `event_class` lives in the partition path; every other column lives in the file body.
CREATE TABLE observations (
  event_class INTEGER NOT NULL,
  timestamp TIMESTAMP NOT NULL,
  class INTEGER,
  state INTEGER,
  "ABER-CKGL" DOUBLE,
  "ABER-CKP" DOUBLE,
  "ESTADO-DHSV" DOUBLE,
  "ESTADO-M1" DOUBLE,
  "ESTADO-M2" DOUBLE,
  "ESTADO-PXO" DOUBLE,
  "ESTADO-SDV-GL" DOUBLE,
  "ESTADO-SDV-P" DOUBLE,
  "ESTADO-W1" DOUBLE,
  "ESTADO-W2" DOUBLE,
  "ESTADO-XO" DOUBLE,
  "P-ANULAR" DOUBLE,
  "P-JUS-BS" DOUBLE,
  "P-JUS-CKGL" DOUBLE,
  "P-JUS-CKP" DOUBLE,
  "P-MON-CKGL" DOUBLE,
  "P-MON-CKP" DOUBLE,
  "P-MON-SDV-P" DOUBLE,
  "P-PDG" DOUBLE,
  "PT-P" DOUBLE,
  "P-TPT" DOUBLE,
  "QBS" DOUBLE,
  "QGL" DOUBLE,
  "T-JUS-CKP" DOUBLE,
  "T-MON-CKP" DOUBLE,
  "T-PDG" DOUBLE,
  "T-TPT" DOUBLE,
  instance_id VARCHAR NOT NULL,
  well_id INTEGER,
  well_kind VARCHAR,
  PRIMARY KEY (instance_id, timestamp),
  FOREIGN KEY (instance_id) REFERENCES instances (instance_id),
  FOREIGN KEY (event_class) REFERENCES event_types (event_class),
  FOREIGN KEY (well_id) REFERENCES wells (well_id)
);
