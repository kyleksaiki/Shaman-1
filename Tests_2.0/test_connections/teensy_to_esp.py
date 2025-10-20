# teensy_to_esp.py
from machine import Pin, UART
import time

# UART1 on Teensy 4.1 uses D1 (TX) / D0 (RX)
u = UART(1, 115200)

# Button wiring: D2 -> button -> GND (uses internal pull-up)
button = Pin("D2", Pin.IN, Pin.PULL_UP)

toggled = False
last_state = 1
last_change = time.ticks_ms()
DEBOUNCE_MS = 120  # adjust if needed

print("Teensy ready (UART1 D1/D0, button D2)")

while True:
    s = button.value()
    now = time.ticks_ms()

    # Edge detect with debounce
    if s != last_state and time.ticks_diff(now, last_change) > DEBOUNCE_MS:
        last_change = now
        if s == 0:  # on PRESS
            toggled = not toggled
            msg = b"LED_ON\n" if toggled else b"LED_OFF\n"
            u.write(msg)
            print("Sent:", msg.strip())

    last_state = s
    time.sleep(0.005)
