# button_test.py
# Simple MicroPython test for a pushbutton on a Teensy 4.1 (or similar board)
# Reads a pushbutton on D2 for 5 seconds and prints its state to the terminal.
# Example usage:
#   mpremote connect COM9 run button_test.py

"""
Button Test – Teensy 4.1 (MicroPython)

Overview
--------
This simple script confirms that a pushbutton connected to D2 (to GND) works
as expected. It reads the pin for 5 seconds, printing whether the button
is "pressed" or "released" every 250 ms.

Hardware Setup
--------------
- Button wired between D2 and GND.
- Internal pull-up resistor enabled on D2.
  * Pin reads HIGH (1) when released.
  * Pin reads LOW  (0) when pressed.

Expected Output
---------------
Terminal will show alternating:
    pressed
    released
depending on your button actions during the 5-second test.
"""

import machine
import time

# ---------------------------------------------------------------------------
# Configure the input pin
# ---------------------------------------------------------------------------
# "D2" corresponds to Teensy's digital pin 2 in MicroPython naming.
# Enable the internal pull-up so the pin defaults HIGH (released).
btn = machine.Pin("D2", machine.Pin.IN, machine.Pin.PULL_UP)

# ---------------------------------------------------------------------------
# Main loop: monitor the button for 5 seconds
# ---------------------------------------------------------------------------
print("Press/release the button for 5 seconds...")

t_start = time.ticks_ms()  # capture start time in milliseconds

# Run for approximately 5000 ms (5 seconds)
while time.ticks_diff(time.ticks_ms(), t_start) < 5000:
    # Read the button pin: 0 = pressed, 1 = released
    state = "pressed" if btn.value() == 0 else "released"

    # Print the current state
    print(state)

    # Delay to make output human-readable (4 updates/sec)
    time.sleep(0.25)

# ---------------------------------------------------------------------------
# End of test
# ---------------------------------------------------------------------------
print("Test complete. Button input verified.")
