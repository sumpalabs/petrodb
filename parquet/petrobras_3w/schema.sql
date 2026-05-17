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
