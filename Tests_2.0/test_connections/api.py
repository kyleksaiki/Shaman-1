# api.py
import time
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
from typing import Literal, Optional

app = FastAPI(title="ESP32 LED Logger (Test)")

API_KEY = "1234"  # simple test key, THIS IS BAD FOR SECURITY but okay because this is just a test program

class LedEvent(BaseModel):
    device_id: str
    state: Literal["LED_ON", "LED_OFF"]
    esp_epoch: Optional[int] = None  # optional timestamp from ESP32

@app.post("/events", status_code=204)
async def events(evt: LedEvent, request: Request, x_api_key: str = Header(None)):
    # Tiny auth for testing
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Bad API key")

    # Print ONLY the LED state, per your request
    # (You’ll still see server logs from Uvicorn around it)
    print(evt.state)
    return
