-- FORCE 2020 dataset — DDL
-- Auto-generated from the published Parquet schema. Do not edit by hand.
-- Upstream: https://github.com/bolgebrygg/Force-2020-Machine-Learning-competition

-- One row per ~0.15 m log sample. Published as one Parquet file per
-- well under wells/<well>.parquet; (WELL, DEPTH_MD) is the primary key.
CREATE TABLE wells (
  WELL VARCHAR NOT NULL,
  DEPTH_MD DOUBLE NOT NULL,
  X_LOC DOUBLE,
  Y_LOC DOUBLE,
  Z_LOC DOUBLE,
  "GROUP" VARCHAR,
  FORMATION VARCHAR,
  CALI DOUBLE,
  RSHA DOUBLE,
  RMED DOUBLE,
  RDEP DOUBLE,
  RHOB DOUBLE,
  GR DOUBLE,
  SGR DOUBLE,
  NPHI DOUBLE,
  PEF DOUBLE,
  DTC DOUBLE,
  SP DOUBLE,
  BS DOUBLE,
  ROP DOUBLE,
  DTS DOUBLE,
  DCAL DOUBLE,
  DRHO DOUBLE,
  MUDWEIGHT DOUBLE,
  RMIC DOUBLE,
  ROPA DOUBLE,
  RXO DOUBLE,
  FORCE_2020_LITHOFACIES_LITHOLOGY BIGINT,
  dataset VARCHAR,
  PRIMARY KEY (WELL, DEPTH_MD)
);
