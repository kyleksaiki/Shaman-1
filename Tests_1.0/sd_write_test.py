# sd_write_test_confirm2.py
# Simple, atomic write/read confirmation on /sdcard using a temp file rename.

"""
SD Card Write/Read Confirmation (Atomic Rename)

What this script does
---------------------
1) Verifies that the SD card mount exists and lists its contents.
2) Writes a small payload to a temporary file (TARGET.tmp) and closes it.
3) Stats the temp file (for visibility), then atomically renames it to TARGET.
4) Briefly yields (sleep) to let the filesystem settle.
5) Re-opens TARGET, reads the contents, and verifies it matches the original data.
6) Prints PASS/FAIL and exits with an explicit SystemExit code:
     - 0 = PASS
     - 1 = SD mount missing
     - 2 = rename failed (cleanup attempted)
     - 3 = readback mismatch

Why use a temp -> rename?
-------------------------
Atomic replacement helps avoid partial/tearing writes. The final file only appears
in its complete form after the rename succeeds.

Environment
-----------
- Intended for MicroPython environments (e.g., Teensy 4.1) where `/sdcard` is mounted.
"""

import os
import sys
import time

# ---------- Configuration ----------
MOUNT = "/sdcard"
TARGET = MOUNT + "/test.txt"
TEMP = TARGET + ".tmp"
DATA = b"Hello SD Card!"  # Arbitrary test payload


def log(*a):
    """
    Print a message and attempt to flush stdout.

    Using a helper avoids repetitive try/except around flush on some targets.
    """
    print(*a)
    try:
        sys.stdout.flush()
    except Exception:
        # Some environments may not support flush; ignore quietly.
        pass


log("--- SD Card Write/Read Confirm  ---")

# ---------- Step 0: Confirm mount ----------
try:
    log("Mount OK; contents:", os.listdir(MOUNT))
except Exception as e:
    log("FATAL: mount missing:", e)
    raise SystemExit(1)

# ---------- Step 1: Write to TEMP and close ----------
log("\nStep 1: write temp:", TEMP)
with open(TEMP, "wb") as f:
    n = f.write(DATA)
log("  wrote bytes:", n)

# ---------- Step 2: Stat TEMP and atomically replace TARGET ----------
try:
    # Some ports return a tuple; index 6 is file size in many MicroPython builds.
    log("  temp size:", os.stat(TEMP)[6])
except Exception as e:
    # Non-fatal: just informative if stat fails on this platform.
    log("  stat(temp) fail:", e)

try:
    os.rename(TEMP, TARGET)
    log("  renamed temp ->", TARGET)
except Exception as e:
    log("  rename fail:", e)
    # Best-effort cleanup of TEMP; ignore further errors.
    try:
        os.remove(TEMP)
    except Exception:
        pass
    raise SystemExit(2)

# Tiny settle before reopening same file (helps on some FS/SD stacks)
time.sleep_ms(50)

# ---------- Step 3: Read back and compare ----------
log("\nStep 3: read back:", TARGET)
with open(TARGET, "rb") as r:
    got = r.read()
match = (got == DATA)
log("  read OK, matches:", match)

# ---------- Step 4: Final status and exit explicitly ----------
if match:
    log("\nPASS")
    raise SystemExit(0)
else:
    log("\nFAIL")
    raise SystemExit(3)
