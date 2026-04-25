# RoboTuner Spring Calibration

This directory contains Python scripts for running and analyzing the RoboTuner spring calibration setup. The main workflow is to run the active control GUI, collect torque/encoder data into CSV files, and then plot selected result files.

## Main Files

- `main_adaptive_ff_trim.py` - current main control script for the RoboTuner calibration GUI.
- `GUI_Test.py` - GUI test/development script.
- `plot.py` - plotting script for CSV data stored in `Results/`.
- `.gitignore` - ignores Python cache files such as `__pycache__/` and `*.pyc`.

## Folders

- `Results/` - exported CSV files from calibration runs.
- `Past_Versions/` - archived versions of older main scripts.
- `Unit_Tests/` - smaller test/helper scripts for sensors, stepper motion, and automation.

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

`plot.py` currently loads a specific CSV file from `Results/`. To plot a different run, edit the filename in:

```python
file_path = RESULTS_DIR / "RoboTuners_Test_20260420_160532.csv"
```

Then run:

```powershell
python plot.py
```

## Notes

Some scripts depend on hardware-specific libraries and devices, including Raspberry Pi GPIO and Phidget torque sensor hardware. Syntax checks can be run on a development machine, but full operation requires the calibration hardware setup.
