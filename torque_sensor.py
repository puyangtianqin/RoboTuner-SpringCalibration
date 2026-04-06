from Phidget22.Phidget import *
from Phidget22.Devices.VoltageRatioInput import *
import time

# ------------------------------
# CONFIGURATION
# ------------------------------
CHANNEL = 0  # Only read channel 0
# CALIBRATION_FACTOR = 104186.695491727  # Convert voltage ratio → force
CALIBRATION_FACTOR = 98640.7377186547  # Convert voltage ratio → torque #getting values close to noah's setup
# CALIBRATION_FACTOR = 104775.208950319 #Manufacturing value - slightly higher than expected on noah's setup -- eg 5.83 vs 5.5 readings
DATA_RATE = 100  # Updates per second
# ------------------------------

# Create VoltageRatioInput object
bridge = VoltageRatioInput()
bridge.setChannel(CHANNEL)

# ------------------------------
# Handlers
# ------------------------------
OFFSET = None


def on_attach(self):
    print(f"Channel {self.getChannel()} attached.")


def on_voltage_ratio_change(self, voltageRatio):
    global OFFSET
    if OFFSET is None:
        OFFSET = voltageRatio
        print(f"Zero Captured: {OFFSET:.6f}")
    force = (voltageRatio - OFFSET) * CALIBRATION_FACTOR
    print(
        f"Channel {self.getChannel()}: Voltage Ratio={voltageRatio:.6f} → Torque={force:.2f} Nm"
    )


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
while OFFSET is None:
    time.sleep(0.01)

print("Starting live readings... (press Enter to stop)")

# ------------------------------
# RUN LOOP
# ------------------------------
try:
    input()
finally:
    bridge.close()
