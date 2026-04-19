import csv
import math
import re
import sys
from collections import deque
from datetime import datetime
from time import perf_counter, sleep

from PyQt5.QtCore import QEvent, QPointF, QTimer, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QPolygonF
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
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

try:
    import RPi.GPIO as GPIO
except ImportError:

    class MockGPIO:
        BCM = "BCM"
        OUT = "OUT"
        IN = "IN"
        HIGH = 1
        LOW = 0

        @staticmethod
        def setmode(mode):
            pass

        @staticmethod
        def setwarnings(flag):
            pass

        @staticmethod
        def setup(pin, mode):
            pass

        @staticmethod
        def output(pin, value):
            pass

        @staticmethod
        def input(pin):
            return 0

        @staticmethod
        def cleanup():
            pass

    GPIO = MockGPIO()


DIR = 4
STEP = 23
CW = 1
CCW = 0
DIR_SETUP_DELAY_S = 0.01
BASE_STEPPER_DRIVER_PULSES_PER_REV = 1600
STEPPER_DRIVER_PULSES_PER_REV = 6400 * 2 * 2
OPEN_LOOP_RATE_SCALE = (
    STEPPER_DRIVER_PULSES_PER_REV / BASE_STEPPER_DRIVER_PULSES_PER_REV
)
PULSES_PER_REV = STEPPER_DRIVER_PULSES_PER_REV
STEPPER_OUTPUT_DEG_PER_PULSE = 360.0 / STEPPER_DRIVER_PULSES_PER_REV
STEP_DELAY_S = 0.005
DEFAULT_ACTUATION_FREQUENCY_HZ = 100.0 * OPEN_LOOP_RATE_SCALE
RETURN_FREQUENCY_HZ = 50.0 * OPEN_LOOP_RATE_SCALE
CALIBRATION_START_FREQUENCY_HZ = 1.0 * OPEN_LOOP_RATE_SCALE
CALIBRATION_MAX_FREQUENCY_HZ = 20.0 * OPEN_LOOP_RATE_SCALE
CALIBRATION_RAMP_TIME_S = 2.0
CALIBRATION_TIMER_INTERVAL_MS = 20

TORQUE_CHANNEL = 0
CALIBRATION_FACTOR = 98640.737718654
DATA_RATE = 100
NAN_TEXT = "nan"
DISPLAY_TORQUE_SCALE = 1000.0
DEFAULT_TORQUE_LIMIT_MNM = 10000.0
CLOSED_LOOP_REFERENCE_MAX_OFFSET_MNM = 10000.0
PID_CONTROL_INTERVAL_MS = 20
PID_KP = 0.05
PID_KI = 0.0
PID_KD = 0.0005
PID_MAX_STEP_RATE_HZ = 150.0
PID_PULSE_OUTPUT_FREQUENCY_HZ = 500.0
PID_MAX_PULSES_PER_TICK = 2
PID_INTEGRAL_LIMIT = 10000.0
PID_ERROR_DEADBAND_MNM = 10.0
PID_HYSTERESIS_REENTRY_MNM = PID_ERROR_DEADBAND_MNM
SIMULATED_TORQUE_SLOPE_NM_PER_MOTOR_REV = 40.0
SIMULATED_TORQUE_TICKS_PER_MNM = 2000.0

ENCODER_ENABLED = True
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
ENCODER_COUNTS_PER_REV = ENCODER_DATA_MASK + 1
GEAR_REDUCTION_RATIO = 50.0
SIMULATED_ENCODER_DC_BIAS_TICKS = 300000.0
SIMULATED_SPRING_STIFFNESS_MNM_PER_OUTPUT_REV = (
    SIMULATED_TORQUE_SLOPE_NM_PER_MOTOR_REV
    * DISPLAY_TORQUE_SCALE
    * GEAR_REDUCTION_RATIO
    * 1.8
)
SIMULATED_SPRING_DAMPING_MNM_PER_OUTPUT_REV_PER_S = 960000.0
SIMULATED_TRANSIENT_TIME_CONSTANT_S = 0.6

PLOT_HISTORY = 200


class WaveformWidget(QWidget):
    def __init__(self, title, color, parent=None):
        super().__init__(parent)
        self.title = title
        self.paused = False
        self.samples = deque(maxlen=PLOT_HISTORY)
        self.pen = QPen(QColor(color), 2)
        self.reference_visible = False
        self.reference_pen = QPen(QColor("#1d4ed8"), 2, Qt.DashLine)
        self.reference_samples = deque(maxlen=PLOT_HISTORY)
        self.setMinimumHeight(120)

    def update_samples(self, samples):
        if self.paused:
            return
        self.samples.clear()
        self.samples.extend(samples)
        self.update()

    def set_reference_samples(self, samples, visible):
        self.reference_samples.clear()
        self.reference_samples.extend(samples)
        self.reference_visible = visible
        self.update()

    def set_title(self, title):
        self.title = title
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.paused = not self.paused
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f7f7f7"))

        plot_rect = self.rect().adjusted(8, 24, -8, -8)
        painter.setPen(QColor("#666666"))
        title = self.title if not self.paused else f"{self.title} (Paused)"
        painter.drawText(8, 16, title)

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

        valid_reference_samples = [
            value for value in self.reference_samples if not math.isnan(value)
        ]

        min_val = min(valid_samples)
        max_val = max(valid_samples)
        if self.reference_visible and valid_reference_samples:
            min_val = min(min_val, min(valid_reference_samples))
            max_val = max(max_val, max(valid_reference_samples))
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

        if self.reference_visible and valid_reference_samples:
            reference_points = []
            reference_sample_count = max(len(self.reference_samples) - 1, 1)
            for index, value in enumerate(self.reference_samples):
                if math.isnan(value):
                    continue
                x = plot_rect.left() + (index / reference_sample_count) * width
                normalized = (value - min_val) / (max_val - min_val)
                y = plot_rect.bottom() - normalized * height
                reference_points.append(QPointF(x, y))

            painter.setPen(self.reference_pen)
            if len(reference_points) >= 2:
                painter.drawPolyline(QPolygonF(reference_points))
            elif len(reference_points) == 1:
                single_point = reference_points[0]
                painter.drawLine(
                    QPointF(plot_rect.left(), single_point.y()),
                    QPointF(plot_rect.right(), single_point.y()),
                )

            painter.setPen(QColor("#1d4ed8"))
            painter.drawText(plot_rect.adjusted(6, 22, -6, -6), Qt.AlignTop | Qt.AlignRight, "Ref")

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
        self.actuation_frequency_hz = DEFAULT_ACTUATION_FREQUENCY_HZ
        self.active_tab_index = 0
        self.closed_loop_lock_active = False
        self.motion_lock_active = False
        self.bridge = None
        self.tare_offset = None
        self.latest_voltage_ratio = math.nan
        self.latest_force = math.nan
        self.torque_limit_mnm = DEFAULT_TORQUE_LIMIT_MNM
        self.torque_limit_tripped = False
        self.torque_limit_dialog_open = False
        self.closed_loop_reference_warning_open = False
        self.closed_loop_enabled = False
        self.closed_loop_automation_running = False
        self.closed_loop_automation_points = []
        self.closed_loop_automation_point_index = -1
        self.closed_loop_automation_hold_started_s = None
        self.closed_loop_automation_settled_started_s = None
        self.meaningful_logging_enabled = False
        self.start_time_s = perf_counter()
        self.last_log_time_s = self.start_time_s
        self.last_csv_flush_s = self.start_time_s
        self.csv_file = None
        self.csv_writer = None
        self.encoder_available = False
        self.encoder_filtered = math.nan
        self.encoder_raw = math.nan
        self.encoder_zero_raw = math.nan
        self.encoder_status = math.nan
        self.calibration_direction = None
        self.calibration_hold_start_s = None
        self.calibration_last_update_s = None
        self.calibration_step_accumulator = 0.0
        self.pid_integral = 0.0
        self.pid_previous_torque_mnm = math.nan
        self.pid_last_update_s = perf_counter()
        self.pid_step_accumulator = 0.0
        self.pid_hysteresis_active = False
        self.simulated_output_angle_rev = 0.0
        self.simulated_load_angle_rev = 0.0
        self.simulated_deflection_rev = 0.0
        self.simulated_transient_torque_mnm = 0.0
        self.last_simulated_plant_update_s = perf_counter()
        self.torque_history = deque([math.nan], maxlen=PLOT_HISTORY)
        self.reference_torque_history = deque([math.nan], maxlen=PLOT_HISTORY)
        self.torque_error_history = deque([math.nan], maxlen=PLOT_HISTORY)
        self.actuation_torque_history = deque([math.nan], maxlen=PLOT_HISTORY)
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
        action_panel.setFixedWidth(240)
        action_layout = QVBoxLayout(action_panel)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(8)

        self.brake_button = QPushButton("Brake")
        self.brake_button.setFixedHeight(40)
        self.brake_button.clicked.connect(self.request_stop)
        action_layout.addWidget(self.brake_button)

        self.emergency_stop_button = QPushButton("Stepper Disabled")
        self.emergency_stop_button.setFixedHeight(40)
        self.emergency_stop_button.setCheckable(True)
        self.emergency_stop_button.toggled.connect(self.on_emergency_stop_toggled)
        action_layout.addWidget(self.emergency_stop_button)

        self.step_counter_label = QLabel("Step Counter: 0 step")
        self.step_counter_label.setWordWrap(True)
        action_layout.addWidget(self.step_counter_label)

        counter_button_row = QHBoxLayout()
        counter_button_row.setSpacing(8)

        self.reset_counter_button = QPushButton("Reset Counter")
        self.reset_counter_button.setFixedHeight(32)
        self.reset_counter_button.clicked.connect(self.reset_step_counter)
        counter_button_row.addWidget(self.reset_counter_button)

        self.return_to_zero_button = QPushButton("Return to Zero")
        self.return_to_zero_button.setFixedHeight(32)
        self.return_to_zero_button.clicked.connect(self.return_to_zero)
        counter_button_row.addWidget(self.return_to_zero_button)

        action_layout.addLayout(counter_button_row)

        self.stepper_status_label = QLabel("Stepper State: IDLE")
        self.stepper_status_label.setWordWrap(True)
        action_layout.addWidget(self.stepper_status_label)

        speed_label = QLabel("Stepper Speed (steps/s)")
        action_layout.addWidget(speed_label)

        self.actuation_frequency_input = QDoubleSpinBox()
        self.actuation_frequency_input.setFixedWidth(120)
        self.actuation_frequency_input.setRange(1.0, 10000.0)
        self.actuation_frequency_input.setSingleStep(50.0)
        self.actuation_frequency_input.setDecimals(1)
        self.actuation_frequency_input.setValue(self.actuation_frequency_hz)
        self.actuation_frequency_input.valueChanged.connect(
            self.on_actuation_frequency_changed
        )
        action_layout.addWidget(self.actuation_frequency_input)

        torque_limit_label = QLabel("Torque Limit (mN-m)")
        action_layout.addWidget(torque_limit_label)

        self.torque_limit_input = QDoubleSpinBox()
        self.torque_limit_input.setFixedWidth(120)
        self.torque_limit_input.setRange(1.0, 1_000_000.0)
        self.torque_limit_input.setSingleStep(100.0)
        self.torque_limit_input.setDecimals(1)
        self.torque_limit_input.setValue(self.torque_limit_mnm)
        self.torque_limit_input.valueChanged.connect(self.on_torque_limit_changed)
        action_layout.addWidget(self.torque_limit_input)

        self.meaningful_logging_button = QPushButton("Meaningful Logging: OFF")
        self.meaningful_logging_button.setFixedHeight(36)
        self.meaningful_logging_button.setCheckable(True)
        self.meaningful_logging_button.toggled.connect(
            self.on_meaningful_logging_toggled
        )
        # When this is implemented in main.py, only apply the user-selected
        # sampling rate while meaningful logging is ON. Otherwise, record
        # background/history data at 1 Hz.
        # Also add a separate boolean CSV column so each row indicates whether
        # it was logged as meaningful/special data or regular history.
        action_layout.addWidget(self.meaningful_logging_button)

        data_rate_label = QLabel("Data Acquisition Rate (Hz)")
        action_layout.addWidget(data_rate_label)

        self.data_rate_input = QDoubleSpinBox()
        self.data_rate_input.setFixedWidth(120)
        self.data_rate_input.setRange(0.1, 1000.0)
        self.data_rate_input.setSingleStep(1.0)
        self.data_rate_input.setDecimals(1)
        self.data_rate_input.setValue(10.0)
        action_layout.addWidget(self.data_rate_input)

        serial_number_label = QLabel("Unique Serial Number")
        action_layout.addWidget(serial_number_label)

        self.serial_number_input = QLineEdit()
        self.serial_number_input.setFixedWidth(120)
        self.serial_number_input.setText("RoboTuners_Test")
        self.serial_number_input.setPlaceholderText("Enter serial number")
        # Keep this field in the GUI test harness for now. When this UI is moved
        # into the main file, use the entered serial number to help name the CSV.
        action_layout.addWidget(self.serial_number_input)

        action_layout.addStretch()

        root_layout.addWidget(action_panel, 0)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        root_layout.addWidget(self.tabs, 2)

        self.sensor_panel = QWidget()
        self.sensor_panel.setFixedWidth(240)
        root_layout.addWidget(self.sensor_panel, 1)

        self.manual_tab = QWidget()
        self.automation_tab = QWidget()
        self.closed_loop_tab = QWidget()
        self.closed_loop_automation_tab = QWidget()
        self.tabs.addTab(self.manual_tab, "Manual Control")
        self.tabs.addTab(self.automation_tab, "Automation")
        self.tabs.addTab(self.closed_loop_tab, "Closed-Loop Control")
        self.tabs.addTab(
            self.closed_loop_automation_tab, "Closed-Loop Automation"
        )
        self.closed_loop_tab_index = self.tabs.indexOf(self.closed_loop_tab)
        self.closed_loop_automation_tab_index = self.tabs.indexOf(
            self.closed_loop_automation_tab
        )
        self.tabs.tabBar().installEventFilter(self)

        self._build_manual_tab()
        self._build_automation_tab()
        self._build_closed_loop_tab()
        self._build_closed_loop_automation_tab()
        self._build_sensor_panel()
        self._init_encoder()
        self._init_torque_sensor()
        self._start_sensor_refresh()
        self._start_calibration_motion_timer()
        self._start_closed_loop_timer()
        self._update_emergency_stop_button()
        self._update_meaningful_logging_button()
        self._update_step_counter_label()
        self._set_motion_controls_enabled(True)

    def _build_manual_tab(self):
        QLabel(
            "Revolutions (-1 to 1, + is CW)", self.manual_tab
        ).setGeometry(40, 40, 260, 30)

        self.manual_rev_input = QDoubleSpinBox(self.manual_tab)
        self.manual_rev_input.setRange(-1.0, 1.0)
        self.manual_rev_input.setSingleStep(0.01)
        self.manual_rev_input.setDecimals(3)
        self.manual_rev_input.setGeometry(40, 75, 120, 35)

        self.manual_actuation_button = QPushButton("Actuation Cmd", self.manual_tab)
        self.manual_actuation_button.setGeometry(40, 130, 160, 40)
        self.manual_actuation_button.clicked.connect(self.run_manual_actuation)

        self.manual_move_cw_button = QPushButton("Move CW", self.manual_tab)
        self.manual_move_cw_button.setGeometry(40, 190, 120, 40)
        self.manual_move_cw_button.pressed.connect(
            lambda: self.start_manual_calibration_move(CW)
        )
        self.manual_move_cw_button.released.connect(self.stop_manual_calibration_move)

        self.manual_move_ccw_button = QPushButton("Move CCW", self.manual_tab)
        self.manual_move_ccw_button.setGeometry(180, 190, 120, 40)
        self.manual_move_ccw_button.pressed.connect(
            lambda: self.start_manual_calibration_move(CCW)
        )
        self.manual_move_ccw_button.released.connect(self.stop_manual_calibration_move)

    def _build_automation_tab(self):
        QLabel("Move per step (rev)", self.automation_tab).setGeometry(
            40, 40, 180, 30
        )
        self.auto_step_rev_input = QDoubleSpinBox(self.automation_tab)
        self.auto_step_rev_input.setRange(0.001, 1.0)
        self.auto_step_rev_input.setSingleStep(0.01)
        self.auto_step_rev_input.setDecimals(3)
        self.auto_step_rev_input.setValue(0.10)
        self.auto_step_rev_input.setGeometry(40, 75, 120, 35)

        QLabel("Number of points", self.automation_tab).setGeometry(
            220, 40, 140, 30
        )
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

    def _build_closed_loop_tab(self):
        QLabel("Closed-Loop Torque Control", self.closed_loop_tab).setGeometry(
            40, 30, 240, 30
        )

        self.closed_loop_note_label = QLabel(
            "UI scaffold only for now. Control algorithm will be added later.",
            self.closed_loop_tab,
        )
        self.closed_loop_note_label.setGeometry(40, 60, 360, 24)
        self.closed_loop_note_label.setStyleSheet("color: #666666;")

        QLabel("Reference Torque (mN-m)", self.closed_loop_tab).setGeometry(
            40, 105, 180, 30
        )
        self.closed_loop_target_input = QDoubleSpinBox(self.closed_loop_tab)
        self.closed_loop_target_input.setGeometry(40, 140, 140, 35)
        self.closed_loop_target_input.setRange(-1_000_000.0, 1_000_000.0)
        self.closed_loop_target_input.setDecimals(2)
        self.closed_loop_target_input.setSingleStep(100.0)
        self.closed_loop_target_input.setValue(0.0)
        self.closed_loop_target_input.editingFinished.connect(
            self.validate_closed_loop_reference
        )

        self.closed_loop_toggle_button = QPushButton(
            "Closed Loop: OFF", self.closed_loop_tab
        )
        self.closed_loop_toggle_button.setGeometry(40, 205, 220, 40)
        self.closed_loop_toggle_button.setCheckable(True)
        self.closed_loop_toggle_button.setStyleSheet(
            "background-color: #6b7280; color: white; font-weight: bold;"
        )
        self.closed_loop_toggle_button.toggled.connect(
            self.on_closed_loop_toggled
        )

        self.closed_loop_status_label = QLabel(
            "Closed-Loop State: Idle", self.closed_loop_tab
        )
        self.closed_loop_status_label.setGeometry(40, 265, 220, 24)

    def _build_closed_loop_automation_tab(self):
        QLabel(
            "Closed-Loop Automation", self.closed_loop_automation_tab
        ).setGeometry(40, 30, 240, 30)

        self.closed_loop_automation_note_label = QLabel(
            "Ramps the closed-loop torque reference in stepped levels.",
            self.closed_loop_automation_tab,
        )
        self.closed_loop_automation_note_label.setGeometry(40, 60, 420, 24)
        self.closed_loop_automation_note_label.setStyleSheet("color: #666666;")

        QLabel("Torque Bound (mN-m)", self.closed_loop_automation_tab).setGeometry(
            40, 105, 180, 30
        )
        self.closed_loop_automation_bound_input = QDoubleSpinBox(
            self.closed_loop_automation_tab
        )
        self.closed_loop_automation_bound_input.setGeometry(40, 140, 140, 35)
        self.closed_loop_automation_bound_input.setRange(0.1, 1_000_000.0)
        self.closed_loop_automation_bound_input.setDecimals(2)
        self.closed_loop_automation_bound_input.setSingleStep(100.0)
        self.closed_loop_automation_bound_input.setValue(1000.0)

        QLabel("Torque Points", self.closed_loop_automation_tab).setGeometry(
            220, 105, 140, 30
        )
        self.closed_loop_automation_points_input = QSpinBox(
            self.closed_loop_automation_tab
        )
        self.closed_loop_automation_points_input.setGeometry(220, 140, 120, 35)
        self.closed_loop_automation_points_input.setRange(1, 1000)
        self.closed_loop_automation_points_input.setValue(10)

        QLabel(
            "Hold Time After Settling (s)", self.closed_loop_automation_tab
        ).setGeometry(40, 195, 200, 30)
        self.closed_loop_automation_pause_input = QDoubleSpinBox(
            self.closed_loop_automation_tab
        )
        self.closed_loop_automation_pause_input.setGeometry(40, 230, 140, 35)
        self.closed_loop_automation_pause_input.setRange(0.0, 3600.0)
        self.closed_loop_automation_pause_input.setDecimals(1)
        self.closed_loop_automation_pause_input.setSingleStep(0.5)
        self.closed_loop_automation_pause_input.setValue(2.0)

        QLabel("Direction", self.closed_loop_automation_tab).setGeometry(
            220, 195, 120, 30
        )
        self.closed_loop_automation_direction_input = QComboBox(
            self.closed_loop_automation_tab
        )
        self.closed_loop_automation_direction_input.setGeometry(220, 230, 120, 35)
        self.closed_loop_automation_direction_input.addItems(["CW", "CCW"])

        self.closed_loop_automation_start_button = QPushButton(
            "Start Closed-Loop Automation", self.closed_loop_automation_tab
        )
        self.closed_loop_automation_start_button.setGeometry(40, 295, 240, 40)
        self.closed_loop_automation_start_button.clicked.connect(
            self.start_closed_loop_automation
        )

        self.closed_loop_automation_status_label = QLabel(
            "Automation State: Idle", self.closed_loop_automation_tab
        )
        self.closed_loop_automation_status_label.setGeometry(40, 355, 340, 24)

    def _build_sensor_panel(self):
        layout = QVBoxLayout(self.sensor_panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Torque Sensor Readout")
        layout.addWidget(title)

        self.sensor_state_label = QLabel("State: Waiting for sensor")
        layout.addWidget(self.sensor_state_label)

        self.sensor_voltage_label = QLabel("Voltage Ratio: nan")
        layout.addWidget(self.sensor_voltage_label)

        self.sensor_torque_label = QLabel("Torque: nan mN-m")
        layout.addWidget(self.sensor_torque_label)

        layout.addSpacing(12)

        encoder_title = QLabel("Spring Deflection Encoder")
        layout.addWidget(encoder_title)

        self.encoder_state_label = QLabel("State: Waiting for encoder")
        layout.addWidget(self.encoder_state_label)

        self.encoder_raw_label = QLabel("Raw: nan")
        layout.addWidget(self.encoder_raw_label)

        self.encoder_filtered_label = QLabel("Filtered: nan")
        layout.addWidget(self.encoder_filtered_label)

        self.encoder_angle_label = QLabel("Angular Displacement: nan deg")
        layout.addWidget(self.encoder_angle_label)

        self.torque_plot = WaveformWidget("Torque Waveform", "#c1121f")
        layout.addWidget(self.torque_plot)

        self.actuation_torque_plot = WaveformWidget(
            "Torque Waveform (Last Actuation)", "#9c6644"
        )
        layout.addWidget(self.actuation_torque_plot)

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
            self.encoder_zero_raw = math.nan
            self.encoder_status = math.nan
            self.encoder_state_label.setText("State: Waiting for encoder")

    def _init_torque_sensor(self):
        if VoltageRatioInput is None:
            self.sensor_state_label.setText("State: Simulated")
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
            self.sensor_state_label.setText("State: Simulated")
            self.latest_voltage_ratio = 0.0
            self.latest_force = 0.0
            self.last_simulated_plant_update_s = perf_counter()

    def _start_sensor_refresh(self):
        self.sensor_timer = QTimer(self)
        self.sensor_timer.timeout.connect(self.refresh_sensor_labels)
        self.sensor_timer.start(20)

    def eventFilter(self, source, event):
        if (
            source == self.tabs.tabBar()
            and event.type() == QEvent.MouseButtonPress
            and self.closed_loop_lock_active
        ):
            tab_index = self.tabs.tabBar().tabAt(event.pos())
            if tab_index != -1 and tab_index not in (
                self.closed_loop_tab_index,
                self.closed_loop_automation_tab_index,
            ):
                self._show_closed_loop_tab_warning()
                event.accept()
                return True
        return super().eventFilter(source, event)

    def _start_calibration_motion_timer(self):
        self.calibration_timer = QTimer(self)
        self.calibration_timer.timeout.connect(self._process_calibration_motion)
        self.calibration_timer.start(CALIBRATION_TIMER_INTERVAL_MS)

    def _start_closed_loop_timer(self):
        self.closed_loop_timer = QTimer(self)
        self.closed_loop_timer.timeout.connect(self._process_closed_loop_control)
        self.closed_loop_timer.start(PID_CONTROL_INTERVAL_MS)

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
        if self.bridge is None:
            self._update_simulated_plant()

        self.sensor_voltage_label.setText(
            f"Voltage Ratio: {self._format_numeric(self.latest_voltage_ratio, 6)}"
        )
        displayed_torque = self.latest_force * DISPLAY_TORQUE_SCALE
        self.sensor_torque_label.setText(
            f"Torque: {self._format_numeric(displayed_torque, 2)} mN-m"
        )
        self._check_torque_limit(displayed_torque)
        self.refresh_encoder_labels()
        self._update_waveforms()
        self.log_data()

        if self.bridge is None:
            self.sensor_state_label.setText("State: Simulated")
        elif math.isnan(self.latest_voltage_ratio):
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
                if math.isnan(self.encoder_zero_raw):
                    self.encoder_zero_raw = float(raw_data)
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
                self.encoder_zero_raw = math.nan
                self.encoder_status = math.nan

        self.encoder_raw_label.setText(
            f"Raw: {self._format_numeric(self.encoder_raw, 0)}"
        )
        self.encoder_filtered_label.setText(
            f"Filtered: {self._format_numeric(self.encoder_filtered, 0)}"
        )
        self.encoder_angle_label.setText(
            "Angular Displacement: "
            f"{self._format_numeric(self._calculate_output_angle_deg(), 2)} deg"
        )

        if self.encoder_available:
            self.encoder_state_label.setText("State: Live")
        else:
            self.encoder_state_label.setText("State: Waiting for encoder")

    def _update_waveforms(self):
        displayed_torque = self.latest_force * DISPLAY_TORQUE_SCALE
        self.torque_history.append(displayed_torque)
        reference_torque = (
            self.closed_loop_target_input.value() if self.closed_loop_enabled else math.nan
        )
        self.reference_torque_history.append(reference_torque)
        torque_error = (
            reference_torque - displayed_torque
            if self.closed_loop_enabled and not math.isnan(displayed_torque)
            else math.nan
        )
        self.torque_error_history.append(torque_error)
        if self.closed_loop_enabled:
            self.actuation_torque_plot.set_title("Torque Tracking Error")
            self.actuation_torque_plot.update_samples(self.torque_error_history)
        else:
            self.actuation_torque_plot.set_title("Torque Waveform (Last Actuation)")
            self.actuation_torque_history.append(displayed_torque)
            self.actuation_torque_plot.update_samples(self.actuation_torque_history)
        self.encoder_history.append(self.encoder_filtered)
        self.torque_plot.update_samples(self.torque_history)
        self.encoder_plot.update_samples(self.encoder_history)
        self._update_torque_reference_overlay()

    def _reset_actuation_torque_history(self):
        self.actuation_torque_history.clear()
        self.actuation_torque_history.append(math.nan)
        self.actuation_torque_plot.update_samples(self.actuation_torque_history)

    def _reset_torque_error_history(self):
        self.torque_error_history.clear()
        self.torque_error_history.append(math.nan)

    def _update_torque_reference_overlay(self):
        self.torque_plot.set_reference_samples(
            self.reference_torque_history, self.closed_loop_enabled
        )

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

    def _calculate_output_angle_deg(self):
        if math.isnan(self.encoder_filtered):
            return math.nan
        if math.isnan(self.encoder_zero_raw):
            return math.nan
        encoder_motion_ticks = self.encoder_filtered - self.encoder_zero_raw
        return (encoder_motion_ticks / ENCODER_COUNTS_PER_REV) * 360.0

    def _update_simulated_plant(self):
        current_time_s = perf_counter()
        delta_s = current_time_s - self.last_simulated_plant_update_s
        self.last_simulated_plant_update_s = current_time_s
        if delta_s <= 0.0:
            return

        previous_output_angle_rev = self.simulated_output_angle_rev
        motor_angle_rev = self.step_counter / STEPPER_DRIVER_PULSES_PER_REV
        self.simulated_output_angle_rev = motor_angle_rev / GEAR_REDUCTION_RATIO
        output_velocity_rev_s = (
            self.simulated_output_angle_rev - previous_output_angle_rev
        ) / delta_s

        # Use a fixed load angle for now, so output angle directly creates spring
        # deflection and torque through the spring-damper relation.
        self.simulated_deflection_rev = (
            self.simulated_output_angle_rev - self.simulated_load_angle_rev
        )
        static_torque_mnm = (
            SIMULATED_SPRING_STIFFNESS_MNM_PER_OUTPUT_REV
            * self.simulated_deflection_rev
        )
        transient_target_mnm = (
            SIMULATED_SPRING_DAMPING_MNM_PER_OUTPUT_REV_PER_S * output_velocity_rev_s
        )
        transient_blend = 1.0 - math.exp(
            -delta_s / SIMULATED_TRANSIENT_TIME_CONSTANT_S
        )
        self.simulated_transient_torque_mnm += (
            transient_target_mnm - self.simulated_transient_torque_mnm
        ) * transient_blend
        torque_mnm = static_torque_mnm + self.simulated_transient_torque_mnm
        torque_ticks = round(torque_mnm * SIMULATED_TORQUE_TICKS_PER_MNM)
        quantized_torque_mnm = torque_ticks / SIMULATED_TORQUE_TICKS_PER_MNM
        self.latest_force = quantized_torque_mnm / DISPLAY_TORQUE_SCALE
        self.latest_voltage_ratio = self.latest_force / CALIBRATION_FACTOR

    def _calculate_simulated_encoder_ticks(self):
        encoder_motion_ticks = self.simulated_deflection_rev * ENCODER_COUNTS_PER_REV
        return SIMULATED_ENCODER_DC_BIAS_TICKS + encoder_motion_ticks

    def _reset_pid_state(self):
        self.pid_integral = 0.0
        self.pid_previous_torque_mnm = math.nan
        self.pid_last_update_s = perf_counter()
        self.pid_step_accumulator = 0.0
        self.pid_hysteresis_active = False

    def _process_closed_loop_control(self):
        if not self.closed_loop_enabled:
            return

        if not self._torque_feedback_ready():
            self.closed_loop_toggle_button.setChecked(False)
            return

        if not self.emergency_stop_enabled or self.torque_limit_tripped:
            self.closed_loop_toggle_button.setChecked(False)
            return

        current_torque_mnm = self.latest_force * DISPLAY_TORQUE_SCALE
        if math.isnan(current_torque_mnm):
            return

        current_time_s = perf_counter()
        delta_s = current_time_s - self.pid_last_update_s
        self.pid_last_update_s = current_time_s
        if delta_s <= 0.0:
            return

        target_torque_mnm = self.closed_loop_target_input.value()
        error_mnm = target_torque_mnm - current_torque_mnm

        if not self.pid_hysteresis_active:
            if abs(error_mnm) <= PID_HYSTERESIS_REENTRY_MNM:
                error_mnm = 0.0
            else:
                self.pid_hysteresis_active = True
        elif abs(error_mnm) <= PID_ERROR_DEADBAND_MNM:
            self.pid_hysteresis_active = False
            error_mnm = 0.0

        self.pid_integral += error_mnm * delta_s
        if error_mnm == 0.0:
            self.pid_integral = 0.0
        self.pid_integral = max(
            min(self.pid_integral, PID_INTEGRAL_LIMIT), -PID_INTEGRAL_LIMIT
        )

        if math.isnan(self.pid_previous_torque_mnm):
            torque_derivative_mnm_s = 0.0
        else:
            torque_derivative_mnm_s = (
                current_torque_mnm - self.pid_previous_torque_mnm
            ) / delta_s
        self.pid_previous_torque_mnm = current_torque_mnm

        commanded_rate_hz = (
            PID_KP * error_mnm
            + PID_KI * self.pid_integral
            - PID_KD * torque_derivative_mnm_s
        )
        commanded_rate_hz = max(
            min(commanded_rate_hz, PID_MAX_STEP_RATE_HZ), -PID_MAX_STEP_RATE_HZ
        )

        self.pid_step_accumulator += commanded_rate_hz * delta_s
        available_pulse_count = int(abs(self.pid_step_accumulator))
        if available_pulse_count <= 0:
            self.closed_loop_status_label.setText(
                "Closed-Loop State: Holding "
                f"({current_torque_mnm:.1f} mN-m, "
                f"error {error_mnm:.1f} mN-m, "
                f"rate {commanded_rate_hz:.1f} step/s)"
            )
            self._process_closed_loop_automation(current_time_s)
            return

        direction = CW if self.pid_step_accumulator > 0 else CCW
        pulse_count = min(available_pulse_count, PID_MAX_PULSES_PER_TICK)
        self.pid_step_accumulator -= math.copysign(
            pulse_count, self.pid_step_accumulator
        )
        direction_text = "CW" if direction == CW else "CCW"
        self.set_status(f"Stepper State: PID {direction_text}")
        pulses_sent = self._drive_stepper_pulses(
            direction,
            pulse_count,
            PID_PULSE_OUTPUT_FREQUENCY_HZ,
            process_events=False,
        )
        missed_pulses = pulse_count - pulses_sent
        if missed_pulses > 0:
            self.pid_step_accumulator += math.copysign(
                missed_pulses, commanded_rate_hz
            )
        self.closed_loop_status_label.setText(
            f"Closed-Loop State: Active ({current_torque_mnm:.1f} mN-m)"
        )
        self._process_closed_loop_automation(current_time_s)

    def _process_closed_loop_automation(self, current_time_s):
        if not self.closed_loop_automation_running:
            return

        if self.stop_requested or self.torque_limit_tripped:
            self._stop_closed_loop_automation("Automation State: Stopped")
            return

        if not self.closed_loop_automation_points:
            self._stop_closed_loop_automation("Automation State: No points loaded")
            return

        if self.closed_loop_automation_hold_started_s is None:
            self.closed_loop_automation_hold_started_s = current_time_s

        hold_duration_s = self.closed_loop_automation_pause_input.value()
        current_point = self.closed_loop_automation_point_index + 1
        total_points = len(self.closed_loop_automation_points)
        target_value = self.closed_loop_automation_points[
            self.closed_loop_automation_point_index
        ]
        current_torque_mnm = self.latest_force * DISPLAY_TORQUE_SCALE
        error_mnm = target_value - current_torque_mnm
        is_settled = (
            not math.isnan(current_torque_mnm)
            and abs(error_mnm) <= PID_ERROR_DEADBAND_MNM
            and not self.pid_hysteresis_active
        )

        if is_settled:
            if self.closed_loop_automation_settled_started_s is None:
                self.closed_loop_automation_settled_started_s = current_time_s
            settled_elapsed_s = (
                current_time_s - self.closed_loop_automation_settled_started_s
            )
        else:
            self.closed_loop_automation_settled_started_s = None
            settled_elapsed_s = 0.0

        if settled_elapsed_s < hold_duration_s:
            if is_settled:
                status_suffix = (
                    f"settled for {settled_elapsed_s:.1f}/{hold_duration_s:.1f} s"
                )
            else:
                status_suffix = f"settling ({error_mnm:.1f} mN-m error)"
            self.closed_loop_automation_status_label.setText(
                "Automation State: "
                f"Holding point {current_point}/{total_points} at "
                f"{target_value:.1f} mN-m, {status_suffix}"
            )
            return

        next_index = self.closed_loop_automation_point_index + 1
        if next_index >= total_points:
            self._stop_closed_loop_automation("Automation State: Complete")
            self.closed_loop_toggle_button.setChecked(False)
            return

        self.closed_loop_automation_point_index = next_index
        self.closed_loop_automation_hold_started_s = current_time_s
        self.closed_loop_automation_settled_started_s = None
        self._apply_closed_loop_automation_target(
            self.closed_loop_automation_points[self.closed_loop_automation_point_index]
        )
        self.closed_loop_automation_status_label.setText(
            "Automation State: "
            f"Point {self.closed_loop_automation_point_index + 1}/{total_points} engaged"
        )

    def start_manual_calibration_move(self, direction):
        if not self.emergency_stop_enabled:
            self.set_status("Stepper State: DISABLED (E-Break: F)")
            return

        self.calibration_direction = direction
        self.calibration_hold_start_s = perf_counter()
        self.calibration_last_update_s = self.calibration_hold_start_s
        self.calibration_step_accumulator = 0.0
        self.stop_requested = False
        direction_text = "CW" if direction == CW else "CCW"
        self.set_status(f"Stepper State: CALIBRATING {direction_text}")
        self._reset_actuation_torque_history()

    def stop_manual_calibration_move(self):
        if self.calibration_direction is None:
            return

        self.calibration_direction = None
        self.calibration_hold_start_s = None
        self.calibration_last_update_s = None
        self.calibration_step_accumulator = 0.0
        if not self.torque_limit_tripped:
            self.set_status("Stepper State: IDLE")

    def _process_calibration_motion(self):
        if self.calibration_direction is None or not self.emergency_stop_enabled:
            return

        current_time_s = perf_counter()
        elapsed_hold_s = current_time_s - self.calibration_hold_start_s
        delta_s = current_time_s - self.calibration_last_update_s
        self.calibration_last_update_s = current_time_s

        ramp_fraction = min(max(elapsed_hold_s / CALIBRATION_RAMP_TIME_S, 0.0), 1.0)
        frequency_hz = CALIBRATION_START_FREQUENCY_HZ + ramp_fraction * (
            CALIBRATION_MAX_FREQUENCY_HZ - CALIBRATION_START_FREQUENCY_HZ
        )
        self.calibration_step_accumulator += frequency_hz * delta_s
        pulse_count = int(self.calibration_step_accumulator)
        self.calibration_step_accumulator -= pulse_count

        if pulse_count <= 0:
            return

        self._drive_stepper_pulses(
            self.calibration_direction,
            pulse_count,
            frequency_hz,
            process_events=False,
        )

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
            if not self.torque_limit_tripped:
                self.set_status("Stepper State: IDLE")
            self._set_motion_controls_enabled(True)

    def start_closed_loop_automation(self):
        if not self.emergency_stop_enabled:
            self.set_status("Stepper State: DISABLED (E-Break: F)")
            return

        if not self._torque_feedback_ready():
            self._show_closed_loop_sensor_warning()
            return

        torque_bound_mnm = self.closed_loop_automation_bound_input.value()
        point_count = self.closed_loop_automation_points_input.value()
        direction_sign = (
            1.0
            if self.closed_loop_automation_direction_input.currentText() == "CW"
            else -1.0
        )

        self.closed_loop_automation_points = [
            direction_sign * torque_bound_mnm * (point_index + 1) / point_count
            for point_index in range(point_count)
        ]
        self.closed_loop_automation_point_index = 0
        self.closed_loop_automation_hold_started_s = perf_counter()
        self.closed_loop_automation_settled_started_s = None
        self.closed_loop_automation_running = True
        self.stop_requested = False

        self.stop_manual_calibration_move()
        self._set_motion_controls_enabled(False)
        self._set_closed_loop_enabled(True, self.closed_loop_automation_tab_index)
        self._apply_closed_loop_automation_target(
            self.closed_loop_automation_points[self.closed_loop_automation_point_index]
        )
        self.closed_loop_automation_status_label.setText(
            "Automation State: "
            f"Point 1/{len(self.closed_loop_automation_points)} engaged"
        )

    def _apply_closed_loop_automation_target(self, target_mnm):
        self.closed_loop_target_input.blockSignals(True)
        self.closed_loop_target_input.setValue(target_mnm)
        self.closed_loop_target_input.blockSignals(False)
        self.closed_loop_status_label.setText(
            f"Closed-Loop State: Target {target_mnm:.1f} mN-m"
        )

    def _stop_closed_loop_automation(self, status_text="Automation State: Idle"):
        self.closed_loop_automation_running = False
        self.closed_loop_automation_points = []
        self.closed_loop_automation_point_index = -1
        self.closed_loop_automation_hold_started_s = None
        self.closed_loop_automation_settled_started_s = None
        self.closed_loop_automation_status_label.setText(status_text)
        if not self.closed_loop_enabled:
            self._set_motion_controls_enabled(True)

    def move_stepper(self, direction, pulse_count, frequency_hz):
        if not self.emergency_stop_enabled:
            self.stop_requested = True
            self.set_status("Stepper State: DISABLED (E-Break: F)")
            return

        direction_text = "CW" if direction == CW else "CCW"
        self.set_status(f"Stepper State: MOVING {direction_text}")
        self._reset_actuation_torque_history()

        self._drive_stepper_pulses(direction, pulse_count, frequency_hz)

        if not self.stop_requested and not self.torque_limit_tripped:
            self.set_status("Stepper State: IDLE")

    def _drive_stepper_pulses(
        self, direction, pulse_count, frequency_hz, process_events=True
    ):
        if pulse_count <= 0:
            return 0

        GPIO.output(DIR, direction)
        sleep(DIR_SETUP_DELAY_S)

        pulse_delay_s = 0.5 / max(float(frequency_hz), 1.0)
        pulses_sent = 0
        for _ in range(pulse_count):
            if self.stop_requested or self.torque_limit_tripped:
                break
            GPIO.output(STEP, GPIO.HIGH)
            sleep(pulse_delay_s)
            GPIO.output(STEP, GPIO.LOW)
            sleep(pulse_delay_s)
            self.step_counter += 1 if direction == CW else -1
            pulses_sent += 1
            if self.step_counter % 50 == 0:
                self._update_step_counter_label()
            if process_events:
                QApplication.processEvents()

        self._update_step_counter_label()
        return pulses_sent

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
            self.torque_limit_input,
            self.data_rate_input,
            self.meaningful_logging_button,
            self.reset_counter_button,
            self.return_to_zero_button,
            self.manual_rev_input,
            self.manual_actuation_button,
            self.manual_move_cw_button,
            self.manual_move_ccw_button,
            self.auto_step_rev_input,
            self.auto_point_count_input,
            self.auto_pause_input,
            self.auto_direction_input,
            self.automation_start_button,
            self.closed_loop_automation_bound_input,
            self.closed_loop_automation_points_input,
            self.closed_loop_automation_pause_input,
            self.closed_loop_automation_direction_input,
            self.closed_loop_automation_start_button,
        ):
            widget.setEnabled(enabled)

    def on_actuation_frequency_changed(self, value_hz):
        self.actuation_frequency_hz = value_hz

    def on_torque_limit_changed(self, value_mnm):
        self.torque_limit_mnm = value_mnm
        if self.torque_limit_tripped:
            current_torque = self.latest_force * DISPLAY_TORQUE_SCALE
            if math.isnan(current_torque) or abs(current_torque) < self.torque_limit_mnm:
                self.torque_limit_tripped = False

    def on_closed_loop_toggled(self, checked):
        target_tab_index = (
            self.closed_loop_automation_tab_index
            if self.closed_loop_automation_running
            else self.closed_loop_tab_index
        )
        self._set_closed_loop_enabled(checked, target_tab_index)

    def _set_closed_loop_enabled(self, enabled, target_tab_index=None):
        if enabled and not self._torque_feedback_ready():
            self.closed_loop_lock_active = False
            self.closed_loop_enabled = False
            self.closed_loop_toggle_button.blockSignals(True)
            self.closed_loop_toggle_button.setChecked(False)
            self.closed_loop_toggle_button.blockSignals(False)
            self.closed_loop_toggle_button.setText("Closed Loop: OFF")
            self.closed_loop_toggle_button.setStyleSheet(
                "background-color: #6b7280; color: white; font-weight: bold;"
            )
            self.closed_loop_status_label.setText(
                "Closed-Loop State: Torque sensor not live"
            )
            self._show_closed_loop_sensor_warning()
            return

        self.closed_loop_lock_active = enabled
        self.closed_loop_enabled = enabled
        if enabled:
            self.stop_requested = False
            self.validate_closed_loop_reference()
            self.stop_manual_calibration_move()
            self._reset_pid_state()
            self._reset_torque_error_history()
            self.closed_loop_toggle_button.blockSignals(True)
            self.closed_loop_toggle_button.setChecked(True)
            self.closed_loop_toggle_button.blockSignals(False)
            self.closed_loop_toggle_button.setText("Closed Loop: ON")
            self.closed_loop_toggle_button.setStyleSheet(
                "background-color: #2a9d46; color: white; font-weight: bold;"
            )
            if not self.closed_loop_automation_running:
                self.closed_loop_status_label.setText(
                    "Closed-Loop State: Hold Torque Active"
                )
            if target_tab_index is not None:
                self.tabs.setCurrentIndex(target_tab_index)
            return

        self._reset_pid_state()
        self._reset_actuation_torque_history()
        self.closed_loop_toggle_button.blockSignals(True)
        self.closed_loop_toggle_button.setChecked(False)
        self.closed_loop_toggle_button.blockSignals(False)
        self.closed_loop_toggle_button.setText("Closed Loop: OFF")
        self.closed_loop_toggle_button.setStyleSheet(
            "background-color: #6b7280; color: white; font-weight: bold;"
        )
        self.closed_loop_status_label.setText("Closed-Loop State: Idle")
        if self.closed_loop_automation_running:
            self._stop_closed_loop_automation("Automation State: Stopped")
        elif self.motion_lock_active:
            self._set_motion_controls_enabled(True)
        if not self.torque_limit_tripped:
            self.set_status("Stepper State: IDLE")

    def _torque_feedback_ready(self):
        return (
            self.bridge is not None
            and self.tare_offset is not None
            and not math.isnan(self.latest_voltage_ratio)
            and not math.isnan(self.latest_force)
        )

    def _show_closed_loop_sensor_warning(self):
        QMessageBox.warning(
            self,
            "Closed-Loop Unavailable",
            (
                "Closed-loop control requires a live torque sensor reading. "
                "The motor was not moved."
            ),
        )

    def _show_closed_loop_tab_warning(self):
        QMessageBox.warning(
            self,
            "Closed-Loop Active",
            "Closed-loop hold torque is active. Turn it off before using the other tabs.",
        )

    def validate_closed_loop_reference(self):
        current_torque_mnm = self.latest_force * DISPLAY_TORQUE_SCALE
        if math.isnan(current_torque_mnm):
            return

        requested_torque_mnm = self.closed_loop_target_input.value()
        if (
            abs(requested_torque_mnm - current_torque_mnm)
            <= CLOSED_LOOP_REFERENCE_MAX_OFFSET_MNM
        ):
            return

        self.closed_loop_target_input.blockSignals(True)
        self.closed_loop_target_input.setValue(current_torque_mnm)
        self.closed_loop_target_input.blockSignals(False)

        if self.closed_loop_reference_warning_open:
            return

        self.closed_loop_reference_warning_open = True
        QMessageBox.warning(
            self,
            "Reference Torque Rejected",
            (
                "Reference torque must stay within +/-10 Nm of the current "
                "torque reading. The entry was reset to the current torque."
            ),
        )
        self.closed_loop_reference_warning_open = False

    def on_meaningful_logging_toggled(self, checked):
        self.meaningful_logging_enabled = checked
        self._update_meaningful_logging_button()

    def _check_torque_limit(self, torque_mnm):
        if math.isnan(torque_mnm) or self.torque_limit_tripped:
            return

        if abs(torque_mnm) >= self.torque_limit_mnm:
            self._trip_torque_limit(torque_mnm)

    def _trip_torque_limit(self, torque_mnm):
        self.torque_limit_tripped = True
        self.stop_requested = True
        self.set_status("Stepper State: TORQUE LIMIT REACHED")

        if self.emergency_stop_button.isChecked():
            self.emergency_stop_button.setChecked(False)
        else:
            self.emergency_stop_enabled = False
            self._update_emergency_stop_button()

        if self.torque_limit_dialog_open:
            return

        self.torque_limit_dialog_open = True
        QMessageBox.warning(
            self,
            "Torque Limit Reached",
            (
                f"Measured torque reached {torque_mnm:.2f} mN-m, "
                f"which exceeds the limit of {self.torque_limit_mnm:.2f} mN-m.\n\n"
                "The stepper has been disabled."
            ),
        )
        self.torque_limit_dialog_open = False

    def request_stop(self):
        self.stop_requested = True
        self.stop_manual_calibration_move()
        self._stop_closed_loop_automation("Automation State: Stopped")
        if self.closed_loop_enabled:
            self.closed_loop_toggle_button.setChecked(False)
        if not self.torque_limit_tripped:
            self.set_status("Stepper State: IDLE")

    def on_emergency_stop_toggled(self, checked):
        self.emergency_stop_enabled = checked
        if not checked:
            self.request_stop()
        elif self.torque_limit_tripped:
            self.torque_limit_tripped = False
        if not checked and self.closed_loop_enabled:
            self.closed_loop_toggle_button.setChecked(False)
        self._update_emergency_stop_button()

    def _update_emergency_stop_button(self):
        if self.emergency_stop_enabled:
            self.emergency_stop_button.setText("Stepper Enabled")
            self.emergency_stop_button.setStyleSheet(
                "background-color: #2a9d46; color: white; font-weight: bold;"
            )
        else:
            self.emergency_stop_button.setText("Stepper Disabled")
            self.emergency_stop_button.setStyleSheet(
                "background-color: #7f1d1d; color: white; font-weight: bold;"
            )

    def _update_meaningful_logging_button(self):
        if self.meaningful_logging_enabled:
            self.meaningful_logging_button.setText("Meaningful Logging: ON")
            self.meaningful_logging_button.setStyleSheet(
                "background-color: #2a9d46; color: white; font-weight: bold;"
            )
        else:
            self.meaningful_logging_button.setText("Meaningful Logging: OFF")
            self.meaningful_logging_button.setStyleSheet(
                "background-color: #6b7280; color: white; font-weight: bold;"
            )

    def reset_step_counter(self):
        self.step_counter = 0
        self.simulated_output_angle_rev = 0.0
        self.simulated_load_angle_rev = 0.0
        self.simulated_deflection_rev = 0.0
        self.simulated_transient_torque_mnm = 0.0
        if self.bridge is None:
            self.latest_force = 0.0
            self.latest_voltage_ratio = 0.0
        self.last_simulated_plant_update_s = perf_counter()
        if self.encoder_available and not math.isnan(self.encoder_raw):
            self.encoder_zero_raw = float(self.encoder_raw)
        else:
            self.encoder_zero_raw = math.nan
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
        self.step_counter_label.setText(f"Step Counter: {self.step_counter} step")

    def on_tab_changed(self, index):
        if self.closed_loop_lock_active and index not in (
            self.closed_loop_tab_index,
            self.closed_loop_automation_tab_index,
        ):
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex(
                self.closed_loop_automation_tab_index
                if self.closed_loop_automation_running
                else self.closed_loop_tab_index
            )
            self.tabs.blockSignals(False)
            self._show_closed_loop_tab_warning()
            return

        if self.closed_loop_enabled and index in (
            self.closed_loop_tab_index,
            self.closed_loop_automation_tab_index,
        ):
            self.active_tab_index = index
            return

        if index != self.active_tab_index:
            self.request_stop()
            self.active_tab_index = index

    def _safe_serial_number(self):
        serial_number = self.serial_number_input.text().strip()
        if not serial_number:
            serial_number = "RoboTuners_Test"
        serial_number = re.sub(r"[^A-Za-z0-9_.-]+", "_", serial_number)
        return serial_number.strip("._-") or "RoboTuners_Test"

    def _ensure_csv_logger(self):
        if self.csv_writer is not None:
            return

        serial_number = self._safe_serial_number()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{serial_number}_{timestamp}.csv"
        self.csv_file = open(filename, "w", newline="")
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(
            [
                "time_s",
                "serial_number",
                "meaningful_logging",
                "voltage_ratio",
                "torque_mnm",
                "encoder_raw",
                "encoder_filtered",
                "encoder_angle_deg",
                "step_counter",
                "closed_loop_enabled",
                "closed_loop_target_mnm",
            ]
        )

    def log_data(self):
        current_time_s = perf_counter()
        log_rate_hz = (
            self.data_rate_input.value() if self.meaningful_logging_enabled else 1.0
        )
        log_interval_s = 1.0 / max(log_rate_hz, 0.1)
        if current_time_s - self.last_log_time_s < log_interval_s:
            return

        torque_mnm = self.latest_force * DISPLAY_TORQUE_SCALE
        if math.isnan(torque_mnm) and math.isnan(self.encoder_filtered):
            return

        self._ensure_csv_logger()
        elapsed_s = current_time_s - self.start_time_s
        target_torque_mnm = (
            self.closed_loop_target_input.value() if self.closed_loop_enabled else math.nan
        )
        self.csv_writer.writerow(
            [
                f"{elapsed_s:.6f}",
                self._safe_serial_number(),
                int(self.meaningful_logging_enabled),
                self.latest_voltage_ratio,
                torque_mnm,
                self.encoder_raw,
                self.encoder_filtered,
                self._calculate_output_angle_deg(),
                self.step_counter,
                int(self.closed_loop_enabled),
                target_torque_mnm,
            ]
        )
        self.last_log_time_s = current_time_s
        if current_time_s - self.last_csv_flush_s >= 1.0:
            self.csv_file.flush()
            self.last_csv_flush_s = current_time_s

    def closeEvent(self, event):
        self.stop_manual_calibration_move()
        if self.bridge is not None:
            try:
                self.bridge.close()
            except Exception:
                pass
        if self.csv_file is not None:
            self.csv_file.close()
        GPIO.cleanup()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
