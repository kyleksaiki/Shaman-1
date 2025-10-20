-- select_all.sql
USE noise_db;
SELECT id, device_id, event_start_utc, duration_ms, peak_dbfs, created_at_utc
FROM noise_events
ORDER BY id DESC;