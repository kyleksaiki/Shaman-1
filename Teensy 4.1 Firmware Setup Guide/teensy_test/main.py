from machine import Pin
import time

# onboard LED is mapped as "LED"
led = Pin("LED", Pin.OUT)

print("Starting 10-second blink test now...")

# Blink for 10 seconds (0.5s on, 0.5s off → 20 blinks)
for i in range(20):
    led.toggle()
    time.sleep(0.5)

# Ensure LED ends off
led.off()
print("Blinking finished.")
