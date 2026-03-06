from Phidget22.Phidget import *
from Phidget22.Devices.VoltageRatioInput import *
import time

# ------------------------------
# CONFIGURATION
# ------------------------------
CHANNEL = 0                       # Only read channel 0
CALIBRATION_FACTOR = 100000       # Convert voltage ratio → force
DATA_RATE = 100                   # Updates per second
# ------------------------------

# Create VoltageRatioInput object
bridge = VoltageRatioInput()
bridge.setChannel(CHANNEL)

# ------------------------------
# Handlers
# ------------------------------
tare_offset = None

def on_attach(self):
    print(f"Channel {self.getChannel()} attached.")

def on_voltage_ratio_change(self, voltageRatio):
    global tare_offset
    if tare_offset is None:
        tare_offset = voltageRatio
        print(f"Tare complete: {tare_offset:.6f}")
    force = (voltageRatio - tare_offset) * CALIBRATION_FACTOR
    print(f"Channel {self.getChannel()}: Voltage Ratio={voltageRatio:.6f} → Force={force:.2f} N")

bridge.setOnAttachHandler(on_attach)
bridge.setOnVoltageRatioChangeHandler(on_voltage_ratio_change)

# ------------------------------
# OPEN AND WAIT FOR ATTACHMENT FIRST
# ------------------------------
bridge.openWaitForAttachment(5000)  # Wait up to 5 seconds for USB device

# ------------------------------
# NOW configure the data rate
# ------------------------------
bridge.setDataRate(DATA_RATE)

print("Waiting for first valid reading for tare...")

# ------------------------------
# WAIT for the first reading
# ------------------------------
while tare_offset is None:
    time.sleep(0.01)

print("Starting live readings... (press Enter to stop)")

# ------------------------------
# RUN LOOP
# ------------------------------
try:
    input()
finally:
    bridge.close()

