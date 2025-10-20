# record_on_button.py
# Teensy 4.1 + Adafruit SPH0645 (I2S mic)
# Press D2 (to GND) -> record N seconds to /sdcard/rec_YYYYMMDD_HHMMSS.wav, then exit.

"""
Single-press one-shot audio recorder for Teensy 4.1 using an SPH0645 I2S microphone.

Behavior
--------
1) On import/run, the script announces the SD mount contents and waits for a single
   active-LOW button press on D2.
2) When pressed, it records `SECONDS` of audio from the I2S microphone at 44.1 kHz,
   converts the SPH0645's 24-bit samples (carried in the upper 24 bits of a 32-bit
   frame) down to 16-bit PCM, and writes a timestamped WAV to /sdcard/.
3) The LED on D13 blinks during capture and turns off when done.
4) The script then exits with SystemExit(0) so tools like `mpremote run` return.

Notes
-----
- File writing is atomic: data is captured into a temporary file (*.tmp) and then
  renamed into place after the WAV sizes are patched.
- The WAV header is written up front with placeholder sizes and patched on completion.
- MCK is provided in the I2S constructor but the SPH0645 ignores it; leaving it in
  matches many working pinouts. A commented alternative shows how to omit it entirely.
- Do not modify constants or logic unless you intend to change functionality.

Hardware
--------
- BUTTON_PIN (D2): Active-LOW; press to start a single recording.
- LED_PIN    (D13): Status LED; blinks while recording.
- I2S pins: BCLK=D21, WS/LRCLK=D20, SD/DATA=D8, MCK=D23 (optional for mic).

Tested Environment
------------------
- MicroPython/Teensy 4.1 style I2S API (using `machine.I2S`).
"""

import os
import time
import struct
from machine import Pin, I2S

# ---------- Pins (match your working test) ----------
BUTTON_PIN, LED_PIN = "D2", "D13"
# MCK is optional for this mic; kept for consistency with working setups.
BCLK_PIN, WS_PIN, SD_PIN, MCK_PIN = "D21", "D20", "D8", "D23"

# ---------- Recording config ----------
RATE = 44100            # Sample rate in Hz
SECONDS = 20            # Recording duration in seconds (set to 60 for 1 minute)
CHANNELS = 1            # Mono (SPH0645 is mono)
BITS_OUT = 16           # WAV bit depth (we write 16-bit PCM)
MOUNT = "/sdcard"       # SD card mount path
READ_BYTES = 4096       # I2S read chunk size (bytes); must be multiple of 4 (32-bit words)
IBUF_BYTES = 20000      # I2S internal DMA buffer size (bytes)

# ---------- I/O ----------
btn = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)  # Active-LOW: pressed -> 0
led = Pin(LED_PIN, Pin.OUT)
led.off()

# ---------- Helpers ----------
def to_signed24(v: int) -> int:
    """
    Convert a raw value to signed 24-bit two's-complement.

    Parameters
    ----------
    v : int
        Input integer (mask will constrain to 24 bits).

    Returns
    -------
    int
        The same value interpreted as signed 24-bit.
    """
    v &= 0xFFFFFF
    if v & 0x800000:
        v -= 1 << 24
    return v


def wav_write_header(f, nchan: int, rate: int, bits: int, data_len: int) -> None:
    """
    Write a minimal PCM WAV header to an open file object.

    This function writes the RIFF/WAVE header and a 'fmt ' and 'data' chunk with the
    provided sizes. Data and RIFF sizes can be patched later if data_len is unknown.

    Parameters
    ----------
    f : io.BufferedWriter
        Open file (binary) positioned at start.
    nchan : int
        Number of channels (1 = mono).
    rate : int
        Sample rate in Hz.
    bits : int
        Bits per sample (we use 16).
    data_len : int
        Number of bytes of PCM data (0 if unknown; will be patched later).
    """
    byte_rate = rate * nchan * bits // 8
    block_align = nchan * bits // 8
    riff_size = 36 + data_len  # 4 + (8+16) + (8+data_len)

    f.write(b"RIFF")
    f.write(riff_size.to_bytes(4, "little"))
    f.write(b"WAVE")

    # 'fmt ' subchunk (PCM)
    f.write(b"fmt ")
    f.write((16).to_bytes(4, "little"))         # Subchunk1Size (16 for PCM)
    f.write((1).to_bytes(2, "little"))          # AudioFormat (1 = PCM)
    f.write(nchan.to_bytes(2, "little"))        # NumChannels
    f.write(rate.to_bytes(4, "little"))         # SampleRate
    f.write(byte_rate.to_bytes(4, "little"))    # ByteRate
    f.write(block_align.to_bytes(2, "little"))  # BlockAlign
    f.write(bits.to_bytes(2, "little"))         # BitsPerSample

    # 'data' subchunk header
    f.write(b"data")
    f.write(data_len.to_bytes(4, "little"))     # Subchunk2Size


def patch_wav_sizes(path: str, data_len: int) -> None:
    """
    Patch the WAV header sizes (RIFF and data chunk) after recording completes.

    Parameters
    ----------
    path : str
        Path to the WAV file to patch.
    data_len : int
        Actual number of data bytes written after the header.
    """
    with open(path, "r+b") as f:
        riff_size = 36 + data_len
        # RIFF size at offset 4, data size at offset 40
        f.seek(4)
        f.write(riff_size.to_bytes(4, "little"))
        f.seek(40)
        f.write(data_len.to_bytes(4, "little"))


def make_name() -> str:
    """
    Create a timestamped WAV filename on the SD card.

    Falls back to ticks-based stamp if RTC time is unavailable.

    Returns
    -------
    str
        Full path: /sdcard/rec_YYYYMMDD_HHMMSS.wav (or ticks fallback).
    """
    try:
        y, m, d, wd, h, mi, s, _ = time.localtime()
        stamp = "%04d%02d%02d_%02d%02d%02d" % (y, m, d, h, mi, s)
    except Exception:
        # Ticks fallback keeps uniqueness without requiring RTC
        stamp = "%08d" % (time.ticks_ms() & 0xFFFFFFFF)
    return "%s/rec_%s.wav" % (MOUNT, stamp)


def flash_toggle(last_ms: int, period: int = 100) -> int:
    """
    Toggle the LED if at least `period` milliseconds have elapsed.

    Parameters
    ----------
    last_ms : int
        Timestamp (ms) when the LED last toggled.
    period : int, optional
        Blink period in ms, by default 100.

    Returns
    -------
    int
        Possibly updated timestamp of the last toggle.
    """
    now = time.ticks_ms()
    if time.ticks_diff(now, last_ms) >= period:
        led.value(0 if led.value() else 1)
        return now
    return last_ms


# ---------- Recorder ----------
def record_once(seconds: int = SECONDS) -> None:
    """
    Perform a single recording session of the specified duration.

    Steps
    -----
    1) Ensure SD card mount is accessible.
    2) Configure I2S in RX (receive) mode to read 32-bit frames at 44.1 kHz.
    3) Create buffers and open a temporary output file.
    4) Write a placeholder WAV header (sizes patched after capture).
    5) Loop until duration elapses:
         - Blink LED periodically,
         - Read I2S DMA into a 32-bit buffer,
         - Convert each 24-bit sample (upper 24 bits of the 32-bit word)
           to clipped 16-bit PCM,
         - Append to file.
    6) Deinit I2S, patch sizes, and atomically rename temp -> final.

    Parameters
    ----------
    seconds : int, optional
        Recording length in seconds, by default SECONDS.
    """
    # 1) Ensure /sdcard exists and is mounted (raises if not).
    _ = os.listdir(MOUNT)

    # 2) Configure I2S — using your working signature (keywords + mck).
    i2s = I2S(
        1,
        sck=Pin(BCLK_PIN),
        ws=Pin(WS_PIN),
        sd=Pin(SD_PIN),
        mck=Pin(MCK_PIN),
        mode=I2S.RX,
        bits=32,               # Mic outputs 24 bits inside a 32-bit container
        format=I2S.MONO,
        rate=RATE,
        ibuf=IBUF_BYTES,
    )
    # If you prefer to drop MCK entirely, use this instead (same behavior for this mic):
    # i2s = I2S(
    #     1,
    #     sck=Pin(BCLK_PIN), ws=Pin(WS_PIN), sd=Pin(SD_PIN),
    #     mode=I2S.RX, bits=32, format=I2S.MONO, rate=RATE, ibuf=IBUF_BYTES
    # )

    # 3) Prepare filenames and buffers.
    final = make_name()
    tmp = final + ".tmp"

    in_buf = bytearray(READ_BYTES)        # Raw 32-bit frames from I2S
    mv_in = memoryview(in_buf)
    out_buf = bytearray(READ_BYTES // 2)  # 16-bit PCM (half the bytes of 32-bit input)
    mv_out = memoryview(out_buf)

    try:
        with open(tmp, "wb") as f:
            # 4) Write a placeholder WAV header (sizes get patched later).
            wav_write_header(f, CHANNELS, RATE, BITS_OUT, 0)
            data_bytes = 0

            # Prime DMA once to reduce initial underflow.
            _ = i2s.readinto(mv_in)

            # Timing for duration and LED blink.
            end_at = time.ticks_add(time.ticks_ms(), seconds * 1000)
            last_led = time.ticks_ms()
            led.on()
            print("Recording to:", final)

            # 5) Main capture loop.
            while time.ticks_diff(end_at, time.ticks_ms()) > 0:
                # Blink LED at 10 Hz to show liveness.
                last_led = flash_toggle(last_led, 100)

                # Read a chunk of 32-bit words into mv_in.
                n = i2s.readinto(mv_in)
                if not n:
                    # If DMA had no data yet, yield briefly and retry.
                    time.sleep_ms(1)
                    continue

                # Convert little-endian 32-bit words -> signed 16-bit PCM.
                # SPH0645 places the 24-bit sample in the top 24 bits; shift down 8,
                # interpret as signed 24, then downscale to ~16 bits with clipping.
                words = struct.unpack("<%dI" % (n // 4), mv_in[:n])

                out_i = 0
                for w in words:
                    s24 = to_signed24(w >> 8)   # keep signed 24 (upper bits)
                    s16 = s24 >> 8              # downscale to ~16-bit range
                    if s16 < -32768:
                        s16 = -32768
                    elif s16 > 32767:
                        s16 = 32767
                    struct.pack_into("<h", mv_out, out_i, s16)
                    out_i += 2  # 2 bytes per 16-bit sample

                # Write the converted PCM to disk.
                f.write(mv_out[:out_i])
                data_bytes += out_i

                # Micro-yield to keep system responsive.
                time.sleep_ms(0)

        led.off()

    finally:
        # 6a) Always release the I2S peripheral, even on exceptions.
        try:
            i2s.deinit()
        except Exception:
            pass

    # 6b) Patch header sizes and atomically move temp into place.
    patch_wav_sizes(tmp, data_bytes)
    time.sleep_ms(20)
    try:
        os.rename(tmp, final)
    except Exception:
        # If a same-named file exists (unlikely), replace it.
        try:
            os.remove(final)
        except Exception:
            pass
        os.rename(tmp, final)

    print("Saved:", final, "bytes:", data_bytes)


# ---------- One-shot main ----------
print("Waiting for button...")

# Debounced wait for a single active-LOW press:
# 1) Wait until button goes LOW,
# 2) Ensure it remained LOW for at least ~30 ms, then proceed.
while btn.value() != 0:
    time.sleep_ms(10)

t0 = time.ticks_ms()
while btn.value() == 0 and time.ticks_diff(time.ticks_ms(), t0) < 30:
    time.sleep_ms(5)

time.sleep(5)

# Record once and exit so mpremote returns promptly.
record_once(SECONDS)

# Exit so mpremote returns
raise SystemExit(0)
