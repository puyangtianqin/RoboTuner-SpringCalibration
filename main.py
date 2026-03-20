import math
import sys
from time import sleep

import RPi.GPIO as GPIO
from PyQt5.QtCore import QTimer
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Senior Design")
        self.resize(1000, 600)
        self.stop_requested = False
        self.active_tab_index = 0
        self.bridge = None
        self.tare_offset = None
        self.latest_voltage_ratio = math.nan
        self.latest_force = math.nan
        self.encoder_available = False
        self.encoder_filtered = math.nan
        self.encoder_raw = math.nan
        self.encoder_status = math.nan

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

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.brake_button = QPushButton("Brake")
        self.brake_button.setFixedSize(100, 40)
        self.brake_button.clicked.connect(self.request_stop)
        left_layout.addWidget(self.brake_button)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        left_layout.addWidget(self.tabs)

        root_layout.addWidget(left_panel, 3)

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

    def _build_manual_tab(self):
        QLabel("Revolutions (-1 to 1, + is CW)", self.manual_tab).setGeometry(40, 40, 260, 30)

        self.manual_rev_input = QDoubleSpinBox(self.manual_tab)
        self.manual_rev_input.setRange(-1.0, 1.0)
        self.manual_rev_input.setSingleStep(0.1)
        self.manual_rev_input.setDecimals(2)
        self.manual_rev_input.setGeometry(40, 75, 120, 35)

        self.manual_actuation_button = QPushButton("Actuation Cmd", self.manual_tab)
        self.manual_actuation_button.setGeometry(40, 130, 160, 40)
        self.manual_actuation_button.clicked.connect(self.run_manual_actuation)

        self.manual_status_label = QLabel("Stepper State: IDLE", self.manual_tab)
        self.manual_status_label.setGeometry(40, 190, 220, 30)

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

        QLabel("Stop time per point (s)", self.automation_tab).setGeometry(40, 125, 180, 30)
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

        self.automation_start_button = QPushButton("Automation Start", self.automation_tab)
        self.automation_start_button.setGeometry(40, 220, 180, 40)
        self.automation_start_button.clicked.connect(self.run_automation)

        self.automation_status_label = QLabel("Stepper State: IDLE", self.automation_tab)
        self.automation_status_label.setGeometry(40, 280, 260, 30)

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
        self.sensor_state_label.setText(f"State: Channel {sensor.getChannel()} attached")

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

        if math.isnan(self.latest_voltage_ratio):
            self.sensor_state_label.setText("State: Waiting for sensor")
        elif self.tare_offset is None:
            self.sensor_state_label.setText("State: Waiting for tare")
        else:
            self.sensor_state_label.setText("State: Live")

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
        revolutions = self.manual_rev_input.value()
        if revolutions == 0:
            return

        direction = CW if revolutions > 0 else CCW
        pulse_count = round(abs(revolutions) * PULSES_PER_REV)
        self.stop_requested = False
        self.move_stepper(direction, pulse_count)

    def run_automation(self):
        step_revolutions = self.auto_step_rev_input.value()
        point_count = self.auto_point_count_input.value()
        pause_seconds = self.auto_pause_input.value()
        direction = CW if self.auto_direction_input.currentText() == "CW" else CCW
        pulse_count = round(step_revolutions * PULSES_PER_REV)

        if pulse_count <= 0:
            return

        self.stop_requested = False
        for point_index in range(point_count):
            if self.stop_requested:
                break

            self.move_stepper(direction, pulse_count)
            if self.stop_requested:
                break

            if point_index < point_count - 1:
                self.wait_with_stop(pause_seconds)

        self.set_status("Stepper State: IDLE")

    def move_stepper(self, direction, pulse_count):
        direction_text = "CW" if direction == CW else "CCW"
        self.set_status(f"Stepper State: MOVING {direction_text}")

        GPIO.output(DIR, direction)
        sleep(DIR_SETUP_DELAY_S)

        for _ in range(pulse_count):
            if self.stop_requested:
                break
            GPIO.output(STEP, GPIO.HIGH)
            sleep(STEP_DELAY_S)
            GPIO.output(STEP, GPIO.LOW)
            sleep(STEP_DELAY_S)
            QApplication.processEvents()

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
        self.manual_status_label.setText(text)
        self.automation_status_label.setText(text)
        QApplication.processEvents()

    def request_stop(self):
        self.stop_requested = True
        self.set_status("Stepper State: IDLE")

    def on_tab_changed(self, index):
        if index != self.active_tab_index:
            self.request_stop()
            self.active_tab_index = index

    def closeEvent(self, event):
        if self.bridge is not None:
            try:
                self.bridge.close()
            except Exception:
                pass
        GPIO.cleanup()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
