"""Qt desktop control panel for BerryLink.

Thread rule: the server, Gemini gateway and recorder all call UiBridge from
worker threads.  UiBridge turns those calls into Qt signals; only the GUI
thread touches widgets.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import threading
import time
import uuid
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from typing import Any, Optional

from PyQt6.QtCore import QMetaObject, QObject, QPointF, QRectF, QSize, Qt, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QFontDatabase,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QGuiApplication,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


# --------------------------------------------------------------------------- theme

# Placeholders shown in the key entry once a provider is selected.
_PROVIDER_PLACEHOLDERS = {
    "openrouter": "Paste an OpenRouter API key (stored only on this desktop)",
    "xkiro": "Paste the xkiro API key for Qwen (stored only on this desktop)",
    "gemini": "Paste a Gemini API key (stored only on this desktop)",
}


THEME = """
* { font-family: "IBM Plex Sans"; color: #e9edff; font-size: 13px; }
QMainWindow, QWidget#root { background-color: #090c18; }
QWidget#content { background-color: #090c18; }
QFrame#sidebar { background-color: #0f1327; border-right: 1px solid #222a4a; }
QFrame#card { background-color: #141932; border: 1px solid #252d50; border-radius: 18px; }
QFrame#hero { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #1b2d73, stop:0.55 #2747a8, stop:1 #3c2a78); border: 1px solid #4867cb; border-radius: 24px; }
QFrame#warning { background-color: #291a22; border: 1px solid #6a3142; border-radius: 14px; }
QFrame#success { background-color: #112a26; border: 1px solid #235a4e; border-radius: 14px; }
QLabel { background: transparent; }
QLabel#h1 { font-family: "Fredoka"; font-size: 30px; font-weight: 600; color: #f5f7ff; }
QLabel#heroTitle { font-family: "Fredoka"; font-size: 31px; font-weight: 600; color: #ffffff; }
QLabel#heroSub { font-size: 14px; color: #d5ddff; }
QLabel#h2 { font-family: "Fredoka"; font-size: 19px; font-weight: 600; color: #f3f5ff; }
QLabel#h3 { font-family: "Fredoka"; font-size: 15px; font-weight: 500; color: #e9edff; }
QLabel#muted { color: #9aa5ca; }
QLabel#tiny { color: #8792b8; font-size: 11px; }
QLabel#code { font-family: "IBM Plex Mono", monospace; font-size: 34px; font-weight: 600; letter-spacing: 7px; color: #ffffff; }
QLabel#mono { font-family: "IBM Plex Mono", monospace; font-size: 11px; color: #aeb9de; }
QLabel#pill { background-color: #202945; color: #cad5ff; border: 1px solid #354168; border-radius: 11px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
QLabel#pillGood { background-color: #12352e; color: #8ff0cf; border: 1px solid #235c4f; border-radius: 11px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
QLabel#pillWarn { background-color: #3a2b14; color: #ffd596; border: 1px solid #66502a; border-radius: 11px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
QLabel#pillBad { background-color: #3c1722; color: #ffb1bd; border: 1px solid #713143; border-radius: 11px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
QLabel#recording { background-color: #421924; color: #ffd3da; border: 1px solid #803348; border-radius: 11px; padding: 4px 10px; font-size: 11px; font-weight: 600; }
QPushButton { background-color: #202844; border: 1px solid #354064; border-radius: 10px; padding: 8px 14px; color: #eef1ff; font-weight: 500; }
QPushButton:hover { background-color: #293454; border-color: #4b5b8c; }
QPushButton:pressed { background-color: #192039; }
QPushButton:disabled { color: #687294; background-color: #171d31; border-color: #242b45; }
QPushButton#primary { background-color: #5d7df0; border: 1px solid #7896ff; color: #ffffff; font-weight: 600; }
QPushButton#primary:hover { background-color: #6b8cff; }
QPushButton#danger { background-color: #d94a62; border: 1px solid #f2647a; color: #ffffff; font-weight: 600; }
QPushButton#danger:hover { background-color: #eb5872; }
QPushButton#resume { background-color: #d8a84a; border: 1px solid #f2c466; color: #221b0d; font-weight: 700; }
QPushButton#ghost { background-color: transparent; border: 1px solid #2f385b; color: #c3ccec; }
QPushButton#ghost:hover { background-color: #1b223b; }
QPushButton#nav { text-align: left; padding: 10px 14px; border-radius: 10px; border: 1px solid transparent; background: transparent; color: #a8b3d8; font-weight: 500; }
QPushButton#nav:hover { background-color: #171e36; color: #eef1ff; }
QPushButton#nav:checked { background-color: #202b52; border: 1px solid #344474; color: #ffffff; }
QLineEdit, QSpinBox { background-color: #0d1225; border: 1px solid #303b61; border-radius: 9px; padding: 8px 10px; selection-background-color: #5d7df0; }
QLineEdit:focus, QSpinBox:focus { border-color: #718fff; }
QCheckBox { spacing: 9px; color: #dce3ff; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px; border: 1px solid #47537c; background: #0d1225; }
QCheckBox::indicator:hover { border-color: #748bff; }
QCheckBox::indicator:checked { background-color: #5d7df0; border-color: #7e99ff; }
QTreeWidget { background-color: #0f1428; alternate-background-color: #121932; border: 1px solid #262f4e; border-radius: 12px; padding: 5px; selection-background-color: #273768; }
QTreeWidget::item { padding: 8px 4px; border-bottom: 1px solid #1d2540; }
QHeaderView::section { background-color: #161d36; color: #9fabd1; border: none; padding: 8px; font-weight: 600; font-size: 11px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: #0b0f1f; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2b365a; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #3c4b78; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTabWidget::pane { border: 1px solid #283154; border-radius: 12px; top: -1px; }
QTabBar::tab { background: #131a31; color: #aab5d9; padding: 8px 16px; border: 1px solid #283154; border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: #202a4b; color: #ffffff; }
QTextBrowser, QTextEdit, QPlainTextEdit { background-color: #0d1225; border: 1px solid #283154; border-radius: 10px; padding: 8px; selection-background-color: #3a4f92; }
QToolTip { background-color: #1c2440; color: #eef1ff; border: 1px solid #3b4770; padding: 5px; }
QMenu { background-color: #141a30; border: 1px solid #2e385b; padding: 5px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background-color: #29375f; }
QMenu::separator { height: 1px; background: #2c3657; margin: 5px 8px; }
QDialog { background-color: #10152a; }
QMessageBox { background-color: #10152a; }
"""


def load_fonts(asset_dir: str) -> tuple[str, str]:
    """Load the OFL fonts bundled with the app. Return family names."""
    families = QFontDatabase.families()
    heading = "Fredoka" if "Fredoka" in families else "DejaVu Sans"
    body = "IBM Plex Sans" if "IBM Plex Sans" in families else "DejaVu Sans"
    for filename in ("Fredoka.ttf", "IBMPlexSans.ttf"):
        path = os.path.join(asset_dir, filename)
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    families = QFontDatabase.families()
    heading = "Fredoka" if "Fredoka" in families else heading
    body = "IBM Plex Sans" if "IBM Plex Sans" in families else body
    return heading, body


class BerryMark(QWidget):
    """A tiny painted blueberry used in the desktop chrome."""

    def __init__(self, size: int = 46, parent=None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = float(self._size)
        cx, cy = s * 0.5, s * 0.54
        body = QPainterPath()
        body.moveTo(cx, cy - s * 0.36)
        body.cubicTo(cx - s * 0.30, cy - s * 0.37, cx - s * 0.44, cy - s * 0.10, cx - s * 0.39, cy + s * 0.12)
        body.cubicTo(cx - s * 0.34, cy + s * 0.33, cx - s * 0.12, cy + s * 0.39, cx, cy + s * 0.39)
        body.cubicTo(cx + s * 0.16, cy + s * 0.39, cx + s * 0.38, cy + s * 0.27, cx + s * 0.40, cy + s * 0.05)
        body.cubicTo(cx + s * 0.42, cy - s * 0.17, cx + s * 0.23, cy - s * 0.37, cx, cy - s * 0.36)
        grad = QLinearGradient(0, cy - s * 0.4, 0, cy + s * 0.4)
        grad.setColorAt(0, QColor("#9cb2ff"))
        grad.setColorAt(0.55, QColor("#5877eb"))
        grad.setColorAt(1, QColor("#263a9d"))
        p.setBrush(QBrush(grad))
        p.setPen(QPen(QColor("#17225b"), max(1.0, s * 0.035)))
        p.drawPath(body)
        # leaves
        p.setPen(QPen(QColor("#1b6453"), max(1.0, s * 0.02)))
        p.setBrush(QColor("#55dfae"))
        leaf = QPainterPath()
        leaf.moveTo(cx, cy - s * 0.35)
        leaf.cubicTo(cx - s * 0.05, cy - s * 0.48, cx - s * 0.22, cy - s * 0.50, cx - s * 0.31, cy - s * 0.43)
        leaf.cubicTo(cx - s * 0.22, cy - s * 0.32, cx - s * 0.10, cy - s * 0.32, cx, cy - s * 0.35)
        p.drawPath(leaf)
        # eyes
        eye_y = cy - s * 0.03
        for dx in (-s * 0.16, s * 0.16):
            p.setBrush(QColor("#f9fbff"))
            p.setPen(QPen(QColor("#17225b"), max(1.0, s * 0.025)))
            p.drawEllipse(QPointF(cx + dx, eye_y), s * 0.105, s * 0.13)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#121a45"))
            p.drawEllipse(QPointF(cx + dx + s * 0.018, eye_y + s * 0.012), s * 0.045, s * 0.058)
        p.setPen(QPen(QColor("#1d245e"), max(1.0, s * 0.028), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        mouth = QPainterPath(QPointF(cx - s * 0.065, cy + s * 0.16))
        mouth.quadTo(QPointF(cx, cy + s * 0.23), QPointF(cx + s * 0.065, cy + s * 0.16))
        p.drawPath(mouth)
        p.end()


def make_app_icon(size: int = 128) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    mark = BerryMark(size)
    mark.render(painter)
    painter.end()
    return QIcon(pixmap)


# --------------------------------------------------------------------------- bridge


class UiBridge(QObject):
    """Thread-safe adapter between gateway/server and the Qt widgets."""

    caption_requested = pyqtSignal(str, str)
    point_requested = pyqtSignal(int, int, str, str, object)
    stop_pointing_requested = pyqtSignal()
    sleep_requested = pyqtSignal()
    action_requested = pyqtSignal(str)
    clear_action_requested = pyqtSignal()
    emergency_changed = pyqtSignal(bool)
    recording_changed = pyqtSignal(bool, str)
    runtime_changed = pyqtSignal()
    peers_updated = pyqtSignal(object)
    confirm_requested = pyqtSignal(str, str, str, float)
    confirm_dismissed = pyqtSignal(str)
    emergency_pressed = pyqtSignal()
    hotkey_toggle_requested = pyqtSignal()
    hotkey_demo_point_requested = pyqtSignal()

    def __init__(self, control, parent=None) -> None:
        super().__init__(parent)
        self.control = control
        self.overlay = None
        self._pending_lock = threading.RLock()
        self._pending: dict[str, tuple[Future, float]] = {}
        self._emergency_callback = None

    def attach_overlay(self, overlay) -> None:
        self.overlay = overlay
        self.caption_requested.connect(overlay.show_caption)
        self.point_requested.connect(overlay.point_at)
        self.stop_pointing_requested.connect(overlay.stop_pointing)
        self.sleep_requested.connect(overlay.sleep)
        self.action_requested.connect(overlay.show_action)
        self.clear_action_requested.connect(overlay.clear_action)
        self.emergency_changed.connect(overlay.set_emergency)

    def set_emergency_callback(self, callback) -> None:
        self._emergency_callback = callback

    # ServerUi + OverlayPort methods; all may be called from worker threads.
    def caption(self, text: str, mood: str = "happy") -> None:
        self.caption_requested.emit(str(text), str(mood))

    def point_at(self, x: int, y: int, label: str, bubble: str = "", rect=None) -> None:
        self.point_requested.emit(int(x), int(y), str(label), str(bubble), rect)

    def stop_pointing(self) -> None:
        self.stop_pointing_requested.emit()

    def sleep(self) -> None:
        self.sleep_requested.emit()

    def show_action(self, label: str) -> None:
        self.action_requested.emit(str(label))

    def clear_action(self) -> None:
        self.clear_action_requested.emit()

    def set_recording(self, active: bool, label: str = "Recording") -> None:
        self.recording_changed.emit(bool(active), str(label))

    def set_emergency(self, active: bool) -> None:
        self.emergency_changed.emit(bool(active))

    def hide_overlay(self) -> None:
        overlay = self.overlay
        if overlay is None:
            return
        try:
            if QThread.currentThread() is self.thread():
                overlay.hide_for_capture()
            else:
                QMetaObject.invokeMethod(
                    overlay,
                    "hide_for_capture",
                    Qt.ConnectionType.BlockingQueuedConnection,
                )
        except Exception:
            pass

    def show_overlay(self) -> None:
        overlay = self.overlay
        if overlay is None:
            return
        try:
            if QThread.currentThread() is self.thread():
                overlay.show_after_capture()
            else:
                QMetaObject.invokeMethod(overlay, "show_after_capture", Qt.ConnectionType.QueuedConnection)
        except Exception:
            pass

    def notify_runtime(self) -> None:
        self.runtime_changed.emit()

    def peers_changed(self, peers: list[dict[str, Any]]) -> None:
        self.peers_updated.emit(peers)

    def confirm(self, title: str, description: str, timeout: float = 90.0) -> bool:
        token = uuid.uuid4().hex
        future: Future = Future()
        with self._pending_lock:
            if self._pending:
                return False
            self._pending[token] = (future, time.monotonic() + max(5.0, float(timeout)))
        self.confirm_requested.emit(token, title, description, float(timeout))
        try:
            return bool(future.result(timeout=max(5.0, float(timeout)) + 1.0))
        except FutureTimeoutError:
            self.confirm_dismissed.emit(token)
            return False
        finally:
            with self._pending_lock:
                self._pending.pop(token, None)

    def resolve_confirm(self, token: str, approved: bool) -> None:
        with self._pending_lock:
            item = self._pending.get(token)
            if item is None:
                return
            future, _ = item
            if not future.done():
                future.set_result(bool(approved))

    def trigger_emergency(self) -> None:
        self.control.trigger_emergency_stop()
        with self._pending_lock:
            tokens = list(self._pending.keys())
        for token in tokens:
            self.resolve_confirm(token, False)
            self.confirm_dismissed.emit(token)
        self.emergency_changed.emit(True)
        self.emergency_pressed.emit()
        if self._emergency_callback:
            try:
                self._emergency_callback()
            except Exception:
                pass

    def resume_controls(self) -> None:
        self.control.resume()
        self.emergency_changed.emit(False)

    def pending_confirmations(self) -> int:
        with self._pending_lock:
            return len(self._pending)


# --------------------------------------------------------------------------- small widgets


def _label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _button(text: str, name: str = "", slot=None) -> QPushButton:
    button = QPushButton(text)
    if name:
        button.setObjectName(name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot:
        button.clicked.connect(slot)
    return button


def _card(object_name: str = "card") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(11)
    return frame, layout


def _hbox(*widgets, spacing: int = 10) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(spacing)
    for widget in widgets:
        if widget is None:
            row.addStretch(1)
        elif isinstance(widget, int):
            row.addSpacing(widget)
        else:
            row.addWidget(widget)
    return row


def _pill(text: str, name: str = "pill") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
    return label


def _scroll_page() -> tuple[QScrollArea, QWidget, QVBoxLayout]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    inner = QWidget()
    inner.setObjectName("page")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(0, 2, 10, 24)
    layout.setSpacing(18)
    scroll.setWidget(inner)
    return scroll, inner, layout


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {sec:02d}s"


def _short_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%b %d, %H:%M")
    except (ValueError, TypeError):
        return str(value)[:16]


class TextDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 620)
        layout = QVBoxLayout(self)
        header = _label(title, "h2")
        layout.addWidget(header)
        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(text)
        body.setFont(QFont("IBM Plex Mono", 10))
        layout.addWidget(body, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = _button("Close", "ghost", self.accept)
        row.addWidget(close)
        layout.addLayout(row)


# --------------------------------------------------------------------------- dialogs


class PairingDialog(QDialog):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._initial_devices = len(controller.pairing.list_devices())
        self.setWindowTitle("Pair a phone")
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._build()
        self._timer.start()
        self._tick()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(14)
        title_row = QHBoxLayout()
        title_row.addWidget(BerryMark(42))
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(_label("Pair your phone", "h2"))
        text_col.addWidget(_label("BerryLink Talks to the desktop over your local Wi-Fi.", "muted", True))
        title_row.addLayout(text_col)
        title_row.addStretch(1)
        layout.addLayout(title_row)
        card, card_layout = _card()
        card_layout.addWidget(_label("Six-digit pairing code", "muted"))
        self.code_label = _label("—", "code")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.code_label)
        self.status_label = _label("", "muted", True)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.status_label)
        self.countdown = _label("", "tiny")
        self.countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.countdown)
        layout.addWidget(card)
        info, info_layout = _card()
        info_layout.addWidget(_label("Desktop address", "h3"))
        self.addresses_label = _label("", "mono", True)
        self.addresses_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.addresses_label)
        self.fingerprint_label = _label("", "mono", True)
        info_layout.addWidget(_label("Certificate fingerprint (compare in the app)", "muted"))
        info_layout.addWidget(self.fingerprint_label)
        info_layout.addWidget(
            _label(
                "On the phone: Pair → choose this desktop → Connect. The desktop shows an Allow "
                "prompt you approve once. A code is only needed when one-tap pairing is off there.",
                "muted",
                True,
            )
        )
        layout.addWidget(info)
        row = QHBoxLayout()
        copy = _button("Copy code", "ghost", self._copy_code)
        new_code = _button("New code", "ghost", self._new_code)
        self.done = _button("Done", "primary", self.accept)
        row.addWidget(copy)
        row.addWidget(new_code)
        row.addStretch(1)
        row.addWidget(self.done)
        layout.addLayout(row)

    def _copy_code(self) -> None:
        code = self.controller.pairing.pairing_status().get("code")
        if code:
            QApplication.clipboard().setText(str(code))

    def _new_code(self) -> None:
        self.controller.start_pairing()
        self._initial_devices = len(self.controller.pairing.list_devices())
        self._tick()

    def _tick(self) -> None:
        status = self.controller.pairing.pairing_status()
        devices = self.controller.pairing.list_devices()
        if len(devices) > self._initial_devices:
            self.code_label.setText("✓")
            self.status_label.setText(f"Paired with {devices[-1]['name']}")
            self.countdown.setText("You can close this window.")
            QTimer.singleShot(900, self.accept)
            return
        if status.get("open"):
            self.code_label.setText(" ".join(str(status.get("code", ""))))
            remaining = int(status.get("expires_in", 0))
            self.status_label.setText("Waiting for a phone…")
            self.countdown.setText(f"Expires in {remaining}s · {status.get('attempts_left', 0)} attempts left")
        else:
            self.code_label.setText("—")
            self.status_label.setText("Pairing is closed. Choose New code to try again.")
            self.countdown.setText("A code only lasts two minutes.")
        server = getattr(self.controller, "server", None)
        port = server.port if server and server.port else self.controller.config.port
        addresses = self.controller.network_addresses(port)
        self.addresses_label.setText("\n".join(addresses) if addresses else "No LAN address detected. Use manual IP in the app.")
        self.fingerprint_label.setText(self.controller.identity.pretty_fingerprint)

    def done(self, result: int) -> None:
        self._timer.stop()
        super().done(result)


class MeetingConsentDialog(QDialog):
    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Start meeting recording")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 22, 26, 20)
        layout.setSpacing(13)
        layout.addWidget(_label("Record a meeting", "h2"))
        layout.addWidget(
            _label(
                "BerryLink will record the desktop microphone in local five-minute chunks. "
                "A persistent red indicator stays visible on screen while recording.",
                "muted",
                True,
            )
        )
        warning = QFrame()
        warning.setObjectName("warning")
        warn_layout = QVBoxLayout(warning)
        warn_layout.setContentsMargins(14, 12, 14, 12)
        warn_layout.addWidget(
            _label(
                "Only continue if everyone who may be recorded has consented. "
                "Recording laws differ by location; you are responsible for obtaining consent.",
                "muted",
                True,
            )
        )
        layout.addWidget(warning)
        self.consent = QCheckBox("I have consent from everyone who may be recorded")
        layout.addWidget(self.consent)
        self.transcribe = QCheckBox("Transcribe after recording (AI provider)")
        self.transcribe.setChecked(bool(controller.config.meeting_transcribe))
        if not controller.ai_configured():
            self.transcribe.setChecked(False)
            self.transcribe.setEnabled(False)
            self.transcribe.setText("Transcription needs a saved AI key (Qwen, OpenRouter or Gemini)")
        layout.addWidget(self.transcribe)
        self.retain = QCheckBox("Keep the local audio files after transcription")
        self.retain.setChecked(bool(controller.config.meeting_retain_audio))
        layout.addWidget(self.retain)
        layout.addWidget(
            _label(
                "Meeting audio goes to the AI provider you connected, only after you stop the recording and only if "
                "transcription is checked. Gemini's free tier may retain interactions for up to one day. "
                "Speaker labels are best effort.",
                "tiny",
                True,
            )
        )
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(_button("Cancel", "ghost", self.reject))
        self.start_button = _button("Start recording", "danger", self._start)
        self.start_button.setEnabled(False)
        self.consent.toggled.connect(self.start_button.setEnabled)
        row.addWidget(self.start_button)
        layout.addLayout(row)

    def _start(self) -> None:
        if not self.consent.isChecked():
            return
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            self.controller.meeting.start(
                consent=True,
                transcribe=self.transcribe.isChecked(),
                retain_audio=self.retain.isChecked(),
                title=f"Meeting {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
            )
            self.controller.save_meeting_preferences(self.transcribe.isChecked(), self.retain.isChecked())
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Could not start recording", str(exc))
        finally:
            QApplication.restoreOverrideCursor()


class NotesDetailDialog(QDialog):
    def __init__(self, controller, session_id: str, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.session_id = session_id
        self.setWindowTitle("Meeting notes")
        self.resize(900, 700)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        try:
            self.detail = controller.meeting.read_session(session_id)
        except Exception as exc:
            layout.addWidget(_label(str(exc), "h2"))
            layout.addWidget(_button("Close", "ghost", self.accept))
            return
        session = self.detail.get("session", {})
        title_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.addWidget(_label(session.get("title", "Meeting"), "h2"))
        meta = (
            f"{_short_date(session.get('started_at'))} · {session.get('status', '')} · "
            f"{_format_duration(controller.session_duration(session))}"
        )
        title_col.addWidget(_label(meta, "muted"))
        title_row.addLayout(title_col)
        title_row.addStretch(1)
        layout.addLayout(title_row)
        tabs = QTabWidget()
        notes = QTextBrowser()
        notes.setMarkdown(self.detail.get("notes_md", ""))
        transcript = QTextEdit()
        transcript.setReadOnly(True)
        transcript.setPlainText(self.detail.get("transcript", ""))
        transcript.setFont(QFont("IBM Plex Mono", 10))
        tabs.addTab(notes, "Notes")
        tabs.addTab(transcript, "Transcript")
        layout.addWidget(tabs, 1)
        row = QHBoxLayout()
        open_folder = _button("Open folder", "ghost", self._open_folder)
        delete = _button("Delete session", "danger", self._delete)
        close = _button("Close", "primary", self.accept)
        row.addWidget(open_folder)
        row.addWidget(delete)
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)

    def _open_folder(self) -> None:
        folder = self.controller.notes_folder_for(self.session_id)
        if folder:
            QDesktopServices.openUrl(__import__("PyQt6.QtCore", fromlist=["QUrl"]).QUrl.fromLocalFile(str(folder)))

    def _delete(self) -> None:
        answer = QMessageBox.question(
            self,
            "Delete meeting notes?",
            "This permanently removes notes.md, session.json, transcript.txt and retained audio for this session.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.meeting.delete_session(self.session_id)
            self.controller.refresh_notes_signal()
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Could not delete session", str(exc))


# --------------------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    key_validation_finished = pyqtSignal(bool, str)
    notes_changed = pyqtSignal()

    def __init__(self, controller, bridge: UiBridge, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.bridge = bridge
        self._status: dict[str, Any] = {}
        self._notes: list[dict[str, Any]] = []
        self._confirm_boxes: dict[str, tuple[QMessageBox, Any]] = {}
        self._resolved_confirms: set[str] = set()
        self._quitting = False
        self._tray_notice_shown = False
        self._notes_dirty = True
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(80)
        self._refresh_timer.timeout.connect(lambda: self.refresh(force_notes=False))
        self._pair_timer = QTimer(self)
        self._pair_timer.setInterval(1000)
        self._pair_timer.timeout.connect(self._tick_pairing)
        self._pair_timer.start()
        self._meeting_timer = QTimer(self)
        self._meeting_timer.setInterval(1000)
        self._meeting_timer.timeout.connect(self._tick_meeting)
        self._meeting_timer.start()
        # The phone's eyes are the primary display, so sample the real pointer
        # continuously.  QCursor must be read on the GUI thread; the server
        # safely fans the normalized position out to paired phones.
        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(33)
        self._cursor_timer.timeout.connect(self._sample_cursor)
        self._cursor_timer.start()
        self.setWindowTitle("BerryLink")
        self.setMinimumSize(980, 700)
        self.resize(1140, 780)
        self.setWindowIcon(make_app_icon())
        self._build()
        self._connect_bridge()
        self._build_tray()
        self.key_validation_finished.connect(self._key_validation_done)
        self.notes_changed.connect(lambda: self.refresh(force_notes=True))
        self.refresh(force_notes=True)

    def _sample_cursor(self) -> None:
        """Feed the real desktop pointer to the paired phone's eyes."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        position = QCursor.pos()
        geometry = screen.virtualGeometry()
        if geometry.width() <= 1 or geometry.height() <= 1:
            return
        x = ((position.x() - geometry.left()) / (geometry.width() - 1)) * 2.0 - 1.0
        y = ((position.y() - geometry.top()) / (geometry.height() - 1)) * 2.0 - 1.0
        self.controller.server.set_cursor_position(x, y)

    # ------------------------------------------------------------------ layout

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_sidebar())
        content = QWidget()
        content.setObjectName("content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 20, 24, 0)
        content_layout.setSpacing(12)
        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(1)
        self.page_title = _label("Home", "h1")
        self.page_subtitle = _label("A little companion for your desktop.", "muted")
        title_col.addWidget(self.page_title)
        title_col.addWidget(self.page_subtitle)
        top.addLayout(title_col)
        top.addStretch(1)
        self.header_recording = _label("● RECORDING", "recording")
        self.header_recording.setVisible(False)
        top.addWidget(self.header_recording)
        self.header_server_pill = _pill("Offline", "pillWarn")
        top.addWidget(self.header_server_pill)
        top.addSpacing(8)
        # The emergency control must be reachable from every page, not just
        # the sidebar.  It mirrors the sidebar button and the global hotkey.
        self.header_emergency = _button("STOP", "danger", self._emergency_clicked)
        self.header_emergency.setToolTip("Immediately latch the emergency stop")
        self.header_emergency.setFixedWidth(96)
        self.header_emergency.setMinimumHeight(34)
        top.addWidget(self.header_emergency)
        content_layout.addLayout(top)
        self.stack = QStackedWidget()
        self.pages: list[QScrollArea] = []
        self.pages.append(self._build_home_page())
        self.pages.append(self._build_screen_page())
        self.pages.append(self._build_settings_page())
        # Meeting notes are deliberately deferred from this MVP.  The page is
        # still constructed so existing controller/status code stays intact,
        # but it is never added to the stack, navigation, or tray.
        self._deferred_meeting_page = self._build_notes_page()
        for page in self.pages:
            self.stack.addWidget(page)
        self._wire_toggles()
        content_layout.addWidget(self.stack, 1)
        outer.addWidget(content, 1)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(224)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(12)
        brand = QHBoxLayout()
        brand.addWidget(BerryMark(40))
        brand_col = QVBoxLayout()
        brand_col.setSpacing(0)
        word = _label("BerryLink", "h2")
        brand_col.addWidget(word)
        brand_col.addWidget(_label("desktop companion", "tiny"))
        brand.addLayout(brand_col)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(10)
        self.nav_buttons: list[QPushButton] = []
        names = [("Home", "Home"), ("Screen && control", "Screen & control"), ("Settings", "Settings")]
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, (label, title) in enumerate(names):
            button = _button(label, "nav")
            button.setCheckable(True)
            button.setProperty("pageTitle", title)
            button.clicked.connect(lambda checked=False, idx=i: self._show_page(idx))
            group.addButton(button, i)
            layout.addWidget(button)
            self.nav_buttons.append(button)
        self.nav_buttons[0].setChecked(True)
        layout.addSpacing(6)
        mode_card, mode_col = _card()
        mode_title = _label("AI mode", "tiny", True)
        mode_col.addWidget(mode_title)
        self.mock_switch = QCheckBox("Local mode — no API tokens")
        self.mock_switch.setToolTip(
            "ON: BerryLink runs fully offline and no API tokens are used.\n"
            "OFF: the cloud AI answers (uses your saved AI key)."
        )
        self.mock_switch.toggled.connect(self._set_mock_mode)
        mode_col.addWidget(self.mock_switch)
        self.mock_switch_hint = _label("Off = uses the saved key", "tiny", True)
        mode_col.addWidget(self.mock_switch_hint)
        layout.addWidget(mode_card)
        layout.addSpacing(4)
        self.sidebar_provider = _pill("Local mock mode", "pillWarn")
        layout.addWidget(self.sidebar_provider)
        self.sidebar_lock = _label("TLS pinned · no cloud key on phone", "tiny", True)
        layout.addWidget(self.sidebar_lock)
        layout.addSpacing(8)
        self.emergency_button = _button("Emergency stop", "danger", self._emergency_clicked)
        self.emergency_button.setToolTip("Immediately blocks screen and input actions")
        self.emergency_button.setMinimumHeight(46)
        layout.addWidget(self.emergency_button)
        self.emergency_info = _label("Ctrl+Alt+S (global)", "tiny")
        layout.addWidget(self.emergency_info)
        return sidebar

    def _new_page(self, title: str, subtitle: str) -> tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll, inner, layout = _scroll_page()
        return scroll, inner, layout

    def _build_home_page(self) -> QScrollArea:
        scroll, inner, layout = self._new_page("Home", "")
        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(26, 22, 26, 22)
        hero_layout.setSpacing(18)
        copy = QVBoxLayout()
        copy.setSpacing(7)
        copy.addWidget(_label("Hi, I'm BerryLink.", "heroTitle"))
        copy.addWidget(
            _label(
                "A tiny blueberry who hangs out on your phone and points around your Kali desktop. "
                "Ask by voice or text; your key stays on this computer.",
                "heroSub",
                True,
            )
        )
        pills = QHBoxLayout()
        self.hero_provider = _pill("Local mock mode", "pillWarn")
        self.hero_security = _pill("Pinned TLS", "pillGood")
        self.hero_ai = _pill("AI connected", "pill")
        pills.addWidget(self.hero_provider)
        pills.addWidget(self.hero_security)
        pills.addWidget(self.hero_ai)
        pills.addStretch(1)
        copy.addLayout(pills)
        hero_layout.addLayout(copy, 1)
        layout.addWidget(hero)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        pair_card, pair_layout = _card()
        pair_layout.addWidget(_label("Pair your phone", "h2"))
        pair_layout.addWidget(
            _label(
                "One-tap Connect on the phone (you just allow it here), or the six-digit code window.",
                "muted",
                True,
            )
        )
        self.home_code = _label("Not pairing", "h2")
        self.home_code.setStyleSheet("font-family: 'IBM Plex Mono'; font-size: 22px; letter-spacing: 3px;")
        pair_layout.addWidget(self.home_code)
        self.home_pair_status = _label("", "tiny", True)
        pair_layout.addWidget(self.home_pair_status)
        self.codeless_toggle = QCheckBox("Allow one-tap pairing (desktop shows an Allow prompt)")
        self.codeless_toggle.setChecked(bool(self.controller.config.allow_codeless_pairing))
        self.codeless_toggle.toggled.connect(self._set_codeless_pairing)
        self.codeless_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        pair_layout.addWidget(self.codeless_toggle)
        pair_row = QHBoxLayout()
        pair_row.addWidget(_button("Pair a phone", "primary", self.open_pairing))
        pair_row.addWidget(_button("Copy fingerprint", "ghost", self._copy_fingerprint))
        pair_row.addStretch(1)
        pair_layout.addLayout(pair_row)
        self.home_addresses = _label("", "mono", True)
        pair_layout.addWidget(self.home_addresses)
        grid.addWidget(pair_card, 0, 0)

        status_card, status_layout = _card()
        status_layout.addWidget(_label("Desktop status", "h2"))
        rows = [
            ("Server", "home_server_label"),
            ("Discovery", "home_discovery_label"),
            ("Emergency hotkey", "home_hotkey_label"),
            ("Paired phones", "home_phones_label"),
        ]
        for label, attr in rows:
            row = QHBoxLayout()
            row.addWidget(_label(label, "muted"))
            row.addStretch(1)
            value = _label("—", "h3")
            setattr(self, attr, value)
            row.addWidget(value)
            status_layout.addLayout(row)
        status_layout.addSpacing(4)
        self.home_scan_button = _button("Test screen reading", "ghost", self.test_screen_read)
        status_layout.addWidget(self.home_scan_button)
        grid.addWidget(status_card, 0, 1)

        quick_card, quick_layout = _card()
        quick_layout.addWidget(_label("Quick controls", "h2"))
        self.home_screen_toggle = QCheckBox("Let BerryLink look and point")
        self.home_input_toggle = QCheckBox("Allow input control (off by default)")
        self.home_confirm_toggle = QCheckBox("Confirm consequential actions")
        self.home_screenshot_toggle = QCheckBox("Allow screenshots to the AI provider")
        for checkbox in (
            self.home_screen_toggle,
            self.home_input_toggle,
            self.home_confirm_toggle,
            self.home_screenshot_toggle,
        ):
            quick_layout.addWidget(checkbox)
        quick_layout.addWidget(
            _label("Input control is re-locked every time BerryLink starts. The desktop cursor and automation badge show when a tool is acting.", "tiny", True)
        )
        grid.addWidget(quick_card, 1, 0, 1, 2)
        self.recent_notes_box = None
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        privacy, privacy_layout = _card()
        privacy_layout.addWidget(_label("Privacy, honestly", "h3"))
        privacy_layout.addWidget(
            _label(
                "BerryLink is local-first. Any AI key (Qwen on xkiro, OpenRouter or Gemini) exists only on this desktop. Without a key, "
                "mock mode still launches, discovers, pairs, reads the screen, and points locally. "
                "When you ask with a cloud AI connected, the recorded clip and (if enabled) screen text or a screenshot "
                "go to that provider. Qwen on xkiro (free) is the intended default; Google's free-tier interactions may be "
                "retained for up to one day when you use Gemini. No paid fallback is wired into this app.",
                "muted",
                True,
            )
        )
        layout.addWidget(privacy)
        layout.addStretch(1)
        return scroll

    def _build_screen_page(self) -> QScrollArea:
        scroll, inner, layout = self._new_page("Screen & control", "Look and point by default; input actions are opt-in and guarded.")
        awareness, awareness_layout = _card()
        awareness_layout.addWidget(_label("Screen awareness", "h2"))
        awareness_layout.addWidget(
            _label(
                "Capture happens only when you ask, or when a paired phone asks while screen awareness is on. "
                "OCR runs locally; screen text is sent to Gemini only for an AI ask and only when this setting is enabled. "
                "The little cursor overlay is hidden during capture so it does not appear in the screenshot.",
                "muted",
                True,
            )
        )
        self.screen_page_toggle = QCheckBox("Let BerryLink capture the screen and point")
        self.screen_page_toggle.setToolTip("This does not allow clicking or typing.")
        awareness_layout.addWidget(self.screen_page_toggle)
        self.screen_caps = _label("", "tiny", True)
        awareness_layout.addWidget(self.screen_caps)
        test_row = QHBoxLayout()
        test_row.addWidget(_button("Test local screen reading", "ghost", self.test_screen_read))
        test_row.addWidget(_button("Point at centre", "ghost", self.point_center))
        test_row.addWidget(_button("Stop pointing", "ghost", lambda: self.bridge.stop_pointing()))
        test_row.addStretch(1)
        awareness_layout.addLayout(test_row)
        layout.addWidget(awareness)

        control_card, control_layout = _card()
        control_layout.addWidget(_label("Input control", "h2"))
        self.control_warning = QFrame()
        self.control_warning.setObjectName("warning")
        warn_layout = QVBoxLayout(self.control_warning)
        warn_layout.setContentsMargins(14, 12, 14, 12)
        warn_layout.addWidget(
            _label(
                "Off by default. When enabled, the AI can move the real mouse and type in the focused window. "
                "It cannot run shell commands, open file URLs, enter passwords, or act while the emergency stop is latched. "
                "Every input action is marked with a visible AUTOMATION badge.",
                "muted",
                True,
            )
        )
        control_layout.addWidget(self.control_warning)
        self.screen_input_toggle = QCheckBox("Enable AI input control for this run")
        control_layout.addWidget(self.screen_input_toggle)
        self.screen_confirm_toggle = QCheckBox("Require my confirmation for input actions")
        control_layout.addWidget(self.screen_confirm_toggle)
        self.screen_screenshot_toggle = QCheckBox("Allow opt-in screenshots to the AI provider")
        self.screen_screenshot_toggle.setToolTip("Off by default. Requires the phone to request a screenshot too.")
        control_layout.addWidget(self.screen_screenshot_toggle)
        policy = _label(
            "Allowed: click, type text, approved key shortcuts, scroll, drag, open installed applications, open http(s) URLs. "
            "Refused: arbitrary shell, password-manager typing, embedded-credential URLs, reserved shortcuts and all actions during emergency stop.",
            "tiny",
            True,
        )
        control_layout.addWidget(policy)
        layout.addWidget(control_card)

        emergency_card, emergency_layout = _card()
        emergency_layout.addWidget(_label("Emergency stop", "h2"))
        emergency_layout.addWidget(
            _label(
                "The emergency stop immediately latches input control off and blocks screen and pointing tools. "
                "It also cancels any pending confirmation. Resuming requires a deliberate click; input control stays off until you enable it again.",
                "muted",
                True,
            )
        )
        self.screen_emergency_status = _label("", "h3")
        emergency_layout.addWidget(self.screen_emergency_status)
        emergency_layout.addWidget(_label("Default global shortcut: Ctrl+Alt+S. Change it in Settings → Hotkeys.", "tiny", True))
        layout.addWidget(emergency_card)
        layout.addStretch(1)
        return scroll

    def _build_notes_page(self) -> QScrollArea:
        scroll, inner, layout = self._new_page("Meeting notes", "Explicit recording, local files, and optional transcription after you stop.")
        meeting_card, meeting_layout = _card()
        meeting_head = QHBoxLayout()
        head_text = QVBoxLayout()
        head_text.addWidget(_label("Meeting recorder", "h2"))
        self.meeting_summary = _label("No active meeting recording.", "muted", True)
        head_text.addWidget(self.meeting_summary)
        meeting_head.addLayout(head_text, 1)
        self.meeting_state_pill = _pill("Idle", "pill")
        meeting_head.addWidget(self.meeting_state_pill)
        meeting_layout.addLayout(meeting_head)
        self.meeting_details = _label("", "tiny", True)
        meeting_layout.addWidget(self.meeting_details)
        row = QHBoxLayout()
        self.start_meeting_button = _button("Start recording…", "danger", self.start_meeting)
        self.stop_meeting_button = _button("Stop & transcribe", "primary", self.stop_meeting)
        self.stop_meeting_button.setEnabled(False)
        row.addWidget(self.start_meeting_button)
        row.addWidget(self.stop_meeting_button)
        row.addStretch(1)
        row.addWidget(_button("Open notes folder", "ghost", self.open_notes_folder))
        meeting_layout.addLayout(row)
        self.notes_transcribe_toggle = QCheckBox("Transcribe after stopping (AI provider)")
        self.notes_retain_toggle = QCheckBox("Keep local audio files")
        meeting_layout.addWidget(self.notes_transcribe_toggle)
        meeting_layout.addWidget(self.notes_retain_toggle)
        self._wire_meeting_toggles()
        warning = QLabel(
            "Consent is required before every manual recording. When a phone asks to start recording, "
            "the desktop shows a separate confirmation. Audio is uploaded only after stop, in chunks, and only if transcription is enabled."
        )
        warning.setObjectName("tiny")
        warning.setWordWrap(True)
        meeting_layout.addWidget(warning)
        layout.addWidget(meeting_card)

        list_card, list_layout = _card()
        list_head = QHBoxLayout()
        list_head.addWidget(_label("Saved sessions", "h2"))
        list_head.addStretch(1)
        list_head.addWidget(_button("Refresh", "ghost", lambda: self.refresh(force_notes=True)))
        list_layout.addLayout(list_head)
        self.notes_tree = QTreeWidget()
        self.notes_tree.setColumnCount(4)
        self.notes_tree.setHeaderLabels(["Title", "Started", "Duration", "Status"])
        self.notes_tree.setAlternatingRowColors(True)
        self.notes_tree.setRootIsDecorated(False)
        self.notes_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.notes_tree.setSortingEnabled(False)
        header = self.notes_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.notes_tree.itemDoubleClicked.connect(lambda *_: self.open_selected_note())
        list_layout.addWidget(self.notes_tree, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(_button("View selected", "ghost", self.open_selected_note))
        buttons.addWidget(_button("Delete selected", "ghost", self.delete_selected_note))
        buttons.addStretch(1)
        self.notes_folder_label = _label("", "tiny", True)
        buttons.addWidget(self.notes_folder_label)
        list_layout.addLayout(buttons)
        layout.addWidget(list_card, 1)
        layout.addStretch(1)
        return scroll

    def _build_settings_page(self) -> QScrollArea:
        scroll, inner, layout = self._new_page("Settings", "Keys, network, pairing, hotkeys and privacy.")
        ai_card, ai_layout = _card()
        ai_layout.addWidget(_label("AI brain", "h2"))
        self.ai_status_label = _label("", "muted", True)
        ai_layout.addWidget(self.ai_status_label)

        provider_row = QHBoxLayout()
        provider_row.addWidget(_label("AI provider", "muted"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Qwen on xkiro — free", "xkiro")
        self.provider_combo.addItem("OpenRouter (your key)", "openrouter")
        self.provider_combo.addItem("Gemini free tier", "gemini")
        self.provider_combo.currentIndexChanged.connect(self._provider_selected)
        provider_row.addWidget(self.provider_combo)
        provider_row.addStretch(1)
        ai_layout.addLayout(provider_row)

        model_row = QHBoxLayout()
        self.openrouter_model_edit = QLineEdit()
        self.openrouter_model_edit.setPlaceholderText("OpenRouter model id, e.g. openrouter/auto or …/:free")
        self.save_model_button = _button("Save model", "ghost", self.apply_openrouter_model)
        model_row.addWidget(self.openrouter_model_edit, 1)
        model_row.addWidget(self.save_model_button)
        ai_layout.addLayout(model_row)

        key_row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Paste the xkiro API key for Qwen (stored only on this desktop)")
        self.key_edit.setClearButtonEnabled(True)
        self.save_key_button = _button("Save & validate", "primary", self.save_key)
        self.clear_key_button = _button("Clear saved key", "ghost", self.clear_key)
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.save_key_button)
        key_row.addWidget(self.clear_key_button)
        ai_layout.addLayout(key_row)
        self.key_message = _label("Validation is a lightweight enquiry; it does not spend generation quota.", "tiny", True)
        ai_layout.addWidget(self.key_message)
        self.mock_toggle = QCheckBox("Use local mock mode even if a key is saved")
        self.mock_toggle.toggled.connect(self._set_mock_mode)
        ai_layout.addWidget(self.mock_toggle)
        ai_layout.addWidget(
            _label(
                "The API key lives only on this desktop: never in the APK, protocol messages, or logs. "
                "secret-tool is preferred, otherwise a mode-0600 file is used. With no key, BerryLink still "
                "pairs, reads the screen, points and records in local mock mode.",
                "tiny",
                True,
            )
        )
        docs = QLabel(
            '<a href="https://openrouter.ai/keys">Create an OpenRouter key</a> · '
            '<a href="https://openrouter.ai/models">OpenRouter models</a> · '
            '<a href="https://api.xkiro.com/v1/models">xkiro models</a> · '
            '<a href="https://ai.google.dev/gemini-api/docs">Gemini docs</a>'
        )
        docs.setOpenExternalLinks(True)
        docs.setObjectName("tiny")
        ai_layout.addWidget(docs)
        layout.addWidget(ai_card)

        network_card, network_layout = _card()
        network_layout.addWidget(_label("This desktop", "h2"))
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.name_edit = QLineEdit()
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        form.addRow(_label("Display name", "muted"), self.name_edit)
        form.addRow(_label("Port", "muted"), self.port_spin)
        network_layout.addLayout(form)
        self.network_info = _label("", "mono", True)
        network_layout.addWidget(self.network_info)
        self.mdns_info = _label("", "tiny", True)
        network_layout.addWidget(self.mdns_info)
        self.fingerprint_edit = QLineEdit()
        self.fingerprint_edit.setReadOnly(True)
        self.fingerprint_edit.setObjectName("mono")
        network_layout.addWidget(_label("Certificate SHA-256 pin", "muted"))
        network_layout.addWidget(self.fingerprint_edit)
        row = QHBoxLayout()
        row.addWidget(_button("Save network", "primary", self.save_network))
        row.addWidget(_button("Copy fingerprint", "ghost", self._copy_fingerprint))
        row.addWidget(_button("Restart server", "ghost", self.restart_server))
        row.addWidget(_button("Pair a phone", "ghost", self.open_pairing))
        row.addStretch(1)
        network_layout.addLayout(row)
        layout.addWidget(network_card)

        hotkey_card, hotkey_layout = _card()
        hotkey_layout.addWidget(_label("Global hotkeys (X11)", "h2"))
        form2 = QFormLayout()
        self.emergency_edit = QLineEdit()
        self.overlay_hotkey_edit = QLineEdit()
        self.point_hotkey_edit = QLineEdit()
        form2.addRow(_label("Emergency stop", "muted"), self.emergency_edit)
        form2.addRow(_label("Show / hide cursor", "muted"), self.overlay_hotkey_edit)
        form2.addRow(_label("Demo point", "muted"), self.point_hotkey_edit)
        hotkey_layout.addLayout(form2)
        self.hotkey_status = _label("", "tiny", True)
        hotkey_layout.addWidget(self.hotkey_status)
        hotkey_layout.addWidget(_button("Save & apply hotkeys", "primary", self.save_hotkeys))
        layout.addWidget(hotkey_card)

        devices_card, devices_layout = _card()
        devices_layout.addWidget(_label("Paired phones", "h2"))
        self.devices_box = QVBoxLayout()
        self.devices_box.setSpacing(7)
        devices_layout.addLayout(self.devices_box)
        self.devices_empty = _label("No phones paired yet.", "muted", True)
        devices_layout.addWidget(self.devices_empty)
        layout.addWidget(devices_card)

        about_card, about_layout = _card()
        about_layout.addWidget(_label("About BerryLink", "h2"))
        about_layout.addWidget(
            _label(
                "BerryLink is an independent Android + Kali companion inspired by the public-domain Bluey / Googly Eyes project (Unlicense). "
                "The character and code here are a distinct implementation. Fredoka and IBM Plex Sans are used under the SIL Open Font License; "
                "license texts are bundled in desktop/assets/fonts and Android res/font.",
                "muted",
                True,
            )
        )
        about_layout.addWidget(_label(f"Version 0.1.0 · Desktop id app.berrylink.desktop", "tiny"))
        about_layout.addWidget(_label(f"Config: {self.controller.paths.config_dir}", "tiny", True))
        row = QHBoxLayout()
        row.addWidget(_button("Open app log", "ghost", self.open_log))
        row.addStretch(1)
        row.addWidget(_button("Quit BerryLink", "ghost", self.request_quit))
        about_layout.addLayout(row)
        layout.addWidget(about_card)
        layout.addStretch(1)
        return scroll

    # ------------------------------------------------------------------ wiring

    def _wire_toggles(self) -> None:
        self.home_screen_toggle.toggled.connect(lambda v: self._set_screen_awareness(v, source="home"))
        self.home_input_toggle.toggled.connect(lambda v: self._set_input_control(v))
        self.home_confirm_toggle.toggled.connect(lambda v: self._set_confirm_actions(v))
        self.home_screenshot_toggle.toggled.connect(lambda v: self._set_screenshots(v))
        self.screen_page_toggle.toggled.connect(lambda v: self._set_screen_awareness(v, source="screen"))
        self.screen_input_toggle.toggled.connect(lambda v: self._set_input_control(v))
        self.screen_confirm_toggle.toggled.connect(lambda v: self._set_confirm_actions(v))
        self.screen_screenshot_toggle.toggled.connect(lambda v: self._set_screenshots(v))

    def _wire_meeting_toggles(self) -> None:
        self.notes_transcribe_toggle.toggled.connect(self._save_meeting_toggles)
        self.notes_retain_toggle.toggled.connect(self._save_meeting_toggles)

    def _save_meeting_toggles(self) -> None:
        self.controller.save_meeting_preferences(
            self.notes_transcribe_toggle.isChecked(),
            self.notes_retain_toggle.isChecked(),
        )

    def _connect_bridge(self) -> None:
        self.bridge.runtime_changed.connect(self._schedule_refresh)
        self.bridge.peers_updated.connect(lambda peers: self._schedule_refresh())
        self.bridge.emergency_changed.connect(self._emergency_changed)
        self.bridge.confirm_requested.connect(self.show_confirm)
        self.bridge.confirm_dismissed.connect(self._dismiss_confirm)
        self.bridge.emergency_pressed.connect(self._on_emergency_pressed)
        self.bridge.hotkey_toggle_requested.connect(self._hotkey_toggle_overlay)
        self.bridge.hotkey_demo_point_requested.connect(self.point_center)

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_app_icon(), self)
        self.tray.setToolTip("BerryLink")
        menu = QMenu()
        show_action = QAction("Show BerryLink", self)
        show_action.triggered.connect(self._show_window)
        menu.addAction(show_action)
        pair_action = QAction("Pair a phone…", self)
        pair_action.triggered.connect(self.open_pairing)
        menu.addAction(pair_action)
        menu.addSeparator()
        self.tray_overlay_action = QAction("Show desktop cursor", self)
        self.tray_overlay_action.setCheckable(True)
        self.tray_overlay_action.triggered.connect(self._tray_toggle_overlay)
        menu.addAction(self.tray_overlay_action)
        self.tray_control_action = QAction("Input control", self)
        self.tray_control_action.setCheckable(True)
        self.tray_control_action.triggered.connect(self._set_input_control)
        menu.addAction(self.tray_control_action)
        menu.addSeparator()
        self.tray_emergency_action = QAction("Emergency stop", self)
        self.tray_emergency_action.triggered.connect(self._emergency_clicked)
        menu.addAction(self.tray_emergency_action)
        self.tray_meeting_action = None
        menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.request_quit)
        menu.addAction(quit_action)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self.tray_available:
            self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._show_window()

    def _show_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _tray_toggle_overlay(self, checked: bool) -> None:
        self.controller.set_overlay_visible(checked)
        self.refresh()

    def _hotkey_toggle_overlay(self) -> None:
        self.controller.set_overlay_visible(not bool(self.controller.config.overlay_visible))
        self.refresh()

    def _tray_meeting(self) -> None:
        status = self.controller.meeting.status()
        if status.get("recording"):
            self.stop_meeting()
        else:
            self.start_meeting()

    def _on_emergency_pressed(self) -> None:
        if getattr(self, "tray", None) and self.tray_available:
            self.tray.showMessage(
                "BerryLink emergency stop",
                "Screen and input actions are blocked. Use Resume controls when ready.",
                QSystemTrayIcon.MessageIcon.Critical,
                5000,
            )
        self._show_window()

    def _emergency_clicked(self) -> None:
        if self.controller.control.emergency:
            self.controller.resume_controls()
        else:
            self.controller.emergency_stop()

    def _emergency_changed(self, active: bool) -> None:
        self.refresh()
        for token in list(self._confirm_boxes.keys()):
            self._finish_confirm(token, False)

    def _schedule_refresh(self) -> None:
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    # ------------------------------------------------------------------ refresh

    def refresh(self, force_notes: bool = False) -> None:
        try:
            status = self.controller.status_snapshot()
        except Exception:
            return
        self._status = status
        provider = status.get("provider", "mock")
        if provider == "xkiro":
            self.sidebar_provider.setText("Qwen on xkiro connected")
            self.sidebar_provider.setObjectName("pillGood")
            self.hero_provider.setText("Qwen connected")
            self.hero_provider.setObjectName("pillGood")
            self.hero_ai.setText(status.get("model", "qwen/qwen3-omni-flash:free"))
        elif provider == "openrouter":
            self.sidebar_provider.setText("OpenRouter connected")
            self.sidebar_provider.setObjectName("pillGood")
            self.hero_provider.setText("OpenRouter connected")
            self.hero_provider.setObjectName("pillGood")
            self.hero_ai.setText(status.get("model", "openrouter/auto"))
        elif provider == "gemini":
            self.sidebar_provider.setText("Gemini free tier")
            self.sidebar_provider.setObjectName("pillGood")
            self.hero_provider.setText("Gemini free tier connected")
            self.hero_provider.setObjectName("pillGood")
            self.hero_ai.setText(status.get("model", "gemini-3.8-flash"))
        else:
            self.sidebar_provider.setText("Local mock mode")
            self.sidebar_provider.setObjectName("pillWarn")
            self.hero_provider.setText("Local mock mode")
            self.hero_provider.setObjectName("pillWarn")
            self.hero_ai.setText("No key needed")
        for widget in (self.sidebar_provider, self.hero_provider, self.hero_ai):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        server_running = status.get("server_running", False)
        self.header_server_pill.setText(f"Online :{status.get('port', '—')}" if server_running else "Server offline")
        self.header_server_pill.setObjectName("pillGood" if server_running else "pillWarn")
        self.header_server_pill.style().unpolish(self.header_server_pill)
        self.header_server_pill.style().polish(self.header_server_pill)
        self.home_server_label.setText("Online" if server_running else "Offline")
        self.home_server_label.setStyleSheet("color: #8ff0cf;" if server_running else "color: #ffb1bd;")
        mdns = status.get("mdns", {})
        self.home_discovery_label.setText("mDNS active" if mdns.get("running") else "Manual IP")
        hotkeys = status.get("hotkeys", {})
        self.home_hotkey_label.setText("Active" if hotkeys.get("active") else "On-screen only")
        devices = status.get("devices", [])
        self.home_phones_label.setText(str(len(devices)))
        self.sidebar_lock.setText("TLS pinned · key stays on desktop")
        emergency = status.get("emergency", False)
        self.emergency_button.setText("Resume controls" if emergency else "Emergency stop")
        self.emergency_button.setObjectName("resume" if emergency else "danger")
        self.emergency_button.style().unpolish(self.emergency_button)
        self.emergency_button.style().polish(self.emergency_button)
        self.header_emergency.setText("RESUME" if emergency else "STOP")
        self.header_emergency.setObjectName("resume" if emergency else "danger")
        self.header_emergency.setToolTip(
            "Click to resume screen and input tools"
            if emergency
            else "Immediately latch the emergency stop"
        )
        self.header_emergency.style().unpolish(self.header_emergency)
        self.header_emergency.style().polish(self.header_emergency)
        self.emergency_info.setText(
            "Emergency stop latched" if emergency else str(status.get("emergency_hotkey", "Ctrl+Alt+S")) + " (global)"
        )
        self.screen_emergency_status.setText(
            "EMERGENCY STOP IS ACTIVE — all screen and input tools are blocked."
            if emergency
            else "Armed. Use STOP in the header, the sidebar, or the global shortcut."
        )
        self.screen_emergency_status.setStyleSheet("color: #ff9caa;" if emergency else "color: #8ff0cf;")
        self.header_recording.setVisible(bool(status.get("meeting", {}).get("recording")))

        self._set_checkbox(self.home_screen_toggle, status.get("screen_awareness", True))
        self._set_checkbox(self.screen_page_toggle, status.get("screen_awareness", True))
        self._set_checkbox(self.home_input_toggle, status.get("control_enabled", False))
        self._set_checkbox(self.screen_input_toggle, status.get("control_enabled", False))
        self._set_checkbox(self.home_confirm_toggle, status.get("confirm_actions", True))
        self._set_checkbox(self.screen_confirm_toggle, status.get("confirm_actions", True))
        self._set_checkbox(self.home_screenshot_toggle, status.get("allow_screenshots", False))
        self._set_checkbox(self.screen_screenshot_toggle, status.get("allow_screenshots", False))
        for box in (self.screen_input_toggle, self.screen_page_toggle):
            box.setEnabled(not emergency)
        self.screen_caps.setText(
            f"Capture: {'ready' if status.get('screen_capture') else 'unavailable'} · "
            f"OCR: {status.get('ocr_detail', 'unavailable')}"
        )
        self.tray_overlay_action.setChecked(bool(status.get("overlay_visible", True)))
        if self.tray_meeting_action is not None:
            self.tray_meeting_action.setVisible(False)
        self.tray_control_action.setChecked(bool(status.get("control_enabled", False)))
        self.tray_control_action.setEnabled(not emergency)
        self.tray_emergency_action.setText("Resume controls" if emergency else "Emergency stop")

        self._refresh_pairing()
        self._refresh_meeting(status)
        self._refresh_ai_settings(status)
        self._refresh_network(status)
        self._refresh_hotkeys(status)
        self._refresh_devices(devices)
        if force_notes or len(self._notes) != status.get("notes_count", 0) or self._notes_dirty:
            self.refresh_notes()
        self._refresh_recent_notes()
        self._notes_dirty = False

    def _set_checkbox(self, box: QCheckBox, value: bool) -> None:
        box.blockSignals(True)
        box.setChecked(bool(value))
        box.blockSignals(False)

    def _refresh_pairing(self) -> None:
        pairing = self.controller.pairing.pairing_status()
        self._set_checkbox(self.codeless_toggle, bool(self.controller.config.allow_codeless_pairing))
        if pairing.get("open"):
            code = str(pairing.get("code", ""))
            self.home_code.setText(" ".join(code) if code else "Pairing…")
            self.home_code.setStyleSheet("font-family: 'IBM Plex Mono'; font-size: 22px; letter-spacing: 3px; color: #ffffff;")
            self.home_pair_status.setText(f"Open for {pairing.get('expires_in', 0)}s · {pairing.get('attempts_left', 0)} attempts left")
        else:
            self.home_code.setText("Not pairing")
            self.home_code.setStyleSheet("font-family: 'IBM Plex Sans'; font-size: 16px; color: #9aa5ca;")
            self.home_pair_status.setText("Start a two-minute window when you're ready.")
        server = getattr(self.controller, "server", None)
        port = server.port if server and server.port else self.controller.config.port
        addresses = self.controller.network_addresses(port)
        self.home_addresses.setText("\n".join(addresses) if addresses else "No LAN IPv4 address found; use manual IP entry.")

    def _refresh_meeting(self, status: dict[str, Any]) -> None:
        meeting = status.get("meeting", {})
        session = meeting.get("session") or {}
        recording = meeting.get("recording", False)
        transcribing = meeting.get("transcribing", False)
        if recording:
            self.meeting_state_pill.setText("Recording")
            self.meeting_state_pill.setObjectName("recording")
            title = session.get("title", "Meeting")
            chunks = session.get("chunks", 0)
            started = self.controller.meeting_started_elapsed()
            self.meeting_summary.setText(f"Recording “{title}” · {chunks} chunk(s) saved")
            self.meeting_details.setText(f"Elapsed: {_format_duration(started)} · {meeting.get('message', '')}")
        elif transcribing:
            self.meeting_state_pill.setText("Transcribing")
            self.meeting_state_pill.setObjectName("pillWarn")
            self.meeting_summary.setText("Recording stopped. Transcription is running…")
            self.meeting_details.setText(meeting.get("message", ""))
        elif session:
            self.meeting_state_pill.setText(str(session.get("status", "saved")).title())
            self.meeting_state_pill.setObjectName("pillGood" if session.get("status") == "complete" else "pill")
            self.meeting_summary.setText(f"Last session: {session.get('title', 'Meeting')}")
            self.meeting_details.setText(meeting.get("message", ""))
        else:
            self.meeting_state_pill.setText("Idle")
            self.meeting_state_pill.setObjectName("pill")
            self.meeting_summary.setText("No active meeting recording.")
            self.meeting_details.setText(meeting.get("message", "") if not meeting.get("available") else "Ready when you are.")
        self.meeting_state_pill.style().unpolish(self.meeting_state_pill)
        self.meeting_state_pill.style().polish(self.meeting_state_pill)
        self.start_meeting_button.setEnabled(not recording and not transcribing)
        self.stop_meeting_button.setEnabled(recording)
        if not self._status.get("ai_configured", False):
            self.notes_transcribe_toggle.setEnabled(False)
            if self.notes_transcribe_toggle.isChecked():
                self._set_checkbox(self.notes_transcribe_toggle, False)
        else:
            self.notes_transcribe_toggle.setEnabled(True)
        self._set_checkbox(self.notes_retain_toggle, self.controller.config.meeting_retain_audio)
        self.header_recording.setVisible(recording)
        self.bridge.set_recording(recording, f"{session.get('title', 'Meeting')} · BerryLink")
        self.notes_folder_label.setText(f"Folder: {self.controller.paths.notes_dir}")

    def _refresh_ai_settings(self, status: dict[str, Any]) -> None:
        provider = status.get("provider", "mock")
        setting = self.controller.config.ai_provider
        if provider == "xkiro":
            self.ai_status_label.setText(
                f"Connected to Qwen on xkiro · model {status.get('model')}. "
                "Free endpoint (api.xkiro.com); key stays on this desktop."
            )
        elif provider == "openrouter":
            self.ai_status_label.setText(
                f"Connected to OpenRouter · model {status.get('model')}. "
                "Rate limits and credits follow your OpenRouter account; errors are shown verbatim."
            )
        elif provider == "gemini":
            self.ai_status_label.setText(
                f"Connected to Gemini free tier · model {status.get('model')} · verified 2026-10-21. "
                "No paid fallback is enabled."
            )
        else:
            self.ai_status_label.setText(
                "Local mock mode · no key needed. Voice clips cannot be understood offline, but typing, "
                "OCR, pointing, screenshots, pairing, recording and notes still work."
            )
        target = getattr(self, "_picked_provider", None) or setting
        for value in range(self.provider_combo.count()):
            if self.provider_combo.itemData(value) == target:
                self.provider_combo.blockSignals(True)
                self.provider_combo.setCurrentIndex(value)
                self.provider_combo.blockSignals(False)
                break
        key_field = {
            "openrouter": "has_openrouter_key",
            "xkiro": "has_xkiro_key",
            "gemini": "has_gemini_key",
        }
        target_has_key = bool(status.get(key_field.get(target, key_field["openrouter"])))
        self.clear_key_button.setEnabled(target_has_key)
        prefix = _PROVIDER_PLACEHOLDERS.get(
            target, _PROVIDER_PLACEHOLDERS["openrouter"]
        )
        self.key_edit.setPlaceholderText(
            f"A key is saved. Paste a new one to replace it. ({prefix.split('(')[0].strip()})"
            if target_has_key
            else prefix
        )
        if not self.openrouter_model_edit.hasFocus():
            if target == "xkiro":
                self.openrouter_model_edit.setText(self.controller.config.xkiro_model)
            else:
                self.openrouter_model_edit.setText(self.controller.config.openrouter_model)
        checked = bool(self.controller.config.use_mock_ai)
        self._set_checkbox(self.mock_toggle, checked)
        self._set_checkbox(self.mock_switch, checked)
        self._refresh_mock_hints()
        if not self.name_edit.hasFocus():
            self.name_edit.setText(self.controller.config.display_name)
        if not self.port_spin.hasFocus():
            self.port_spin.setValue(int(self.controller.config.port))

    def _refresh_network(self, status: dict[str, Any]) -> None:
        self.fingerprint_edit.setText(self.controller.identity.pretty_fingerprint)
        addresses = self.controller.network_addresses(status.get("port") or self.controller.config.port)
        self.network_info.setText(
            f"{self.controller.config.display_name}\n"
            + ("\n".join(addresses) if addresses else "No LAN IPv4 address found.")
            + f"\nTLS port: {status.get('port') or 'offline'}"
        )
        mdns = status.get("mdns", {})
        if mdns.get("running"):
            self.mdns_info.setText("mDNS is advertised as “BerryLink”. Android can discover this desktop on the same Wi-Fi.")
        else:
            self.mdns_info.setText(
                "mDNS is unavailable; use manual IP entry on the phone. " + str(mdns.get("error") or "")
            )

    def _refresh_hotkeys(self, status: dict[str, Any]) -> None:
        hotkeys = status.get("hotkeys", {})
        self.emergency_edit.setText(self.controller.config.emergency_hotkey)
        self.overlay_hotkey_edit.setText(self.controller.config.overlay_hotkey)
        self.point_hotkey_edit.setText(self.controller.config.point_hotkey)
        if hotkeys.get("active"):
            self.hotkey_status.setText(
                "Global hotkeys active: " + ", ".join(f"{k} — {v}" for k, v in hotkeys.get("bound", {}).items())
            )
        else:
            self.hotkey_status.setText(
                "Global hotkeys unavailable: " + str(hotkeys.get("error") or "use the sidebar button.")
            )

    def _refresh_devices(self, devices: list[dict[str, Any]]) -> None:
        while self.devices_box.count():
            item = self.devices_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.devices_empty.setVisible(not devices)
        for device in devices:
            row = QHBoxLayout()
            name = _label(device.get("name", "Android phone"), "h3")
            detail = _label(
                f"Last seen {_short_date(device.get('last_seen'))} · id {device.get('id', '')}",
                "tiny",
            )
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(name)
            col.addWidget(detail)
            row.addLayout(col, 1)
            row.addWidget(_button("Revoke", "ghost", lambda checked=False, did=device.get("id"): self.revoke_device(did)))
            wrapper = QWidget()
            wrapper.setLayout(row)
            self.devices_box.addWidget(wrapper)

    def _refresh_recent_notes(self) -> None:
        if self.recent_notes_box is None:
            return
        while self.recent_notes_box.count():
            item = self.recent_notes_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        sessions = self._notes[:3]
        if not sessions:
            self.recent_notes_box.addWidget(_label("No notes yet. Start a meeting recording when everyone has consented.", "muted", True))
            return
        for session in sessions:
            row = QHBoxLayout()
            title = _label(session.get("title", "Meeting"), "h3")
            detail = _label(
                f"{_short_date(session.get('started_at'))} · {_format_duration(session.get('duration_seconds', 0))} · {session.get('status', '')}",
                "tiny",
            )
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(title)
            col.addWidget(detail)
            row.addLayout(col, 1)
            row.addWidget(_button("View", "ghost", lambda checked=False, sid=session.get("id"): self.open_note(sid)))
            wrapper = QWidget()
            wrapper.setLayout(row)
            self.recent_notes_box.addWidget(wrapper)

    def refresh_notes(self) -> None:
        try:
            sessions = self.controller.meeting.list_sessions()
        except Exception:
            sessions = []
        self._notes = sessions
        selected = None
        current = self.notes_tree.currentItem()
        if current:
            selected = current.data(0, Qt.ItemDataRole.UserRole)
        self.notes_tree.clear()
        for session in sessions:
            item = QTreeWidgetItem(
                [
                    str(session.get("title", "Meeting")),
                    _short_date(session.get("started_at")),
                    _format_duration(session.get("duration_seconds", 0)),
                    str(session.get("status", "")).title(),
                ]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, session.get("id"))
            self.notes_tree.addTopLevelItem(item)
            if session.get("id") == selected:
                self.notes_tree.setCurrentItem(item)
        self._notes_dirty = False
        self._refresh_recent_notes()

    # ------------------------------------------------------------------ actions

    def _show_page(self, index: int) -> None:
        if not 0 <= index < len(self.pages):
            return
        self.stack.setCurrentIndex(index)
        titles = [
            ("Home", "A little companion for your desktop."),
            ("Screen & control", "Look and point by default; input actions are opt-in and guarded."),
            ("Settings", "Keys, network, pairing, hotkeys and privacy."),
        ]
        self.page_title.setText(titles[index][0])
        self.page_subtitle.setText(titles[index][1])
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)
        self.refresh()

    def _set_codeless_pairing(self, value: bool) -> None:
        try:
            self.controller.set_allow_codeless_pairing(bool(value))
        except Exception as exc:
            QMessageBox.warning(self, "Setting not saved", str(exc))
            return
        self.refresh()

    def open_pairing(self) -> None:
        if not self.controller.server_running:
            QMessageBox.warning(
                self,
                "Server offline",
                "The desktop server is offline. Fix the port in Settings and restart the server before pairing.",
            )
            return
        self.controller.start_pairing()
        dialog = PairingDialog(self.controller, self)
        dialog.exec()
        self.refresh()

    def _tick_pairing(self) -> None:
        if self.isVisible():
            self._refresh_pairing()

    def _tick_meeting(self) -> None:
        if self._status.get("meeting", {}).get("recording"):
            self._refresh_meeting(self._status)

    def _copy_fingerprint(self) -> None:
        QApplication.clipboard().setText(self.controller.identity.pretty_fingerprint)
        if getattr(self, "tray", None) and self.tray_available:
            self.tray.showMessage("Fingerprint copied", "The certificate pin is on your clipboard.", QSystemTrayIcon.MessageIcon.Information, 2500)

    def _set_screen_awareness(self, value: bool, source: str) -> None:
        self.controller.set_screen_awareness(bool(value))
        self._set_checkbox(self.home_screen_toggle, bool(value))
        self._set_checkbox(self.screen_page_toggle, bool(value))
        self.refresh()

    def _set_input_control(self, value: bool) -> None:
        if value:
            if self.controller.control.emergency:
                QMessageBox.warning(self, "Emergency stop active", "Resume controls before enabling input control.")
                self.refresh()
                return
            answer = QMessageBox.warning(
                self,
                "Enable AI input control?",
                "BerryLink will be able to move the mouse and type in the focused window. "
                "It still asks for confirmation unless you turn that off, and cannot use a shell. "
                "This permission lasts only for this run.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.refresh()
                return
        self.controller.set_input_control(bool(value))
        self.refresh()

    def _set_confirm_actions(self, value: bool) -> None:
        self.controller.set_confirm_actions(bool(value))
        self._set_checkbox(self.home_confirm_toggle, bool(value))
        self._set_checkbox(self.screen_confirm_toggle, bool(value))

    def _set_mock_mode(self, value: bool) -> None:
        try:
            self.controller.set_mock_mode(bool(value))
        except Exception as exc:
            QMessageBox.warning(self, "Could not change AI mode", str(exc))
        checked = bool(self.controller.config.use_mock_ai)
        for box in (self.mock_switch, self.mock_toggle):
            if box.isChecked() != checked:
                box.blockSignals(True)
                box.setChecked(checked)
                box.blockSignals(False)
        self._refresh_mock_hints()
        self.refresh()

    def _refresh_mock_hints(self) -> None:
        on = bool(self.controller.config.use_mock_ai)
        self.mock_switch_hint.setText(
            "ON: nothing leaves this computer" if on else "Off = uses the saved key"
        )

    def _set_screenshots(self, value: bool) -> None:
        if value:
            answer = QMessageBox.warning(
                self,
                "Allow screenshots to the AI provider?",
                "A screenshot of your entire desktop will be sent only when a paired phone explicitly asks for one. "
                "Screen text is already sent for screen-aware asks. The API key stays on this desktop. "
                "With Gemini's free tier, content may be retained for up to one day by Google.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.refresh()
                return
        self.controller.set_allow_screenshots(bool(value))
        self._set_checkbox(self.home_screenshot_toggle, bool(value))
        self._set_checkbox(self.screen_screenshot_toggle, bool(value))

    def test_screen_read(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            text = self.controller.read_screen_for_test()
        except Exception as exc:
            QMessageBox.warning(self, "Screen reading failed", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        TextDialog("Local screen reading", text, self).exec()

    def point_center(self) -> None:
        snapshot = self.controller.screen.latest()
        if snapshot is None:
            try:
                snapshot = self.controller.screen.get(force=True)
            except Exception as exc:
                QMessageBox.warning(self, "Pointing failed", str(exc))
                return
        self.bridge.point_at(
            snapshot.width // 2,
            snapshot.height // 2,
            "centre of screen",
            "Right here, in the middle!",
            None,
        )

    def start_meeting(self) -> None:
        try:
            dialog = MeetingConsentDialog(self.controller, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._notes_dirty = True
                self.refresh(force_notes=True)
        except Exception as exc:
            QMessageBox.warning(self, "Recording failed", str(exc))

    def stop_meeting(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.controller.meeting.stop()
        except Exception as exc:
            QMessageBox.warning(self, "Could not stop recording", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
        self._notes_dirty = True
        self.refresh(force_notes=True)

    def open_notes_folder(self) -> None:
        from PyQt6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.controller.paths.notes_dir)))

    def open_log(self) -> None:
        from PyQt6.QtCore import QUrl

        if self.controller.paths.log_file.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.controller.paths.log_file)))
        else:
            QMessageBox.information(self, "No log yet", str(self.controller.paths.log_file))

    def open_selected_note(self) -> None:
        item = self.notes_tree.currentItem()
        if item:
            self.open_note(item.data(0, Qt.ItemDataRole.UserRole))

    def open_note(self, session_id: str | None) -> None:
        if not session_id:
            return
        NotesDetailDialog(self.controller, str(session_id), self).exec()
        self.refresh(force_notes=True)

    def delete_selected_note(self) -> None:
        item = self.notes_tree.currentItem()
        if not item:
            return
        sid = item.data(0, Qt.ItemDataRole.UserRole)
        answer = QMessageBox.question(
            self,
            "Delete meeting notes?",
            "This permanently deletes this session's notes, transcript and retained audio.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.controller.meeting.delete_session(str(sid))
            self.refresh(force_notes=True)
        except Exception as exc:
            QMessageBox.warning(self, "Could not delete notes", str(exc))

    def revoke_device(self, device_id: str | None) -> None:
        if not device_id:
            return
        answer = QMessageBox.question(
            self,
            "Revoke phone?",
            "That phone will be disconnected and its token deleted. You will need to pair it again.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.controller.revoke_device(str(device_id))
        self.refresh()

    # ------------------------------------------------------------------ AI key

    def _pick_provider(self, provider: str = "openrouter") -> None:
        """Select a provider in the combo without re-triggering _provider_selected."""
        for value in range(self.provider_combo.count()):
            if self.provider_combo.itemData(value) == provider:
                self.provider_combo.blockSignals(True)
                self.provider_combo.setCurrentIndex(value)
                self.provider_combo.blockSignals(False)
                break
        self._picked_provider = provider

    def _provider_selected(self, _index: int) -> None:
        provider = self.provider_combo.currentData() or "openrouter"
        self._picked_provider = provider
        position = _PROVIDER_PLACEHOLDERS.get(provider)
        if position:
            self.key_edit.setPlaceholderText(position)
        if not getattr(self, "_status", None) or not hasattr(self, "controller"):
            return  # construction-time: nothing to switch yet
        try:
            if self.controller.has_provider_key(provider):
                active = getattr(self.controller.ai_holder.get(), "provider", "mock")
                if active != provider:
                    self.controller.set_ai_provider(provider)
                    self.key_message.setText(
                        f"Active provider is now {provider.title()} (no new key needed)."
                    )
                    self.key_message.setStyleSheet("color: #8ff0cf;")
                    self.refresh()
                else:
                    if provider == "openrouter":
                        hint = (
                            f"OpenRouter is already active · model "
                            f"{self.controller.config.openrouter_model}. Paste a key only to replace it."
                        )
                    elif provider == "xkiro":
                        hint = (
                            f"Qwen on xkiro is already active · model "
                            f"{self.controller.config.xkiro_model}. Paste a key only to replace it."
                        )
                    else:
                        hint = "Gemini is already active. Paste a key only to replace it."
                    self.key_message.setText(hint)
                    self.key_message.setStyleSheet("")
            else:
                provider_names = {
                    "xkiro": "xkiro (Qwen)",
                    "openrouter": "OpenRouter",
                    "gemini": "Gemini",
                }
                self.key_message.setText(
                    f"No {provider_names.get(provider, provider)} key saved yet — paste one below "
                    "and press Save & validate."
                )
                self.key_message.setStyleSheet("")
        except Exception:
            return

    def apply_openrouter_model(self) -> None:
        provider = getattr(self, "_picked_provider", "openrouter")
        model = self.openrouter_model_edit.text().strip()
        if not model:
            QMessageBox.information(self, "Model needed", f"Type a {provider or 'openrouter'} model id.")
            return
        try:
            if provider == "xkiro":
                self.controller.save_xkiro_model(model)
            else:
                self.controller.save_openrouter_model(model)
        except Exception as exc:
            QMessageBox.warning(self, "Model not saved", str(exc))
            return
        self.key_message.setText(f"{provider.title()} model set to {model}.")
        self.key_message.setStyleSheet("color: #8ff0cf;")
        self._pick_provider(provider)
        self.refresh()

    def save_key(self) -> None:
        key = self.key_edit.text().strip()
        if not key:
            QMessageBox.information(
                self,
                "Paste a key",
                "Paste an API key first. Use the list above to choose Qwen (xkiro), OpenRouter or Gemini.",
            )
            return
        provider = getattr(self, "_picked_provider", "openrouter")
        self.save_key_button.setEnabled(False)
        self.key_message.setText("Validating the key — this does not spend generation quota…")
        threading.Thread(
            target=self._validate_key_worker,
            args=(key, provider),
            name="berrylink-key-check",
            daemon=True,
        ).start()

    def _validate_key_worker(self, key: str, provider: str = "openrouter") -> None:
        try:
            if provider == "gemini":
                result = self.controller.save_gemini_key(key)
            elif provider == "xkiro":
                result = self.controller.save_xkiro_key(key)
            else:
                result = self.controller.save_openrouter_key(key)
            self.key_validation_finished.emit(bool(result.get("ok")), str(result.get("message", "")))
        except Exception as exc:
            self.key_validation_finished.emit(False, f"Key validation failed: {type(exc).__name__}")

    def _key_validation_done(self, ok: bool, message: str) -> None:
        self.save_key_button.setEnabled(True)
        self.key_message.setText(message)
        self.key_message.setStyleSheet("color: #8ff0cf;" if ok else "color: #ffb1bd;")
        if ok:
            self.key_edit.clear()
        self.refresh()

    def clear_key(self) -> None:
        provider = getattr(self, "_picked_provider", "openrouter")
        answer = QMessageBox.question(
            self,
            "Remove saved key?",
            "The desktop will return to local mock mode while no other key is saved. "
            "The Android app continues to work without a key.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            if provider == "gemini":
                self.controller.clear_gemini_key()
            elif provider == "xkiro":
                self.controller.clear_xkiro_key()
            else:
                self.controller.clear_openrouter_key()
            self.key_message.setText("API key removed. Local mock mode is active while no other key is saved.")
            self.key_message.setStyleSheet("color: #ffd596;")
            self.refresh()

    # ------------------------------------------------------------------ settings

    def save_network(self) -> None:
        try:
            self.controller.save_network_settings(self.name_edit.text().strip(), int(self.port_spin.value()))
        except Exception as exc:
            QMessageBox.warning(self, "Settings not saved", str(exc))
            return
        self.refresh()
        if int(self.controller.config.port) != int(self._status.get("port") or 0):
            QMessageBox.information(
                self,
                "Restart required",
                "The display name is updated. The new port will be used after you restart the desktop server.",
            )

    def restart_server(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.controller.restart_server()
        except Exception as exc:
            QMessageBox.warning(self, "Server could not restart", str(exc))
        finally:
            QApplication.restoreOverrideCursor()
        self.refresh()

    def save_hotkeys(self) -> None:
        values = (
            self.emergency_edit.text().strip(),
            self.overlay_hotkey_edit.text().strip(),
            self.point_hotkey_edit.text().strip(),
        )
        if not values[0]:
            QMessageBox.warning(self, "Emergency hotkey required", "Set a global emergency stop hotkey.")
            return
        self.controller.save_hotkeys(*values)
        self.refresh()

    def request_quit(self) -> None:
        meeting = self._status.get("meeting", {})
        if meeting.get("recording") or meeting.get("transcribing"):
            answer = QMessageBox.question(
                self,
                "Quit BerryLink?",
                "A meeting recording or transcription is active. Stop/save and quit? "
                "Any unfinished transcription will be marked interrupted and local audio will remain.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._quitting = True
        self.controller.request_quit()

    # ------------------------------------------------------------------ confirmations

    def show_confirm(self, token: str, title: str, description: str, timeout: float) -> None:
        if not self.isVisible():
            self._show_window()
        box = QMessageBox(self)
        box.setWindowTitle("BerryLink needs your permission")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(title)
        box.setInformativeText(description + "\n\nGlobal emergency stop: " + self.controller.config.emergency_hotkey)
        allow = box.addButton("Allow once", QMessageBox.ButtonRole.AcceptRole)
        deny = box.addButton("Deny", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(deny)
        box.setWindowModality(Qt.WindowModality.ApplicationModal)
        box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._confirm_boxes[token] = (box, allow)
        box.buttonClicked.connect(lambda button, tok=token, allow_btn=allow: self._finish_confirm(tok, button is allow_btn))
        box.finished.connect(lambda _result, tok=token: self._finish_confirm(tok, False))
        box.open()
        QTimer.singleShot(int(max(5.0, timeout) * 1000) + 1200, lambda: self._dismiss_confirm(token))

    def _finish_confirm(self, token: str, approved: bool) -> None:
        if token in self._resolved_confirms:
            return
        self._resolved_confirms.add(token)
        item = self._confirm_boxes.pop(token, None)
        self.bridge.resolve_confirm(token, approved)
        if item:
            box, _ = item
            try:
                box.close()
            except Exception:
                pass

    def _dismiss_confirm(self, token: str) -> None:
        item = self._confirm_boxes.pop(token, None)
        if item:
            box, _ = item
            try:
                box.close()
            except Exception:
                pass
        if token not in self._resolved_confirms:
            self._resolved_confirms.add(token)
            self.bridge.resolve_confirm(token, False)

    # ------------------------------------------------------------------ close/tray

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._quitting or not getattr(self, "tray_available", False):
            event.accept()
            if not self._quitting:
                self.controller.request_quit()
            return
        event.ignore()
        self.hide()
        if not self._tray_notice_shown:
            self._tray_notice_shown = True
            self.tray.showMessage(
                "BerryLink is still running",
                "The character and desktop server are active in the tray. Use Quit in the tray to stop everything.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
