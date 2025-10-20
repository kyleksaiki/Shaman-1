# teensy_to_esp.py
# -----------------------------------------------------------------------------
# Teensy 4.1 + Adafruit SPH0645 (I2S) running MicroPython
# Detects sound events and sends **one** ASCII line to the ESP32 on event end:
#
#   NOISE <duration_ms> <peak_dbfs>\n
#
# ESP32 then forwards this to your API with device_id/timing.
#
# Wiring (3.3V logic, common GND):
#   Teensy TX1 (D1) -> ESP32 RX2 (GPIO16 or your RX_GPIO)
#   Teensy RX1 (D0) <- ESP32 TX2 (GPIO17 or your TX_GPIO)  [optional]
#   GND <-> GND
#
# Usage:
#   mpremote connect COM9 run teensy_to_esp.py
#
# Notes:
# - Plain ASCII prints (Windows-friendly).
# - EXIT threshold is clamped so the event ends promptly.
# - Recalibrate with button on D2.
# -----------------------------------------------------------------------------

from machine import Pin, I2S, UART
import time, struct, array, math

# ---- Pins / I2S -------------------------------------------------------------
LED_PIN = "D13"
BTN_PIN = "D2"
BCLK_PIN, WS_PIN, SD_PIN, MCK_PIN = "D21", "D20", "D8", "D23"

# ---- I2S framing ------------------------------------------------------------
RATE = 44100
BITS_PER_WORD = 32
CHUNK_BYTES = 4096              # 1024 samples/chunk
IBUF_BYTES = 20000

# ---- Detection tuning -------------------------------------------------------
CALIBRATION_S = 5.0             # baseline capture time
MIN_DURATION_S = 1.0            # must sustain >= this to trigger
MIN_RMS = 600                   # absolute floor on thresholds

# Enter/Exit thresholds (data-driven + hysteresis)
MULTIPLIER = 1.20               # ENTER candidate: mean * 1.2
K_SIGMA = 4.0                   # ENTER candidate: mean + 4σ
EXIT_RATIO = 0.85               # EXIT <= ENTER * ratio
EXIT_K_SIGMA_MIN = 1.0          # clamp EXIT >= mean + 1σ (prevents "stuck in event")

# Filtering & end debounce
SMOOTHING_ALPHA = 0.25          # EMA smoothing for detector
END_DEBOUNCE_MS = 200           # must stay below EXIT for this long to end

# UX helpers
EVENT_HEARTBEAT_MS = 1000       # '.' each second while in event (0 to disable)
MAX_EVENT_S = 6.0               # safety timeout to force end (0 to disable)

# ---- Helpers ----------------------------------------------------------------
def to_signed24(v: int) -> int:
    v &= 0xFFFFFF
    if v & 0x800000: v -= 1 << 24
    return v

def rms_int16(vals: array.array) -> int:
    if not vals: return 0
    acc = 0
    for x in vals: acc += x * x
    return int(math.sqrt(acc / len(vals)))

def dbfs(rms: int) -> float:
    return 20.0 * math.log10(max(rms,1)/32768.0)

def read_chunk(i2s, mv):
    """Read one I2S chunk and return RMS(int16)."""
    n = i2s.readinto(mv)
    if not n: return 0
    words = struct.unpack("<%dI" % (n // 4), mv[:n])
    vals16 = array.array('h')
    ap = vals16.append
    for w in words:
        s24 = to_signed24(w >> 8)   # valid top 24 bits
        s16 = s24 >> 8              # scale to int16-ish
        if s16 < -32768: s16 = -32768
        elif s16 > 32767: s16 = 32767
        ap(s16)
    return rms_int16(vals16)

def safe_print(s):
    try: print(s)
    except Exception: print(str(s))

# ---- Hardware init ----------------------------------------------------------
led = Pin(LED_PIN, Pin.OUT); led.off()
btn = Pin(BTN_PIN, Pin.IN, Pin.PULL_UP)

i2s = I2S(1,
          sck=Pin(BCLK_PIN), ws=Pin(WS_PIN), sd=Pin(SD_PIN), mck=Pin(MCK_PIN),
          mode=I2S.RX, bits=BITS_PER_WORD, format=I2S.MONO, rate=RATE, ibuf=IBUF_BYTES)

buf = bytearray(CHUNK_BYTES); mv = memoryview(buf)
SAMPLES_PER_CHUNK = CHUNK_BYTES // 4
CHUNK_MS = int(1000 * (SAMPLES_PER_CHUNK / RATE))  # ~23 ms

# Teensy 4.1 UART1 is fixed to D1 (TX), D0 (RX) on this port
uart = UART(1, 115200)

# ---- Calibration ------------------------------------------------------------
def calibrate():
    """Measure quiet-room mean/std and compute ENTER/EXIT thresholds."""
    safe_print("Calibrating quiet-room baseline (%.1f s)..." % CALIBRATION_S)
    led.on()

    n_chunks = max(1, int((CALIBRATION_S * 1000) // CHUNK_MS))
    rms_vals = array.array('H')
    t_end = time.ticks_add(time.ticks_ms(), int(CALIBRATION_S*1000))
    while time.ticks_diff(t_end, time.ticks_ms()) > 0 and len(rms_vals) < n_chunks:
        r = read_chunk(i2s, mv)
        if r: rms_vals.append(r)

    if len(rms_vals) == 0:
        mean = 0; std = 0
    else:
        m = sum(rms_vals) / len(rms_vals)
        var = 0.0
        for r in rms_vals:
            d = r - m; var += d*d
        var /= max(1, len(rms_vals)-1)
        mean = int(m); std = int(math.sqrt(var))

    enter1 = int(mean * MULTIPLIER)
    enter2 = int(mean + K_SIGMA * std)
    ENTER_TH = max(MIN_RMS, enter1, enter2)

    exit_by_ratio = int(ENTER_TH * EXIT_RATIO)
    exit_by_sigma = int(mean + EXIT_K_SIGMA_MIN * std)
    EXIT_TH = max(MIN_RMS, exit_by_ratio, exit_by_sigma)

    safe_print("Baseline mean RMS = %d std = %d" % (mean, std))
    safe_print("Enter TH = %d Exit TH = %d" % (ENTER_TH, EXIT_TH))
    led.off()
    return ENTER_TH, EXIT_TH

ENTER_TH, EXIT_TH = calibrate()
safe_print("Listening...")

# ---- Main loop --------------------------------------------------------------
smooth = 0
in_event = False
event_peak_rms = 0
event_start_ms = None
below_exit_ms = 0
last_heartbeat = time.ticks_ms()
above_ms = 0

def heartbeat():
    if EVENT_HEARTBEAT_MS <= 0: return
    try: print(".", end="")
    except TypeError: print(".")

def send_event_to_esp(duration_ms, peak_db):
    """Emit one line for the ESP32 to parse and forward."""
    line = "NOISE %d %.2f\n" % (int(duration_ms), float(peak_db))
    try: uart.write(line)
    except Exception as e: safe_print("UART write failed: %r" % (e,))

try:
    while True:
        # Recalibrate on button press (active LOW)
        if not btn.value():
            safe_print("(Recalibrate)")
            ENTER_TH, EXIT_TH = calibrate()
            smooth = 0; in_event = False
            event_peak_rms = 0; event_start_ms = None
            below_exit_ms = 0; last_heartbeat = time.ticks_ms(); above_ms = 0

        r = read_chunk(i2s, mv)
        if r == 0:
            time.sleep_ms(5)
            continue

        # EMA smoothing
        smooth = int(SMOOTHING_ALPHA*r + (1.0-SMOOTHING_ALPHA)*smooth)
        now = time.ticks_ms()

        # Enter event: require sustained above ENTER_TH
        if not in_event:
            if smooth >= ENTER_TH:
                above_ms += CHUNK_MS
            else:
                above_ms = 0

            if above_ms >= int(MIN_DURATION_S*1000):
                in_event = True
                led.on()
                event_start_ms = now
                event_peak_rms = smooth
                below_exit_ms = 0
                safe_print(">>> SOUND DETECTED (>= %.1f s). ENTER=%d, EXIT=%d" % (MIN_DURATION_S, ENTER_TH, EXIT_TH))

        # Inside event: track peak, check for end
        else:
            if smooth > event_peak_rms:
                event_peak_rms = smooth

            if EVENT_HEARTBEAT_MS > 0 and time.ticks_diff(now, last_heartbeat) >= EVENT_HEARTBEAT_MS:
                heartbeat(); last_heartbeat = now

            if smooth < EXIT_TH:
                below_exit_ms += CHUNK_MS
            else:
                below_exit_ms = 0

            # Natural end (fast, debounced)
            if below_exit_ms >= END_DEBOUNCE_MS:
                in_event = False
                led.off()
                dur_ms = time.ticks_diff(now, event_start_ms) if event_start_ms is not None else 0
                peak_db = dbfs(event_peak_rms)
                safe_print("\n<<< SOUND ENDED. duration=%.3f s, peak=%.2f dBFS" % (dur_ms/1000.0, peak_db))
                safe_print("(re-armed)")
                send_event_to_esp(dur_ms, peak_db)
                event_peak_rms = 0; event_start_ms = None; below_exit_ms = 0; above_ms = 0
                continue

            # Safety timeout (prevents getting stuck in very loud rooms)
            if MAX_EVENT_S > 0 and time.ticks_diff(now, event_start_ms) >= int(MAX_EVENT_S*1000):
                in_event = False
                led.off()
                dur_ms = time.ticks_diff(now, event_start_ms)
                peak_db = dbfs(event_peak_rms)
                safe_print("\n<<< SOUND ENDED (timeout). duration=%.3f s, peak=%.2f dBFS" % (dur_ms/1000.0, peak_db))
                safe_print("(re-armed)")
                send_event_to_esp(dur_ms, peak_db)
                event_peak_rms = 0; event_start_ms = None; below_exit_ms = 0; above_ms = 0

except KeyboardInterrupt:
    safe_print("\nStopping...")
finally:
    i2s.deinit(); led.off()
    safe_print("Done.")
