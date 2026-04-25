# RoboTuner Spring Calibration

This directory contains Python scripts for running and analyzing the RoboTuner spring calibration setup. The main workflow is to run the active control GUI, collect torque/encoder data into CSV files, and then plot selected result files.

## Main Files

- `main_adaptive_ff_trim.py` - current main control script for the RoboTuner calibration GUI (PyQt5, with adaptive feed-forward trim and Phidget torque / Raspberry Pi stepper integration).
- `GUI_Test.py` - GUI test/development script.
- `plot.py` - interactive PyQt5 plotting GUI for CSV data stored in `Results/`.
- `.gitignore` - ignores Python cache files such as `__pycache__/` and `*.pyc`.

## Folders

- `Results/` - exported CSV files from calibration runs (`RoboTuners_Test_*.csv` from the active control GUI, `torque_deflection_*.csv` from earlier sweeps).
- `Past_Versions/` - archived versions of older main scripts (`main.py`, dated backups).
- `Unit_Tests/` - smaller test/helper scripts for sensors, stepper motion, and automation (`spring_encoder.py`, `stepper_test.py`, `stepper_automation.py`, `torque_sensor.py`).

## Running the Main Script

Run the active calibration GUI with:

```powershell
python main_adaptive_ff_trim.py
```

New CSV exports are written to:

```text
Results/
```

## Plotting Data

`plot.py` opens an interactive PyQt5 viewer for any CSV in `Results/`. Launch it with:

```powershell
python plot.py
```

Then use the GUI to:

- Pick a CSV from the **CSV file** dropdown (auto-populated from `Results/*.csv`).
- Adjust the **Analysis** window (start/end seconds) via the spin boxes or range slider on the *Reference Selection* tab.
- Adjust the **Reference** window — used to compute `ref_encoder` (mean of `encoder_raw` over the window) for the delta-encoder calculation. Click **Default Ref** to snap to the first `DEFAULT_REF_WINDOW_S` seconds of meaningful logging.
- Switch to the **Analysis Plots** tab for delta-encoder, torque, ratio, and torque-vs-delta-encoder views.

Plots auto-refresh on a timer (`AUTO_REFRESH_INTERVAL_MS`, default 1 s) when controls or the selected file change. Expected CSV columns: `time_s`, `encoder_raw`, `torque_mnm`, and optionally `meaningful_logging`.

## Notes

Some scripts depend on hardware-specific libraries and devices, including Raspberry Pi GPIO and Phidget torque sensor hardware. Syntax checks can be run on a development machine, but full operation requires the calibration hardware setup.
