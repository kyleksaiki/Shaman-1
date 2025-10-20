CREATE DATABASE IF NOT EXISTS noise_db;
USE noise_db;

CREATE TABLE IF NOT EXISTS noise_events (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  device_id VARCHAR(64) NOT NULL,
  event_start_utc DATETIME(6) NOT NULL,
  duration_ms INT UNSIGNED NOT NULL,
  peak_dbfs DECIMAL(5,2) NOT NULL,
  created_at_utc TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_event_start (event_start_utc)
);
