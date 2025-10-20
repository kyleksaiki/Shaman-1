# i2s_levels_final.py
# Teensy 4.1 + Adafruit SPH0645 I2S microphone
# Reads raw 24-bit I2S audio data in 32-bit frames (Little Endian),
# converts to signed 16-bit samples, and computes basic loudness metrics.
# Terminal example: mpremote connect COM9 run i2s_mic_button_test.py

"""
I2S microphone sampler and simple level meter (Teensy 4.1 + SPH0645)

Overview
--------
- Waits for a single active-LOW button press on D2.
- Captures 5 short I2S chunks from an SPH0645 mic at 44.1 kHz (32-bit words with
  24-bit valid data in the top bits).
- Converts each 24-bit sample to int16 (by shifting >> 8, with clipping).
- Computes three quick metrics per chunk:
    * avgAbs: average absolute amplitude
    * peak : maximum absolute amplitude
    * rms  : root-mean-square amplitude (int16 domain)
- Blinks the onboard LED (D13 on) while active, then turns it off and deinitializes I2S.

Notes
-----
- Byte order for unpacking is little-endian ("<I"), matching Teensy behavior.
- This script is for quick terminal-level feedback; it does not write to disk.
- Timing, chunk sizes, and loop counts are unchanged from the original.

Hardware
--------
- BUTTON_PIN: D2 (active-LOW)
- LED_PIN   : D13 (status LED)
- I2S pins  : BCLK=D21, WS/LRCLK=D20, SD/DOUT=D8, MCK=D23 (mic ignores MCK)
"""

from machine import Pin, I2S
import time
import struct
import array
import math

# ---------------------------------------------------------------------------
# Pin assignments (MicroPython pin names, not Arduino numbers)
# ---------------------------------------------------------------------------
BUTTON_PIN, LED_PIN = "D2", "D13"                 # Button (trigger) and onboard LED
BCLK_PIN, WS_PIN, SD_PIN, MCK_PIN = "D21", "D20", "D8", "D23"
# BCLK: Bit clock  | WS: Word select (LRCLK)
# SD: Data line (mic DOUT) | MCK: optional master clock (mic ignores it)

# ---------------------------------------------------------------------------
# Button & LED setup
# ---------------------------------------------------------------------------
btn = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)        # Active-LOW: pressed -> 0
led = Pin(LED_PIN, Pin.OUT)

print("Waiting for button press...")
while btn.value():                                # Wait until button pressed
    time.sleep_ms(20)
led.on()                                          # LED on while capturing/processing

# ---------------------------------------------------------------------------
# I2S peripheral setup
# ---------------------------------------------------------------------------
# mode=I2S.RX     → receive mode (audio input)
# bits=32         → 32-bit word size per sample (SPH0645 outputs 24-bit packed in 32)
# format=I2S.MONO → single channel (mic is mono)
# rate=44100      → 44.1 kHz sample rate
# ibuf=20000      → DMA buffer size (larger == fewer underruns)
i2s = I2S(
    1,
    sck=Pin(BCLK_PIN), ws=Pin(WS_PIN), sd=Pin(SD_PIN), mck=Pin(MCK_PIN),
    mode=I2S.RX, bits=32, format=I2S.MONO, rate=44100, ibuf=20000
)

# ---------------------------------------------------------------------------
# Allocate a data buffer for incoming audio frames
# 4096 bytes = 1024 samples (4 bytes per 32-bit frame)
# ---------------------------------------------------------------------------
buf = bytearray(4096)
mv = memoryview(buf)

# ---------------------------------------------------------------------------
# Helper: convert an unsigned 32-bit word to a signed 24-bit integer
# The SPH0645 places its valid 24-bit sample in the top 24 bits of the 32-bit frame.
# ---------------------------------------------------------------------------
def to_signed24(v: int) -> int:
    """
    Interpret the lower 24 bits of `v` as a signed two's-complement 24-bit integer.
    """
    v &= 0xFFFFFF                # Keep only 24 bits
    if v & 0x800000:             # Sign bit set?
        v -= 1 << 24             # Sign-extend into Python int
    return v

# ---------------------------------------------------------------------------
# Helper: calculate RMS (root-mean-square) for int16 array
# ---------------------------------------------------------------------------
def rms_int16(vals: array.array) -> int:
    """
    Compute the RMS value of a sequence of int16 samples.
    Returns an integer RMS for quick textual display.
    """
    acc = 0
    for x in vals:
        acc += x * x
    return int(math.sqrt(acc / len(vals))) if vals else 0

# ---------------------------------------------------------------------------
# Main loop: capture a few short chunks and print audio metrics
# Each chunk ~0.023 s of audio (1024 samples @ 44.1 kHz)
# ---------------------------------------------------------------------------
for k in range(5):
    n = i2s.readinto(mv)         # Fill buffer with audio data from mic
    if not n:
        print("Chunk %d: no data" % (k + 1))
        time.sleep_ms(150)
        continue

    # -----------------------------------------------------------------------
    # Parse 32-bit words as LITTLE-ENDIAN (correct byte order for Teensy)
    # -----------------------------------------------------------------------
    words = struct.unpack("<%dI" % (n // 4), mv[:n])

    # -----------------------------------------------------------------------
    # Convert each 24-bit signed sample to a 16-bit value
    # Scale 24-bit down to 16-bit by shifting >> 8 (with clipping).
    # -----------------------------------------------------------------------
    vals16 = array.array('h')     # 'h' = signed 16-bit
    append = vals16.append        # local binding for speed in the tight loop
    for w in words:
        s24 = to_signed24(w >> 8) # Drop the low 8 "don't care" bits
        s16 = s24 >> 8            # Scale from 24-bit to ~16-bit
        # Clip to valid int16 range
        if s16 < -32768:
            s16 = -32768
        elif s16 > 32767:
            s16 = 32767
        append(s16)

    # -----------------------------------------------------------------------
    # Compute average absolute value, peak amplitude, and RMS
    # Rough loudness indicators suitable for terminal display.
    # -----------------------------------------------------------------------
    peak = 0
    total_abs = 0
    for v in vals16:
        a = -v if v < 0 else v
        total_abs += a
        if a > peak:
            peak = a
    avgAbs = total_abs // len(vals16)
    rms = rms_int16(vals16)

    print(
        "Chunk %d: samples=%d  avgAbs=%d  peak=%d  rms=%d"
        % (k + 1, len(vals16), avgAbs, peak, rms)
    )
    time.sleep_ms(150)

# ---------------------------------------------------------------------------
# Clean up hardware resources
# ---------------------------------------------------------------------------
i2s.deinit()
led.off()
print("Done.")
