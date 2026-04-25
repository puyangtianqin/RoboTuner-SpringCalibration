import math
import sys
import time
from collections import deque
from time import sleep
import csv
from pathlib import Path

# MUST ENANBLE ENCODER TO USE DATA LOGGING
# of allow nans for deflection in line 423
# Encoder still may need to be converted to other units
# May need to increase sensor resolution by changing self.sensor_timer.start(100) -> 20 or 10 for higher Hz


import RPi.GPIO as GPIO
from PyQt5.QtCore import QPointF, QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput
except ImportError:
    VoltageRatioInput = None

DIR = 4
STEP = 23
CW = 1
CCW = 0
DIR_SETUP_DELAY_S = 0.01
PULSES_PER_REV = 1600
STEP_DELAY_S = 0.005
RETURN_FREQUENCY_HZ = 50.0

TORQUE_CHANNEL = 0
CALIBRATION_FACTOR = 98640.737718654
DATA_RATE = 100
NAN_TEXT = "nan"

ENCODER_ENABLED = False
ENCODER_CLK = 11
ENCODER_MISO = 9
ENCODER_CS = 8
ENCODER_ALPHA = 0.1
ENCODER_FRAME_BITS = 24
ENCODER_DATA_BITS = 18
ENCODER_STATUS_BITS = 6
ENCODER_DATA_MASK = 0x3FFFF
ENCODER_STATUS_MASK = 0x3F
ENCODER_WAKE_DELAY_S = 0.000005
PLOT_HISTORY = 200
RESULTS_DIR = Path(__file__).resolve().parent.parent / "Results"
RESULTS_DIR.mkdir(exist_ok=True)


class WaveformWidget(QWidget):
    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self.title = title
        self.samples = deque(maxlen=PLOT_HISTORY)
        self.pen = QPen(QColor(color), 2)
        self.setMinimumHeight(120)

    def update_samples(self, samples):
        self.samples.clear()
        self.samples.extend(samples)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f7f7f7"))

        plot_rect = self.rect().adjusted(8, 24, -8, -8)
        painter.setPen(QColor("#666666"))
        painter.drawText(8, 16, self.title)

        painter.setPen(QPen(QColor("#d0d0d0"), 1))
        painter.drawRect(plot_rect)

        if len(self.samples) < 2:
            painter.setPen(QColor("#999999"))
            painter.drawText(plot_rect, Qt.AlignCenter, "Waiting for data")
            return

        valid_samples = [value for value in self.samples if not math.isnan(value)]
        if len(valid_samples) < 2:
            painter.setPen(QColor("#999999"))
            painter.drawText(plot_rect, Qt.AlignCenter, "Waiting for data")
            return

        min_val = min(valid_samples)
        max_val = max(valid_samples)
        if math.isclose(min_val, max_val):
            min_val -= 1.0
            max_val += 1.0

        points = []
        width = max(plot_rect.width(), 1)
        height = max(plot_rect.height(), 1)
        sample_count = len(self.samples) - 1

        for index, value in enumerate(self.samples):
            if math.isnan(value):
                continue
            x = plot_rect.left() + (index / sample_count) * width
            normalized = (value - min_val) / (max_val - min_val)
            y = plot_rect.bottom() - normalized * height
            points.append(QPointF(x, y))

        if len(points) >= 2:
            painter.setPen(self.pen)
            painter.drawPolyline(QPolygonF(points))

        painter.setPen(QColor("#666666"))
        painter.drawText(
            plot_rect.adjusted(6, 6, -6, -6),
            Qt.AlignTop | Qt.AlignRight,
            f"{valid_samples[-1]:.2f}",
        )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Senior Design")
        self.resize(1000, 600)
        self.stop_requested = False
        self.emergency_stop_enabled = False
        self.step_counter = 0
        self.actuation_frequency_hz = 1.0 / (2.0 * STEP_DELAY_S)
        self.active_tab_index = 0
        self.motion_lock_active = False
        self.bridge = None
        self.tare_offset = None
        self.latest_voltage_ratio = math.nan
        self.latest_force = math.nan
        self.encoder_available = False
        self.encoder_filtered = math.nan
        self.encoder_raw = math.nan
        self.encoder_status = math.nan
        self.logging_enabled = True
        self.torque_history = deque([math.nan], maxlen=PLOT_HISTORY)
        self.encoder_history = deque([math.nan], maxlen=PLOT_HISTORY)

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(DIR, GPIO.OUT)
        GPIO.setup(STEP, GPIO.OUT)
        GPIO.output(STEP, GPIO.LOW)

        container = QWidget(self)
        root_layout = QHBoxLayout(container)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(16)
        self.setCentralWidget(container)

        action_panel = QWidget()
        action_panel.setFixedWidth(180)
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.brake_button = QPushButton("Brake")
        self.brake_button.setFixedHeight(40)
        self.brake_button.clicked.connect(self.request_stop)
        action_layout.addWidget(self.brake_button)

        self.emergency_stop_button = QPushButton("E-Break: F")
        self.emergency_stop_button.setFixedHeight(40)
        self.emergency_stop_button.setCheckable(True)
        self.emergency_stop_button.toggled.connect(self.on_emergency_stop_toggled)
        action_layout.addWidget(self.emergency_stop_button)

        self.step_counter_label = QLabel("Step Counter: 0 pulses")
        self.step_counter_label.setWordWrap(True)
        action_layout.addWidget(self.step_counter_label)

        self.stepper_status_label = QLabel("Stepper State: IDLE")
        self.stepper_status_label.setWordWrap(True)
        action_layout.addWidget(self.stepper_status_label)

        speed_label = QLabel("Actuation Freq (Hz)")
        action_layout.addWidget(speed_label)

        self.actuation_frequency_input = QDoubleSpinBox()
        self.actuation_frequency_input.setRange(1.0, 1000.0)
        self.actuation_frequency_input.setSingleStep(10.0)
        self.actuation_frequency_input.setDecimals(1)
        self.actuation_frequency_input.setValue(self.actuation_frequency_hz)
        self.actuation_frequency_input.valueChanged.connect(
            self.on_actuation_frequency_changed
        )
        action_layout.addWidget(self.actuation_frequency_input)

        self.reset_counter_button = QPushButton("Reset Counter")
        self.reset_counter_button.setFixedHeight(32)
        self.reset_counter_button.clicked.connect(self.reset_step_counter)
        action_layout.addWidget(self.reset_counter_button)

        self.return_to_zero_button = QPushButton("Return to Zero")
        self.return_to_zero_button.setFixedHeight(32)
        self.return_to_zero_button.clicked.connect(self.return_to_zero)
        action_layout.addWidget(self.return_to_zero_button)

        action_layout.addStretch()

        root_layout.addWidget(action_panel, 0)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        root_layout.addWidget(self.tabs, 3)

        self.sensor_panel = QWidget()
        self.sensor_panel.setFixedWidth(240)
        root_layout.addWidget(self.sensor_panel, 1)

        self.manual_tab = QWidget()
        self.automation_tab = QWidget()
        self.tabs.addTab(self.manual_tab, "Manual Control")
        self.tabs.addTab(self.automation_tab, "Automation")

        self._build_manual_tab()
        self._build_automation_tab()
        self._build_sensor_panel()
        self._init_encoder()
        self._init_torque_sensor()
        self._start_sensor_refresh()
        self.start_time = time.time()
        self._update_emergency_stop_button()
        self._update_step_counter_label()
        self._set_motion_controls_enabled(True)

        csv_path = RESULTS_DIR / f"torque_deflection_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        self.csv_file = open(csv_path, "w", newline="")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(["time_s", "torque", "deflection"])

    def _build_manual_tab(self):
        QLabel("Revolutions (-1 to 1, + is CW)", self.manual_tab).setGeometry(
            40, 40, 260, 30
        )

        self.manual_rev_input = QDoubleSpinBox(self.manual_tab)
        self.manual_rev_input.setRange(-1.0, 1.0)
        self.manual_rev_input.setSingleStep(0.1)
        self.manual_rev_input.setDecimals(2)
        self.manual_rev_input.setGeometry(40, 75, 120, 35)

        self.manual_actuation_button = QPushButton("Actuation Cmd", self.manual_tab)
        self.manual_actuation_button.setGeometry(40, 130, 160, 40)
        self.manual_actuation_button.clicked.connect(self.run_manual_actuation)

    def _build_automation_tab(self):
        QLabel("Move per step (rev)", self.automation_tab).setGeometry(40, 40, 180, 30)
        self.auto_step_rev_input = QDoubleSpinBox(self.automation_tab)
        self.auto_step_rev_input.setRange(0.01, 1.0)
        self.auto_step_rev_input.setSingleStep(0.05)
        self.auto_step_rev_input.setDecimals(2)
        self.auto_step_rev_input.setValue(0.10)
        self.auto_step_rev_input.setGeometry(40, 75, 120, 35)

        QLabel("Number of points", self.automation_tab).setGeometry(220, 40, 140, 30)
        self.auto_point_count_input = QSpinBox(self.automation_tab)
        self.auto_point_count_input.setRange(1, 1000)
        self.auto_point_count_input.setValue(10)
        self.auto_point_count_input.setGeometry(220, 75, 120, 35)

        QLabel("Stop time per point (s)", self.automation_tab).setGeometry(
            40, 125, 180, 30
        )
        self.auto_pause_input = QDoubleSpinBox(self.automation_tab)
        self.auto_pause_input.setRange(0.0, 3600.0)
        self.auto_pause_input.setSingleStep(0.5)
        self.auto_pause_input.setDecimals(1)
        self.auto_pause_input.setValue(2.0)
        self.auto_pause_input.setGeometry(40, 160, 120, 35)

        QLabel("Direction", self.automation_tab).setGeometry(220, 125, 100, 30)
        self.auto_direction_input = QComboBox(self.automation_tab)
        self.auto_direction_input.addItems(["CW", "CCW"])
        self.auto_direction_input.setGeometry(220, 160, 120, 35)

        self.automation_start_button = QPushButton(
            "Automation Start", self.automation_tab
        )
        self.automation_start_button.setGeometry(40, 220, 180, 40)
        self.automation_start_button.clicked.connect(self.run_automation)

    def _build_sensor_panel(self):
        layout = QVBoxLayout(self.sensor_panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Sensor Readout")
        layout.addWidget(title)

        self.sensor_state_label = QLabel("State: Waiting for sensor")
        layout.addWidget(self.sensor_state_label)

        self.sensor_voltage_label = QLabel("Voltage Ratio: nan")
        layout.addWidget(self.sensor_voltage_label)

        self.sensor_force_label = QLabel("Force: nan")
        layout.addWidget(self.sensor_force_label)

        encoder_title = QLabel("Spring Deflection Encoder")
        layout.addWidget(encoder_title)

        self.encoder_state_label = QLabel("State: Waiting for encoder")
        layout.addWidget(self.encoder_state_label)

        self.encoder_raw_label = QLabel("Raw: nan")
        layout.addWidget(self.encoder_raw_label)

        self.encoder_filtered_label = QLabel("Filtered: nan")
        layout.addWidget(self.encoder_filtered_label)

        self.torque_plot = WaveformWidget("Torque Waveform", "#c1121f")
        layout.addWidget(self.torque_plot)

        self.encoder_plot = WaveformWidget("Encoder Waveform", "#1d3557")
        layout.addWidget(self.encoder_plot)

        layout.addStretch()

    def _init_encoder(self):
        if not ENCODER_ENABLED:
            self.encoder_state_label.setText("State: Waiting for encoder")
            return

        try:
            GPIO.setup(ENCODER_CLK, GPIO.OUT)
            GPIO.setup(ENCODER_CS, GPIO.OUT)
            GPIO.setup(ENCODER_MISO, GPIO.IN)
            GPIO.output(ENCODER_CS, GPIO.HIGH)
            GPIO.output(ENCODER_CLK, GPIO.HIGH)
            self.encoder_available = True
            self.encoder_state_label.setText("State: Live")
        except Exception:
            self.encoder_available = False
            self.encoder_raw = math.nan
            self.encoder_filtered = math.nan
            self.encoder_status = math.nan
            self.encoder_state_label.setText("State: Waiting for encoder")

    def _init_torque_sensor(self):
        if VoltageRatioInput is None:
            self.sensor_state_label.setText("State: Waiting for sensor")
            return

        try:
            self.bridge = VoltageRatioInput()
            self.bridge.setChannel(TORQUE_CHANNEL)
            self.bridge.setOnAttachHandler(self.on_sensor_attach)
            self.bridge.setOnVoltageRatioChangeHandler(self.on_voltage_ratio_change)
            self.bridge.openWaitForAttachment(5000)
            self.bridge.setDataRate(DATA_RATE)
            self.sensor_state_label.setText("State: Waiting for tare")
        except Exception:
            self.bridge = None
            self.sensor_state_label.setText("State: Waiting for sensor")
            self.latest_voltage_ratio = math.nan
            self.latest_force = math.nan

    def _start_sensor_refresh(self):
        self.sensor_timer = QTimer(self)
        self.sensor_timer.timeout.connect(self.refresh_sensor_labels)
        self.sensor_timer.start(100)

    def on_sensor_attach(self, sensor):
        self.sensor_state_label.setText(
            f"State: Channel {sensor.getChannel()} attached"
        )

    def on_voltage_ratio_change(self, sensor, voltage_ratio):
        self.latest_voltage_ratio = voltage_ratio
        if self.tare_offset is None:
            self.tare_offset = voltage_ratio
        self.latest_force = (voltage_ratio - self.tare_offset) * CALIBRATION_FACTOR

    def refresh_sensor_labels(self):
        self.sensor_voltage_label.setText(
            f"Voltage Ratio: {self._format_numeric(self.latest_voltage_ratio, 6)}"
        )
        self.sensor_force_label.setText(
            f"Force: {self._format_numeric(self.latest_force, 2)}"
        )
        self.refresh_encoder_labels()
        self._update_waveforms()

        if math.isnan(self.latest_voltage_ratio):
            self.sensor_state_label.setText("State: Waiting for sensor")
        elif self.tare_offset is None:
            self.sensor_state_label.setText("State: Waiting for tare")
        else:
            self.sensor_state_label.setText("State: Live")
        self.log_data()

    def refresh_encoder_labels(self):
        if self.encoder_available:
            try:
                full_reading = self.read_encoder_raw()
                raw_data = (full_reading >> ENCODER_STATUS_BITS) & ENCODER_DATA_MASK
                self.encoder_status = full_reading & ENCODER_STATUS_MASK
                self.encoder_raw = raw_data

                if math.isnan(self.encoder_filtered):
                    self.encoder_filtered = float(raw_data)
                else:
                    self.encoder_filtered = (
                        ENCODER_ALPHA * raw_data
                        + (1.0 - ENCODER_ALPHA) * self.encoder_filtered
                    )
            except Exception:
                self.encoder_available = False
                self.encoder_raw = math.nan
                self.encoder_filtered = math.nan
                self.encoder_status = math.nan

        self.encoder_raw_label.setText(
            f"Raw: {self._format_numeric(self.encoder_raw, 0)}"
        )
        self.encoder_filtered_label.setText(
            f"Filtered: {self._format_numeric(self.encoder_filtered, 0)}"
        )

        if self.encoder_available:
            self.encoder_state_label.setText("State: Live")
        else:
            self.encoder_state_label.setText("State: Waiting for encoder")

    def _update_waveforms(self):
        self.torque_history.append(self.latest_force)
        self.encoder_history.append(self.encoder_filtered)
        self.torque_plot.update_samples(self.torque_history)
        self.encoder_plot.update_samples(self.encoder_history)

    def read_encoder_raw(self):
        raw_val = 0
        GPIO.output(ENCODER_CS, GPIO.LOW)
        sleep(ENCODER_WAKE_DELAY_S)

        for _ in range(ENCODER_FRAME_BITS):
            GPIO.output(ENCODER_CLK, GPIO.LOW)
            bit = GPIO.input(ENCODER_MISO)
            raw_val = (raw_val << 1) | bit
            GPIO.output(ENCODER_CLK, GPIO.HIGH)

        GPIO.output(ENCODER_CS, GPIO.HIGH)
        return raw_val

    def _format_numeric(self, value, decimals):
        if value is None or math.isnan(value):
            return NAN_TEXT
        return f"{value:.{decimals}f}"

    def run_manual_actuation(self):
        if not self.emergency_stop_enabled:
            self.set_status("Stepper State: DISABLED (E-Break: F)")
            return

        revolutions = self.manual_rev_input.value()
        if revolutions == 0:
            return

        direction = CW if revolutions > 0 else CCW
        pulse_count = round(abs(revolutions) * PULSES_PER_REV)
        self.stop_requested = False
        self._set_motion_controls_enabled(False)
        try:
            self.move_stepper(direction, pulse_count, self.actuation_frequency_hz)
        finally:
            self._set_motion_controls_enabled(True)

    def run_automation(self):
        if not self.emergency_stop_enabled:
            self.set_status("Stepper State: DISABLED (E-Break: F)")
            return

        step_revolutions = self.auto_step_rev_input.value()
        point_count = self.auto_point_count_input.value()
        pause_seconds = self.auto_pause_input.value()
        direction = CW if self.auto_direction_input.currentText() == "CW" else CCW
        pulse_count = round(step_revolutions * PULSES_PER_REV)

        if pulse_count <= 0:
            return

        self.stop_requested = False
        self._set_motion_controls_enabled(False)
        try:
            for point_index in range(point_count):
                if self.stop_requested:
                    break

                self.move_stepper(direction, pulse_count, self.actuation_frequency_hz)
                if self.stop_requested:
                    break

                if point_index < point_count - 1:
                    self.wait_with_stop(pause_seconds)
        finally:
            self.set_status("Stepper State: IDLE")
            self._set_motion_controls_enabled(True)

    def move_stepper(self, direction, pulse_count, frequency_hz):
        if not self.emergency_stop_enabled:
            self.stop_requested = True
            self.set_status("Stepper State: DISABLED (E-Break: F)")
            return

        direction_text = "CW" if direction == CW else "CCW"
        self.set_status(f"Stepper State: MOVING {direction_text}")

        GPIO.output(DIR, direction)
        sleep(DIR_SETUP_DELAY_S)

        for _ in range(pulse_count):
            if self.stop_requested:
                break
            GPIO.output(STEP, GPIO.HIGH)
            sleep(0.5 / frequency_hz)
            GPIO.output(STEP, GPIO.LOW)
            sleep(0.5 / frequency_hz)
            self.step_counter += 1 if direction == CW else -1
            if self.step_counter % 50 == 0:
                self._update_step_counter_label()
            QApplication.processEvents()

        self._update_step_counter_label()

        if not self.stop_requested:
            self.set_status("Stepper State: IDLE")

    def wait_with_stop(self, seconds):
        self.set_status("Stepper State: IDLE")
        remaining = seconds
        while remaining > 0 and not self.stop_requested:
            delay = min(0.05, remaining)
            sleep(delay)
            remaining -= delay
            QApplication.processEvents()

    def set_status(self, text):
        self.stepper_status_label.setText(text)
        QApplication.processEvents()

    def _set_motion_controls_enabled(self, enabled):
        self.motion_lock_active = not enabled
        for widget in (
            self.tabs,
            self.actuation_frequency_input,
            self.reset_counter_button,
            self.return_to_zero_button,
            self.manual_rev_input,
            self.manual_actuation_button,
            self.auto_step_rev_input,
            self.auto_point_count_input,
            self.auto_pause_input,
            self.auto_direction_input,
            self.automation_start_button,
        ):
            widget.setEnabled(enabled)

    def on_actuation_frequency_changed(self, value_hz):
        self.actuation_frequency_hz = value_hz

    def request_stop(self):
        self.stop_requested = True
        self.set_status("Stepper State: IDLE")

    def on_emergency_stop_toggled(self, checked):
        self.emergency_stop_enabled = checked
        if not checked:
            self.request_stop()
        self._update_emergency_stop_button()

    def _update_emergency_stop_button(self):
        if self.emergency_stop_enabled:
            self.emergency_stop_button.setText("E-Break: T")
            self.emergency_stop_button.setStyleSheet(
                "background-color: #d62828; color: white; font-weight: bold;"
            )
        else:
            self.emergency_stop_button.setText("E-Break: F")
            self.emergency_stop_button.setStyleSheet(
                "background-color: #7f1d1d; color: white; font-weight: bold;"
            )

    def reset_step_counter(self):
        self.step_counter = 0
        self._update_step_counter_label()

    def return_to_zero(self):
        if not self.emergency_stop_enabled:
            self.set_status("Stepper State: DISABLED (E-Break: F)")
            return

        if self.step_counter == 0:
            self.set_status("Stepper State: AT ZERO")
            return

        self.stop_requested = False
        direction = CCW if self.step_counter > 0 else CW
        pulse_count = abs(self.step_counter)
        self._set_motion_controls_enabled(False)
        try:
            self.move_stepper(direction, pulse_count, RETURN_FREQUENCY_HZ)
        finally:
            self._set_motion_controls_enabled(True)

    def _update_step_counter_label(self):
        self.step_counter_label.setText(f"Step Counter: {self.step_counter} pulses")

    def on_tab_changed(self, index):
        if index != self.active_tab_index:
            self.request_stop()
            self.active_tab_index = index

    def closeEvent(self, event):
        self.emergency_stop_button.setChecked(False)
        self.emergency_stop_enabled = False
        self._update_emergency_stop_button()
        if self.bridge is not None:
            try:
                self.bridge.close()
            except Exception:
                pass
        GPIO.cleanup()
        super().closeEvent(event)
        if hasattr(self, "csv_file"):
            self.csv_file.close()

    def log_data(self):
        if not self.logging_enabled:
            return

        current_time = time.time() - self.start_time

        torque = self.latest_force
        deflection = self.encoder_filtered

        if math.isnan(torque) or math.isnan(deflection):
            return

        self.csv_writer.writerow([current_time, torque, deflection])


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
