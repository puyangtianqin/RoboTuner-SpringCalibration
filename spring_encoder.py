import RPi.GPIO as GPIO
import time
import math

# --- CONFIGURATION ---
CLK_PIN  = 23
MISO_PIN = 21
CS_PIN   = 24  # "MOSI" wire acting as Chip Select

# Filter Settings
ALPHA = 0.1  # Smoothing factor (0.0 - 1.0)

# --- SETUP GPIO ---
GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)
GPIO.setup(CLK_PIN, GPIO.OUT)
GPIO.setup(CS_PIN, GPIO.OUT)
GPIO.setup(MISO_PIN, GPIO.IN)

# Idle State
GPIO.output(CS_PIN, GPIO.HIGH) 
GPIO.output(CLK_PIN, GPIO.HIGH)

def read_sensor_raw():
    """Reads 24 bits via Bit-Banging"""
    raw_val = 0
    
    # 1. Wake up Sensor
    GPIO.output(CS_PIN, GPIO.LOW)
    time.sleep(0.000005) # Wait for sensor to wake up

    # 2. Read 24 bits
    for _ in range(24):
        GPIO.output(CLK_PIN, GPIO.LOW) # Clock Low
        bit = GPIO.input(MISO_PIN)     # Read Bit
        raw_val = (raw_val << 1) | bit # Shift in
        GPIO.output(CLK_PIN, GPIO.HIGH)# Clock High

    # 3. End Transaction
    GPIO.output(CS_PIN, GPIO.HIGH)
    return raw_val

# --- MAIN LOOP ---
data_filtered = 0.0
print("Reading 18-bit Sensor... (Press Ctrl+C to stop)")

try:
    while True:
        # 1. Get the full 24-bit container
        full_reading = read_sensor_raw()

        # --- THE FIX ---
        # Data is the top 18 bits. We shift RIGHT by 6 to delete the status bits.
        # Then we use 0x3FFFF (which is 18 ones) to keep the data clean.
        raw_data = (full_reading >> 6) & 0x3FFFF 
        
        # Status is the bottom 6 bits.
        status   = full_reading & 0x3F 

        # 2. Filter the data
        data_filtered = (ALPHA * raw_data) + ((1.0 - ALPHA) * data_filtered)

        # 3. Check Status Bits
        # Let's print the binary status so you can see if errors pop up.
        # Usually, 000000 means "All Good".
        status_bin = format(status, '06b')
        
        # Print Result
        # We cast filtered to int() to make it readable
        print(f"Raw: {raw_data} \tFiltered: {int(data_filtered)}")

        # Loop delay (adjust this to make it faster/slower)
        time.sleep(0.05)

except KeyboardInterrupt:
    print("\nStopping...")
    GPIO.cleanup()
