# RoboTuner Spring Calibration

Public repository: https://github.com/puyangtianqin/RoboTuner-SpringCalibration

This directory contains the Python software used to control, monitor, log, and analyze the RoboTuner spring calibration setup. The project has evolved from low-level Raspberry Pi, stepper motor, torque sensor, and encoder tests into a GUI-based calibration controller with closed-loop torque control and a separate analysis viewer for exported CSV data.

Current local directory:

```text
c:\Users\puyan\Box\MINIMAX Lab\Undergraduate Resources\2_Student Work\1_Undergraduate\Tianqin Puyang\Senior Design\RoboTuner-SpringCalibration
```

## Main Files

- `main_adaptive_ff_trim.py` - primary calibration GUI. It integrates Raspberry Pi GPIO stepper control, Phidget torque feedback, spring encoder reading, manual actuation, open-loop automation, adaptive feed-forward plus trim closed-loop torque control, step-counter memory, torque-limit protection, and CSV logging.
- `main_adaptive_ff_trim_zero_check.py` - extended controller variant based on the primary GUI. It adds zero-torque confirmation and spring engagement routines for checking whether the spring is unloaded or engaged before calibration.
- `plot.py` - PyQt5 and Matplotlib result analyzer for the newer GUI CSV files in `Results/`.
- `GUI_Test.py` - GUI development and simulation-oriented script used while building the controller interface and closed-loop workflow.
- `.gitignore` - ignores generated Python cache files such as `__pycache__/` and `*.pyc`.

## Folders

- `Results/` - exported data from calibration runs.
  - `RoboTuners_Test_*.csv` files are produced by the current GUI logging workflow.
  - `torque_deflection_*.csv` files are earlier sweep logs with an older column format.
  - `step_counter_memory.csv` stores the saved step-counter history used by the GUI.
- `Unit_Tests/` - standalone hardware validation scripts:
  - `stepper_test.py` - basic stepper motor direction and pulse test.
  - `stepper_automation.py` - repeated open-loop stepper motion test.
  - `spring_encoder.py` - raw spring encoder readout and filtering test.
  - `torque_sensor.py` - Phidget torque sensor readout and tare test.
- `Past_Versions/` - archived versions of earlier main scripts kept for traceability.
- `.claude/` - local assistant/tooling metadata, not required to operate the RoboTuner software.

## Hardware Dependencies

Full operation requires the RoboTuner hardware setup:

- Raspberry Pi with GPIO access.
- Stepper motor driver connected to the configured direction and step pins.
- Phidget bridge/ADC connected to the reaction torque sensor.
- Spring deflection encoder connected to the configured GPIO pins.
- Python packages used by the GUI and analyzer, including `PyQt5`, `Phidget22`, `numpy`, `pandas`, and `matplotlib`.

The main scripts include fallback behavior for missing Raspberry Pi GPIO imports so that syntax checks and limited GUI development can be performed on a non-Pi computer. Real motor movement, torque readings, and encoder readings require the hardware.

## Running the Main Controller

Run the primary calibration GUI with:

```powershell
python main_adaptive_ff_trim.py
```

Run the zero-check/engagement variant with:

```powershell
python main_adaptive_ff_trim_zero_check.py
```

New CSV exports are written to:

```text
Results/
```

The GUI logs time, serial number, meaningful-logging flag, voltage ratio, torque, encoder readings, encoder angle, step counter, closed-loop state, and closed-loop target torque.

## Plotting Data

Launch the analyzer with:

```powershell
python plot.py
```

The analyzer is intended for current GUI CSV files that contain at least these columns:

```text
time_s, encoder_raw, torque_mnm
```

It also uses `meaningful_logging` when available to choose a default reference window. The older `torque_deflection_*.csv` files are preserved for historical data review, but they use a different schema and are not the main target of `plot.py`.

In the analyzer GUI, the user can:

- Select a CSV file from `Results/`.
- Set an analysis time window.
- Set a reference encoder window.
- Compute `ref_encoder` from the selected reference window.
- View delta encoder, torque, delta-encoder-to-torque ratio, and torque-versus-deflection plots.

## Verification Before Submission

The following syntax checks passed on April 28, 2026:

```powershell
python -m py_compile "main_adaptive_ff_trim.py"
python -m py_compile "main_adaptive_ff_trim_zero_check.py"
python -m py_compile "GUI_Test.py"
python -m py_compile "plot.py"
python -m py_compile "Unit_Tests\stepper_test.py" "Unit_Tests\stepper_automation.py" "Unit_Tests\spring_encoder.py" "Unit_Tests\torque_sensor.py"
```

Functional hardware validation still requires running the controller on the Raspberry Pi with the stepper motor driver, torque sensor, and encoder connected.
