# button_led_flash_test.py
# Teensy 4.1 + MicroPython
# Press the button on D2 → onboard LED (D13) flashes for 10 seconds.

"""
Button-Triggered LED Flash Test – Teensy 4.1 (MicroPython)

Overview
--------
This script demonstrates digital input (button) and output (LED) control.
When the button connected to D2 (wired to GND) is pressed, the onboard LED
(D13) flashes at 5 Hz (0.2-second interval) for 10 seconds. After flashing,
the LED turns off, and the system waits for the next button press.

Hardware Setup
--------------
- Button between D2 and GND (internal pull-up enabled).
  * Released → reads HIGH (1)
  * Pressed  → reads LOW  (0)
- LED on D13 (Teensy onboard LED).

Behavior
--------
1. Wait for button press (LOW).
2. When pressed, flash LED for 10 seconds (0.2s period).
3. Turn LED off and wait for button release.
4. Return to waiting for next press (loop forever).

Usage
-----
    mpremote connect COM9 run button_led_flash_test.py
"""

from machine import Pin
import time

# ---------------------------------------------------------------------------
# Pin setup
# ---------------------------------------------------------------------------
BUTTON_PIN = "D2"    # Pushbutton pin (active LOW)
LED_PIN = "D13"      # Onboard LED pin

# Configure LED output and button input with pull-up
led = Pin(LED_PIN, Pin.OUT)
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)

print("Press the button to make the LED flash for 10 seconds...")

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
while True:
    # Wait for button press (active LOW)
    if button.value() == 0:
        print("Button pressed! Flashing LED...")
        start_time = time.ticks_ms()

        # Flash LED for 10 seconds total
        while time.ticks_diff(time.ticks_ms(), start_time) < 10000:
            led.toggle()       # invert LED state each cycle
            time.sleep(0.2)    # blink every 0.2 seconds (5 Hz)

        # Ensure LED is off after flashing
        led.off()
        print("Done flashing. Waiting for next press...")

        # Wait for button release before restarting loop
        while button.value() == 0:
            time.sleep_ms(20)
