import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

# Load data
RESULTS_DIR = Path(__file__).resolve().parent / "Results"
file_path = RESULTS_DIR / "RoboTuners_Test_20260420_160532.csv"
df = pd.read_csv(file_path)

# --- Truncate to 125 seconds ---
df = df[(df['time_s'] <= 125) & (df['time_s'] >= 50)]

# Columns
time = df['time_s']
encoder_raw = df['encoder_raw']
torque = df['torque_mnm']

# --- Δ(deflection) relative to initial value ---
delta_encoder = encoder_raw - encoder_raw.iloc[0]

# --- Ratio ---
ratio = delta_encoder / torque.replace(0, np.nan)

# -------------------------------
# Create subplot grid (2 rows x 3 cols)
# -------------------------------
plt.figure(figsize=(14, 8))

# 1. Δencoder / torque vs time
plt.subplot(2, 3, 1)
plt.plot(time, ratio)
plt.title("ΔEncoder / Torque vs Time")
plt.xlabel("Time (s)")
plt.ylabel("ΔEncoder / Torque")
plt.grid()

# 2. Encoder_raw vs Torque
plt.subplot(2, 3, 2)
plt.scatter(torque, encoder_raw)
plt.title("Encoder Raw vs Torque")
plt.xlabel("Torque (mNm)")
plt.ylabel("Encoder Raw")
plt.grid()

# 3. ΔEncoder vs Torque
plt.subplot(2, 3, 3)
plt.scatter(torque, delta_encoder)
plt.title("ΔEncoder vs Torque")
plt.xlabel("Torque (mNm)")
plt.ylabel("ΔEncoder")
plt.grid()

# 4. Encoder_raw vs Time
plt.subplot(2, 3, 4)
plt.plot(time, encoder_raw)
plt.title("Encoder Raw vs Time")
plt.xlabel("Time (s)")
plt.ylabel("Encoder Raw")
plt.grid()

# 5. Torque vs Time  ✅ NEW
plt.subplot(2, 3, 5)
plt.plot(time, torque)
plt.title("Torque vs Time")
plt.xlabel("Time (s)")
plt.ylabel("Torque (mNm)")
plt.grid()

plt.tight_layout()
plt.show()
