import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


# Configuration
RESULTS_DIR = Path(__file__).resolve().parent / "Results"
DATA_FILENAME = "RoboTuners_Test_20260420_160532.csv"
START_TIME_S = 0.0
END_TIME_S = 125.0
DEFAULT_REF_WINDOW_S = 10.0
AUTO_REFRESH_INTERVAL_MS = 1000


class RangeSlider(QWidget):
    valueChanged = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(34)
        self.minimum = 0.0
        self.maximum = 1.0
        self.start_value = 0.0
        self.end_value = 1.0
        self._active_handle = None
        self._margin = 12
        self._handle_radius = 7

    def setRange(self, minimum, maximum):
        if maximum <= minimum:
            maximum = minimum + 0.001
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.setValues(self.start_value, self.end_value, emit_signal=False)

    def setValues(self, start_value, end_value, emit_signal=False):
        start_value = self._clamp(start_value)
        end_value = self._clamp(end_value)
        if start_value > end_value:
            start_value, end_value = end_value, start_value
        self.start_value = start_value
        self.end_value = end_value
        self.update()
        if emit_signal:
            self.valueChanged.emit(self.start_value, self.end_value)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        y = self.height() // 2
        left = self._margin
        right = self.width() - self._margin
        start_x = self._value_to_x(self.start_value)
        end_x = self._value_to_x(self.end_value)

        painter.setPen(QPen(QColor("#c7c7c7"), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(left, y, right, y)

        painter.setPen(QPen(QColor("#2563eb"), 5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(start_x, y, end_x, y)

        painter.setPen(QPen(QColor("#1f2937"), 1))
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(start_x - self._handle_radius, y - self._handle_radius, self._handle_radius * 2, self._handle_radius * 2)
        painter.drawEllipse(end_x - self._handle_radius, y - self._handle_radius, self._handle_radius * 2, self._handle_radius * 2)

    def mousePressEvent(self, event):
        start_distance = abs(event.x() - self._value_to_x(self.start_value))
        end_distance = abs(event.x() - self._value_to_x(self.end_value))
        self._active_handle = "start" if start_distance <= end_distance else "end"
        self._move_active_handle(event.x())

    def mouseMoveEvent(self, event):
        self._move_active_handle(event.x())

    def mouseReleaseEvent(self, event):
        self._active_handle = None

    def _move_active_handle(self, x):
        value = self._x_to_value(x)
        if self._active_handle == "start":
            self.start_value = min(value, self.end_value)
        elif self._active_handle == "end":
            self.end_value = max(value, self.start_value)
        self.update()
        self.valueChanged.emit(self.start_value, self.end_value)

    def _clamp(self, value):
        return max(self.minimum, min(float(value), self.maximum))

    def _value_to_x(self, value):
        width = max(self.width() - 2 * self._margin, 1)
        ratio = (self._clamp(value) - self.minimum) / (self.maximum - self.minimum)
        return int(self._margin + ratio * width)

    def _x_to_value(self, x):
        width = max(self.width() - 2 * self._margin, 1)
        ratio = (x - self._margin) / width
        ratio = max(0.0, min(ratio, 1.0))
        return self.minimum + ratio * (self.maximum - self.minimum)


class PlotWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RoboTuner Results Plotter")
        self.resize(1400, 850)
        self._syncing_ref_controls = False
        self._syncing_analysis_controls = False
        self._plots_dirty = True

        container = QWidget(self)
        layout = QVBoxLayout(container)
        self.setCentralWidget(container)

        controls = QHBoxLayout()
        layout.addLayout(controls)

        controls.addWidget(QLabel("CSV file"))
        self.file_input = QComboBox()
        self.file_input.addItems(self._available_csv_files())
        default_index = self.file_input.findText(DATA_FILENAME)
        if default_index >= 0:
            self.file_input.setCurrentIndex(default_index)
        controls.addWidget(self.file_input, 2)

        self.refresh_status_label = QLabel(
            f"Auto-refresh: {AUTO_REFRESH_INTERVAL_MS / 1000:.1f} s"
        )
        controls.addWidget(self.refresh_status_label)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.reference_tab = QWidget()
        reference_layout = QVBoxLayout(self.reference_tab)
        self.tabs.addTab(self.reference_tab, "Reference Selection")

        analysis_controls = QHBoxLayout()
        reference_layout.addLayout(analysis_controls)

        analysis_controls.addWidget(QLabel("Analysis start (s)"))
        self.start_time_input = QDoubleSpinBox()
        self.start_time_input.setRange(0.0, 1_000_000.0)
        self.start_time_input.setDecimals(3)
        self.start_time_input.setValue(START_TIME_S)
        self.start_time_input.valueChanged.connect(self.on_analysis_start_changed)
        analysis_controls.addWidget(self.start_time_input)

        self.analysis_window_slider = RangeSlider()
        self.analysis_window_slider.valueChanged.connect(self.on_analysis_range_changed)
        analysis_controls.addWidget(self.analysis_window_slider, 2)

        analysis_controls.addWidget(QLabel("Analysis end (s)"))
        self.end_time_input = QDoubleSpinBox()
        self.end_time_input.setRange(0.0, 1_000_000.0)
        self.end_time_input.setDecimals(3)
        self.end_time_input.setValue(END_TIME_S)
        self.end_time_input.valueChanged.connect(self.on_analysis_end_changed)
        analysis_controls.addWidget(self.end_time_input)

        ref_controls = QHBoxLayout()
        reference_layout.addLayout(ref_controls)

        ref_controls.addWidget(QLabel("Ref start (s)"))
        self.ref_start_input = QDoubleSpinBox()
        self.ref_start_input.setRange(0.0, 1_000_000.0)
        self.ref_start_input.setDecimals(3)
        self.ref_start_input.valueChanged.connect(self.on_ref_start_changed)
        ref_controls.addWidget(self.ref_start_input)

        self.ref_window_slider = RangeSlider()
        self.ref_window_slider.valueChanged.connect(self.on_ref_range_changed)
        ref_controls.addWidget(self.ref_window_slider, 2)

        ref_controls.addWidget(QLabel("Ref end (s)"))
        self.ref_end_input = QDoubleSpinBox()
        self.ref_end_input.setRange(0.0, 1_000_000.0)
        self.ref_end_input.setDecimals(3)
        self.ref_end_input.valueChanged.connect(self.on_ref_end_changed)
        ref_controls.addWidget(self.ref_end_input)

        self.ref_value_label = QLabel("ref_encoder: nan")
        ref_controls.addWidget(self.ref_value_label)

        self.default_ref_button = QPushButton("Default Ref")
        self.default_ref_button.clicked.connect(lambda: self.reset_reference_window())
        ref_controls.addWidget(self.default_ref_button)

        self.reference_figure = Figure(figsize=(12, 6))
        self.reference_canvas = FigureCanvas(self.reference_figure)
        reference_layout.addWidget(self.reference_canvas, 1)

        self.analysis_tab = QWidget()
        analysis_layout = QVBoxLayout(self.analysis_tab)
        self.tabs.addTab(self.analysis_tab, "Analysis Plots")

        self.analysis_figure = Figure(figsize=(12, 8))
        self.analysis_canvas = FigureCanvas(self.analysis_figure)
        analysis_layout.addWidget(self.analysis_canvas, 1)

        self.file_input.currentIndexChanged.connect(lambda _: self.reset_reference_window())
        self.file_input.currentIndexChanged.connect(lambda _: self.reset_analysis_window())
        self.reset_analysis_window()
        self.reset_reference_window()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_if_needed)
        self.refresh_timer.start(AUTO_REFRESH_INTERVAL_MS)
        self.refresh_if_needed()

    def _available_csv_files(self):
        if not RESULTS_DIR.exists():
            return []
        return sorted(path.name for path in RESULTS_DIR.glob("*.csv"))

    def _selected_time_window(self):
        return self.start_time_input.value(), self.end_time_input.value()

    def _read_selected_csv(self):
        filename = self.file_input.currentText()
        if not filename:
            raise ValueError("No CSV files found in Results.")
        return pd.read_csv(RESULTS_DIR / filename)

    def _data_time_bounds(self, df):
        if df.empty:
            return START_TIME_S, END_TIME_S
        return float(df["time_s"].min()), float(df["time_s"].max())

    def _meaningful_rows(self, df):
        if "meaningful_logging" not in df.columns:
            return df
        meaningful_logging = pd.to_numeric(df["meaningful_logging"], errors="coerce")
        return df[meaningful_logging.fillna(0).astype(bool)]

    def mark_plots_dirty(self):
        self._plots_dirty = True

    def refresh_if_needed(self):
        if not self._plots_dirty:
            return
        self.update_plots()

    def reset_analysis_window(self):
        if self._syncing_analysis_controls:
            return

        try:
            df = self._read_selected_csv()
            data_start_s, data_end_s = self._data_time_bounds(df)
            start_time_s = max(data_start_s, min(START_TIME_S, data_end_s))
            end_time_s = max(start_time_s, min(END_TIME_S, data_end_s))
            if end_time_s <= start_time_s:
                end_time_s = data_end_s
            self._set_analysis_controls(start_time_s, end_time_s, data_start_s, data_end_s)
            self.mark_plots_dirty()
        except Exception:
            return

    def _set_analysis_controls(self, start_time_s, end_time_s, data_start_s=None, data_end_s=None):
        if data_start_s is None or data_end_s is None:
            try:
                data_start_s, data_end_s = self._data_time_bounds(self._read_selected_csv())
            except Exception:
                data_start_s, data_end_s = START_TIME_S, END_TIME_S

        start_time_s = max(data_start_s, min(start_time_s, data_end_s))
        end_time_s = max(start_time_s, min(end_time_s, data_end_s))

        self._syncing_analysis_controls = True
        try:
            self.analysis_window_slider.setRange(data_start_s, data_end_s)
            self.analysis_window_slider.setValues(start_time_s, end_time_s)
            self.start_time_input.setValue(start_time_s)
            self.end_time_input.setValue(end_time_s)
        finally:
            self._syncing_analysis_controls = False

    def on_analysis_range_changed(self, start_time_s, end_time_s):
        if self._syncing_analysis_controls:
            return
        self._set_analysis_controls(start_time_s, end_time_s)
        self.mark_plots_dirty()

    def on_analysis_start_changed(self, value):
        if self._syncing_analysis_controls:
            return
        self._set_analysis_controls(value, max(value, self.end_time_input.value()))
        self.mark_plots_dirty()

    def on_analysis_end_changed(self, value):
        if self._syncing_analysis_controls:
            return
        self._set_analysis_controls(self.start_time_input.value(), value)
        self.mark_plots_dirty()

    def reset_reference_window(self):
        if self._syncing_ref_controls:
            return

        try:
            df = self._read_selected_csv()
            meaningful_df = self._meaningful_rows(df)
            if meaningful_df.empty:
                meaningful_df = df
            if meaningful_df.empty:
                return

            ref_start_s = float(meaningful_df["time_s"].iloc[0])
            ref_end_s = min(ref_start_s + DEFAULT_REF_WINDOW_S, float(meaningful_df["time_s"].iloc[-1]))
            if ref_end_s <= ref_start_s:
                ref_end_s = min(float(df["time_s"].max()), ref_start_s + DEFAULT_REF_WINDOW_S)
            self._set_reference_controls(ref_start_s, ref_end_s)
            self.mark_plots_dirty()
        except Exception:
            return

    def _set_reference_controls(self, ref_start_s, ref_end_s):
        try:
            data_start_s, data_end_s = self._data_time_bounds(self._read_selected_csv())
        except Exception:
            data_start_s, data_end_s = START_TIME_S, END_TIME_S

        ref_start_s = max(data_start_s, min(ref_start_s, data_end_s))
        ref_end_s = max(ref_start_s, min(ref_end_s, data_end_s))

        self._syncing_ref_controls = True
        try:
            self.ref_window_slider.setRange(data_start_s, data_end_s)
            self.ref_window_slider.setValues(ref_start_s, ref_end_s)
            self.ref_start_input.setValue(ref_start_s)
            self.ref_end_input.setValue(ref_end_s)
        finally:
            self._syncing_ref_controls = False

    def on_ref_range_changed(self, ref_start_s, ref_end_s):
        if self._syncing_ref_controls:
            return
        self._set_reference_controls(ref_start_s, ref_end_s)
        self.mark_plots_dirty()

    def on_ref_start_changed(self, value):
        if self._syncing_ref_controls:
            return
        self._set_reference_controls(value, max(value, self.ref_end_input.value()))
        self.mark_plots_dirty()

    def on_ref_end_changed(self, value):
        if self._syncing_ref_controls:
            return
        self._set_reference_controls(self.ref_start_input.value(), value)
        self.mark_plots_dirty()

    def update_plots(self):
        self._plots_dirty = False
        start_time_s = self.start_time_input.value()
        end_time_s = self.end_time_input.value()
        ref_start_s = self.ref_start_input.value()
        ref_end_s = self.ref_end_input.value()

        if start_time_s >= end_time_s:
            self._show_error("Start time must be less than end time.")
            return
        if ref_start_s >= ref_end_s:
            self._show_error("Reference start time must be less than reference end time.")
            return

        try:
            df = self._read_selected_csv()
            if df.empty:
                self._show_error("No data found in the selected CSV.")
                return

            analysis_df = df[
                (df["time_s"] >= start_time_s) & (df["time_s"] <= end_time_s)
            ]
            if analysis_df.empty:
                self._show_error("No data found in the selected time window.")
                return

            meaningful_df = self._meaningful_rows(df)
            ref_df = meaningful_df[
                (meaningful_df["time_s"] >= ref_start_s)
                & (meaningful_df["time_s"] <= ref_end_s)
            ]
            if ref_df.empty:
                ref_df = df[(df["time_s"] >= ref_start_s) & (df["time_s"] <= ref_end_s)]
            if ref_df.empty:
                self._show_error("No data found in the selected reference window.")
                return

            ref_time = df["time_s"]
            ref_encoder_raw = df["encoder_raw"]
            time = analysis_df["time_s"]
            encoder_raw = analysis_df["encoder_raw"]
            torque = analysis_df["torque_mnm"]

            ref_encoder = ref_df["encoder_raw"].mean()
            delta_encoder = encoder_raw - ref_encoder
            ratio = delta_encoder / torque.replace(0, np.nan)
        except KeyError as exc:
            self._show_error(f"Missing required column: {exc}")
            return
        except Exception as exc:
            self._show_error(f"Could not load plot data:\n{exc}")
            return

        self.ref_value_label.setText(f"ref_encoder: {ref_encoder:.3f}")
        self.reference_figure.clear()

        ref_ax = self.reference_figure.add_subplot(1, 1, 1)
        ref_ax.plot(ref_time, ref_encoder_raw)
        ref_ax.axvspan(start_time_s, end_time_s, color="#fecaca", alpha=0.35)
        ref_ax.axvspan(ref_start_s, ref_end_s, color="#93c5fd", alpha=0.25)
        ref_ax.axhline(ref_encoder, color="#2563eb", linestyle="--", linewidth=1.5)
        ref_ax.set_title("Encoder Raw vs Time")
        ref_ax.set_xlabel("Time (s)")
        ref_ax.set_ylabel("Encoder Raw")
        ref_ax.grid(True)

        self.reference_figure.tight_layout()
        self.reference_canvas.draw()

        self.analysis_figure.clear()

        ax1 = self.analysis_figure.add_subplot(2, 2, 1)
        ax1.plot(time, delta_encoder)
        ax1.set_title("Delta Encoder vs Time")
        ax1.set_xlabel("Time (s)")
        ax1.set_ylabel("Delta Encoder")
        ax1.grid(True)

        ax2 = self.analysis_figure.add_subplot(2, 2, 2)
        ax2.plot(time, torque)
        ax2.set_title("Torque vs Time")
        ax2.set_xlabel("Time (s)")
        ax2.set_ylabel("Torque (mNm)")
        ax2.grid(True)

        ax3 = self.analysis_figure.add_subplot(2, 2, 3)
        ax3.plot(time, ratio)
        ax3.set_title("Delta Encoder / Torque vs Time")
        ax3.set_xlabel("Time (s)")
        ax3.set_ylabel("Delta Encoder / Torque")
        ax3.grid(True)

        ax4 = self.analysis_figure.add_subplot(2, 2, 4)
        ax4.scatter(torque, delta_encoder)
        ax4.set_title("Delta Encoder vs Torque")
        ax4.set_xlabel("Torque (mNm)")
        ax4.set_ylabel("Delta Encoder")
        ax4.grid(True)

        self.analysis_figure.tight_layout()
        self.analysis_canvas.draw()

    def _show_error(self, message):
        QMessageBox.warning(self, "Plot Error", message)


def main():
    app = QApplication(sys.argv)
    window = PlotWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
