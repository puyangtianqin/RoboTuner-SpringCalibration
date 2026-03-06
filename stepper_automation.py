# cd Documents
# python3 stepper_automation.py

from time import sleep
import RPi.GPIO as GPIO

# Direction pin from controller
DIR = 7
# Step pin from controller
STEP = 16
# 0/1 used to signify clockwise or counterclockwise.
CW = 1
CCW = 0

# Setup pin layout on PI
GPIO.setmode(GPIO.BOARD)

# Establish Pins in software
GPIO.setup(DIR, GPIO.OUT)
GPIO.setup(STEP, GPIO.OUT)

# Set the first direction you want it to spin
GPIO.output(DIR, CW)

# Define the calibration step index, each contains 100 steps of the stepper
step_idx = 0

try:
	# Run forever.
	while step_idx <= 50:

		sleep(1.0)
		# Esablish the direction you want to go
		GPIO.output(DIR, CW)

		# Run for 200 steps. This will change based on how you set you controller
		for x in range(100):

			# Set one coil winding to high
			GPIO.output(STEP, GPIO.HIGH)
			# Allow it to get there.
			sleep(0.005)  # Dictates how fast stepper motor will run
			# Set coil winding to low
			GPIO.output(STEP, GPIO.LOW)
			sleep(0.005)  # Dictates how fast stepper motor will run

	# Sleep for 5 second before the next step of calibration
	sleep(1.0)

	# Increment the Calibration Step Index
	step_idx += 1

# Once finished clean everything up
except KeyboardInterrupt:
	print("cleanup")
	GPIO.cleanup()
