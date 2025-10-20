# api.py
# ---------------------------------------------------------------------------
# FastAPI endpoint for storing *sound events* into MySQL using your schema:
#
#   CREATE TABLE noise_events (
#     id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
#     device_id VARCHAR(64) NOT NULL,
#     event_start_utc DATETIME(6) NOT NULL,
#     duration_ms INT UNSIGNED NOT NULL,
#     peak_dbfs DECIMAL(5,2) NOT NULL,
#     created_at_utc TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
#     KEY idx_event_start (event_start_utc)
#   );
#
# POST /noise  (API key in header "X-API-Key")
# Body:
# {
#   "device_id": "esp32-01",
#   "duration_ms": 1234,
#   "peak_dbfs": -12.34,
#   "esp_epoch": 1730000000   // optional (seconds). If missing, server time is used.
# }
#
# The server computes event_start_utc = esp_epoch - duration_ms and inserts.
# Returns 204 No Content (silent on success; prints simple logs).
# ---------------------------------------------------------------------------

import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import pymysql
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Noise Detector API (Event Store)")

# ---- Auth (hardcoded; matches your device setup) ---------------------------
API_KEY = "1234"

# ---- MySQL connection (hardcoded; keep as requested) -----------------------
DB_HOST = "Your Info"
DB_USER = "Your Info"
DB_PASS = "Your Info"
DB_NAME = "noise_db"
TABLE   = "noise_events"

def get_conn():
    """Create a new PyMySQL connection (autocommit)."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        autocommit=True,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.Cursor,
    )

# ---- Request model ----------------------------------------------------------
class NoiseEvent(BaseModel):
    device_id: str = Field(..., max_length=64, description="ESP32 identifier")
    duration_ms: int = Field(..., ge=1, description="Event length in milliseconds")
    peak_dbfs: float = Field(..., description="Peak loudness (dBFS), negative number")
    esp_epoch: Optional[int] = Field(
        None, description="Device timestamp in SECONDS (UNIX epoch). If absent, server time is used."
    )

# ---- Endpoint ---------------------------------------------------------------
@app.post("/noise", status_code=204)
async def noise(evt: NoiseEvent, x_api_key: str = Header(None)):
    """Accept a noise event and write it to MySQL using the schema above."""
    # Simple header auth
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Bad API key")

    # Determine event end time (seconds) then compute start (UTC)
    ts_end = evt.esp_epoch if evt.esp_epoch is not None else int(time.time())
    start_dt_utc = datetime.fromtimestamp(ts_end, tz=timezone.utc) - timedelta(milliseconds=evt.duration_ms)

    # Log one concise line for diagnostics
    print(
        f"device_id={evt.device_id} "
        f"start={start_dt_utc.isoformat()} "
        f"dur={evt.duration_ms}ms "
        f"peak={evt.peak_dbfs:.2f}dBFS"
    )

    # Insert row (MySQL DATETIME(6) is naive; drop tzinfo)
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE} (device_id, event_start_utc, duration_ms, peak_dbfs)
                VALUES (%s, %s, %s, %s)
                """,
                (evt.device_id, start_dt_utc.replace(tzinfo=None), evt.duration_ms, round(evt.peak_dbfs, 2)),
            )
    except Exception as e:
        # Keep device flow quiet: print error, still return 204 (as per your test style)
        print("DB ERROR:", e)
        return
