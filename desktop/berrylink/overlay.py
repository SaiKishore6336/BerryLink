"""The compact, click-through BerryLink cursor overlay.

The phone owns the character and its big face.  The desktop only shows a
small two-eyed blueberry cursor that appears where it is told to point.  It
never follows, watches, or reads the real mouse pointer: pointing is an
explicit tool action, not continuous cursor tracking.
"""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Optional

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QWidget


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class BerryOverlay(QWidget):
    """Frameless, transparent, always-on-top, mouse-transparent pointer.

    This is intentionally *not* a desktop character.  It is a small cursor
    with two eyes and a short speech bubble.  It only moves when a pointing
    tool asks it to; the real PC pointer is never inspected.
    """

    POINTER_SIZE = 62.0
    DOCK_MARGIN_X = 96.0
    DOCK_MARGIN_Y = 108.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWindowTitle("BerryLink cursor")

        self._screen = QGuiApplication.primaryScreen()
        self._apply_screen_geometry()
        self._visible_pref = True
        self._hidden_for_capture = False
        self._asleep = False
        self._mode = "dock"
        self._pos = self._dock_point()
        self._target = QPointF(self._pos)
        self._vel = QPointF(0, 0)
        self._point_target: Optional[QPointF] = None
        self._point_label = ""
        self._highlight: Optional[QRectF] = None
        self._bubble = ""
        self._bubble_mood = "happy"
        self._bubble_until = 0.0
        self._action = ""
        self._action_until = 0.0
        self._emergency = False
        self._recording = False
        self._recording_label = "Recording"
        self._last_tick = time.monotonic()
        self._t0 = time.monotonic()
        self._font_family = "Fredoka"
        self._text_family = "IBM Plex Sans"
        self._xdisplay = None
        self._x11_shape_attempted = False
        self._needs_frame = True
        self._paint_count = 0
        self._log = logging.getLogger("berrylink.overlay")
        self._timer = QTimer(self)
        # The pointer is small.  This timer only repaints while it is moving,
        # pointing, recording, or showing a fresh action/bubble.
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # --------------------------------------------------------------- geometry

    def _apply_screen_geometry(self) -> None:
        screen = self._screen or QGuiApplication.primaryScreen()
        if screen is not None:
            self._screen = screen
            self.setGeometry(screen.geometry())

    def _dock_point(self) -> QPointF:
        return QPointF(
            max(self.DOCK_MARGIN_X, self.width() - self.DOCK_MARGIN_X),
            max(self.DOCK_MARGIN_Y, self.height() - self.DOCK_MARGIN_Y),
        )

    def _global_point(self, point: QPoint) -> QPointF:
        return QPointF(point.x() - self.geometry().x(), point.y() - self.geometry().y())

    def _clamp_pos(self, point: QPointF) -> QPointF:
        margin = self.POINTER_SIZE * 0.8
        return QPointF(
            max(margin, min(self.width() - margin, point.x())),
            max(margin, min(self.height() - margin, point.y())),
        )

    def _pointer_spot_for_target(self, target: QPointF) -> QPointF:
        """Place the little cursor beside a target, never on top of it."""
        offset = QPointF(-86.0, -82.0)
        if target.x() < 150:
            offset.setX(78.0)
        if target.y() < 150:
            offset.setY(74.0)
        return self._clamp_pos(target + offset)

    # ---------------------------------------------------------------- public

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._install_x11_clickthrough)
        QTimer.singleShot(80, self._install_x11_clickthrough)
        self._needs_frame = True

    def _install_x11_clickthrough(self) -> None:
        """Make the whole X11 window transparent to input.

        Qt's WindowTransparentForInput flag is not honoured by every X11
        window manager.  An empty X Shape input region is authoritative.
        """
        if not os.environ.get("DISPLAY"):
            return
        if self._xdisplay is not None:
            return
        if self._x11_shape_attempted:
            return
        self._x11_shape_attempted = True
        try:
            from Xlib import X, display
            from Xlib.ext import shape

            xdisplay = display.Display()
            if not xdisplay.has_extension("SHAPE"):
                xdisplay.close()
                self._log.warning("X SHAPE extension unavailable; click-through may be incomplete")
                return
            window = xdisplay.create_resource_object("window", int(self.winId()))
            window.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, [])
            xdisplay.flush()
            self._xdisplay = xdisplay
            self._log.info("Cursor click-through installed via X Shape input region")
        except Exception as exc:
            self._log.warning("Could not install X11 click-through: %s", type(exc).__name__)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._xdisplay is not None:
            try:
                self._xdisplay.close()
            except Exception:
                pass
            self._xdisplay = None
        self._timer.stop()
        super().closeEvent(event)

    def set_visible_preference(self, visible: bool) -> None:
        self._visible_pref = bool(visible)
        if self._visible_pref and not self._hidden_for_capture:
            self.show()
            self.raise_()
        elif not self._visible_pref:
            self.hide()

    def set_follow_pointer(self, follow: bool) -> None:
        """Compatibility shim.

        BerryLink deliberately does not follow the PC pointer.  Older config
        files may still contain this flag; it is ignored so the desktop cursor
        can never start shadowing the mouse.
        """
        return

    def set_emergency(self, active: bool) -> None:
        changed = active != self._emergency
        self._emergency = bool(active)
        self._asleep = False
        if active:
            self._mode = "dock"
            self._target = self._dock_point()
            self._point_target = None
            self._highlight = None
            self._bubble = "Emergency stop. I won't touch anything until you resume."
            self._bubble_mood = "error"
            self._bubble_until = time.monotonic() + 30
            self._action = ""
        elif changed:
            self._bubble = "Controls are unlocked. Input control is still off until you enable it."
            self._bubble_mood = "happy"
            self._bubble_until = time.monotonic() + 12
        self._needs_frame = True
        self.update()

    def set_recording(self, active: bool, label: str = "Recording") -> None:
        self._recording = bool(active)
        self._recording_label = label[:60] or "Recording"
        self._needs_frame = True
        self.update()

    def set_asleep(self, asleep: bool) -> None:
        self._asleep = bool(asleep)
        if asleep:
            self._mode = "dock"
            self._target = self._dock_point()
            self._point_target = None
            self._highlight = None
            self._bubble = ""
        self._needs_frame = True
        self.update()

    def toggle_visible(self) -> None:
        self.set_visible_preference(not self._visible_pref)

    @pyqtSlot()
    def hide_for_capture(self) -> None:
        if not self.isVisible():
            self._hidden_for_capture = False
            return
        self._hidden_for_capture = True
        self.hide()
        QApplication.processEvents()

    @pyqtSlot()
    def show_after_capture(self) -> None:
        self._hidden_for_capture = False
        if self._visible_pref:
            self.show()
            self.raise_()

    def demo_point(self) -> None:
        self.point_at(
            max(1, self.width() // 2),
            max(1, self.height() // 2),
            "the middle of your screen",
            "Right here, in the middle!",
        )

    # --------------------------------------------------------------- slots

    @pyqtSlot(str, str)
    def show_caption(self, text: str, mood: str = "happy") -> None:
        self._asleep = False
        self._bubble = " ".join((text or "").split())[:380]
        self._bubble_mood = mood or "happy"
        self._bubble_until = time.monotonic() + 38
        self._needs_frame = True
        self.update()

    @pyqtSlot(int, int, str, str, object)
    def point_at(self, x: int, y: int, label: str = "", bubble: str = "", rect=None) -> None:
        self._asleep = False
        target_global = QPoint(int(x), int(y))
        local = self._global_point(target_global)
        self._mode = "point"
        self._point_target = local
        self._point_label = (label or "")[:80]
        self._target = self._pointer_spot_for_target(local)
        self._bubble = " ".join((bubble or label or "").split())[:300]
        self._bubble_mood = "pointing"
        self._bubble_until = time.monotonic() + 65
        if isinstance(rect, (tuple, list)) and len(rect) == 4:
            try:
                rx, ry, rw, rh = (float(v) for v in rect)
                self._highlight = QRectF(
                    rx - self.geometry().x(),
                    ry - self.geometry().y(),
                    max(8.0, rw),
                    max(8.0, rh),
                )
            except (TypeError, ValueError):
                self._highlight = None
        else:
            self._highlight = None
        self._needs_frame = True
        self.update()

    @pyqtSlot()
    def stop_pointing(self) -> None:
        self._mode = "dock"
        self._point_target = None
        self._highlight = None
        self._bubble = ""
        self._bubble_until = 0
        self._action = ""
        self._target = self._dock_point()
        self._needs_frame = True
        self.update()

    @pyqtSlot()
    def sleep(self) -> None:
        self.set_asleep(True)

    @pyqtSlot(str)
    def show_action(self, label: str) -> None:
        self._action = (label or "ACTION")[:32].upper()
        self._action_until = time.monotonic() + 8
        self._needs_frame = True
        self.update()

    @pyqtSlot()
    def clear_action(self) -> None:
        self._action = ""
        self._needs_frame = True
        self.update()

    # ---------------------------------------------------------------- motion

    def _tick(self) -> None:
        now = time.monotonic()
        dt = max(0.001, min(0.06, now - self._last_tick))
        self._last_tick = now

        if self._mode == "dock":
            self._target = self._dock_point()
        if self._asleep and self._mode == "dock":
            self._target = self._dock_point()

        dx = self._target.x() - self._pos.x()
        dy = self._target.y() - self._pos.y()
        # A short, slightly springy flight makes the cursor feel alive without
        # wandering around the desktop on its own.
        ax = dx * 120.0 - self._vel.x() * 20.0
        ay = dy * 120.0 - self._vel.y() * 20.0
        self._vel = QPointF(self._vel.x() + ax * dt, self._vel.y() + ay * dt)
        self._pos = QPointF(self._pos.x() + self._vel.x() * dt, self._pos.y() + self._vel.y() * dt)
        if abs(dx) < 0.12 and abs(dy) < 0.12:
            self._pos = QPointF(self._target)
            self._vel = QPointF(0, 0)

        if self._bubble_until and now > self._bubble_until:
            self._bubble = ""
            self._bubble_until = 0
            if self._mode == "point":
                self.stop_pointing()
                return
        if self._action and now > self._action_until:
            self._action = ""
            self._needs_frame = True

        moving = abs(self._vel.x()) > 0.4 or abs(self._vel.y()) > 0.4 or (abs(dx) + abs(dy)) > 0.25
        animated = bool(
            self._asleep
            or self._point_target is not None
            or self._recording
            or self._emergency
            or self._action
            or self._bubble
        )
        if moving or animated or self._needs_frame:
            self._needs_frame = False
            self.update()

    # --------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:  # noqa: N802
        self._paint_count += 1
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        now = time.monotonic()
        t = now - self._t0

        if self._point_target is not None:
            self._paint_tether(painter, t)
        if self._highlight is not None:
            self._paint_highlight(painter, t)
        self._paint_cursor(painter, t)
        if self._bubble:
            self._paint_bubble(painter)
        if self._action:
            self._paint_action(painter)
        if self._recording:
            self._paint_recording(painter, t)
        if self._emergency:
            self._paint_emergency_badge(painter)
        painter.end()

    def _paint_tether(self, painter: QPainter, t: float) -> None:
        target = self._point_target
        if target is None:
            return
        start = QPointF(self._pos.x() + 17, self._pos.y() + 15)
        pen = QPen(QColor(167, 205, 255, 145), 1.6)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setDashPattern([3.0, 6.0])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        mid = QPointF((start.x() + target.x()) / 2, min(start.y(), target.y()) - 22)
        path = QPainterPath(start)
        path.quadTo(mid, target)
        painter.drawPath(path)

        pulse = (math.sin(t * 4.0) + 1.0) / 2.0
        painter.setPen(QPen(QColor(126, 190, 255, 150 + int(70 * pulse)), 1.8))
        painter.setBrush(QColor(122, 174, 255, 18 + int(22 * pulse)))
        painter.drawEllipse(target, 16 + 7 * pulse, 16 + 7 * pulse)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(238, 247, 255, 235))
        painter.drawEllipse(target, 4, 4)
        painter.setBrush(QColor(124, 160, 255, 220))
        painter.drawEllipse(target, 1.7, 1.7)

    def _paint_highlight(self, painter: QPainter, t: float) -> None:
        rect = self._highlight
        if rect is None or rect.isEmpty():
            return
        padded = rect.adjusted(-5, -4, 5, 4)
        pulse = (math.sin(t * 3.2) + 1.0) / 2.0
        painter.setPen(QPen(QColor(126, 191, 255, 180 + int(50 * pulse)), 1.4 + pulse))
        painter.setBrush(QColor(92, 126, 255, 18 + int(12 * pulse)))
        painter.drawRoundedRect(padded, 8, 8)
        if self._point_label:
            font = QFont(self._text_family, 9)
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            metrics = QFontMetrics(font)
            text = self._point_label
            width = min(metrics.horizontalAdvance(text) + 16, 260)
            tag = QRectF(padded.left(), max(2, padded.top() - 23), width, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(18, 25, 55, 235))
            painter.drawRoundedRect(tag, 9, 9)
            painter.setPen(QColor(215, 230, 255))
            painter.drawText(
                tag.adjusted(8, 0, -6, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(width - 14)),
            )

    def _paint_cursor(self, painter: QPainter, t: float) -> None:
        cx, cy = self._pos.x(), self._pos.y()
        s = self.POINTER_SIZE
        asleep = self._asleep
        if asleep:
            cy += math.sin(t * 1.6) * 1.2

        # soft ground shadow
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 8, 22, 95))
        painter.drawEllipse(QPointF(cx + 2, cy + s * 0.43), s * 0.31, s * 0.09)

        # little pointed tail makes the berry read as a cursor
        tail = QPainterPath()
        tail.moveTo(cx - s * 0.18, cy + s * 0.30)
        tail.cubicTo(cx - s * 0.38, cy + s * 0.42, cx - s * 0.40, cy + s * 0.55, cx - s * 0.28, cy + s * 0.58)
        tail.cubicTo(cx - s * 0.13, cy + s * 0.58, cx - s * 0.04, cy + s * 0.46, cx + s * 0.02, cy + s * 0.34)
        tail.closeSubpath()
        painter.setBrush(QColor("#2d479f"))
        painter.setPen(QPen(QColor(20, 32, 84, 245), 1.8))
        painter.drawPath(tail)

        body = QPainterPath()
        body.moveTo(cx, cy - s * 0.50)
        body.cubicTo(cx - s * 0.34, cy - s * 0.50, cx - s * 0.50, cy - s * 0.22, cx - s * 0.47, cy + s * 0.06)
        body.cubicTo(cx - s * 0.44, cy + s * 0.31, cx - s * 0.20, cy + s * 0.43, cx, cy + s * 0.43)
        body.cubicTo(cx + s * 0.22, cy + s * 0.43, cx + s * 0.45, cy + s * 0.29, cx + s * 0.47, cy + s * 0.04)
        body.cubicTo(cx + s * 0.49, cy - s * 0.24, cx + s * 0.32, cy - s * 0.50, cx, cy - s * 0.50)
        gradient = QRadialGradient(
            QPointF(cx - s * 0.19, cy - s * 0.25), s * 0.82
        )
        gradient.setColorAt(0.0, QColor("#a5b9ff"))
        gradient.setColorAt(0.32, QColor("#7291f4"))
        gradient.setColorAt(0.72, QColor("#3f5bd0"))
        gradient.setColorAt(1.0, QColor("#263a9b"))
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(QColor(20, 31, 86, 250), 2.0))
        painter.drawPath(body)

        # leaf
        painter.setPen(QPen(QColor(22, 91, 73), 1.4))
        painter.setBrush(QColor("#4fd1a1"))
        leaf = QPainterPath()
        leaf.moveTo(cx, cy - s * 0.48)
        leaf.cubicTo(cx - s * 0.06, cy - s * 0.66, cx - s * 0.27, cy - s * 0.68, cx - s * 0.37, cy - s * 0.58)
        leaf.cubicTo(cx - s * 0.25, cy - s * 0.43, cx - s * 0.11, cy - s * 0.43, cx, cy - s * 0.48)
        painter.drawPath(leaf)

        # glossy highlight
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawEllipse(QPointF(cx - s * 0.21, cy - s * 0.22), s * 0.11, s * 0.16)

        # eyes.  Their direction is derived only from the point target (or a
        # gentle idle drift), never from the real PC pointer.
        eye_y = cy - s * 0.06
        eye_dx = s * 0.17
        look_x, look_y = 0.0, 0.0
        if self._point_target is not None:
            vx = self._point_target.x() - cx
            vy = self._point_target.y() - cy
            length = max(1.0, math.hypot(vx, vy))
            look_x, look_y = vx / length, vy / length
        elif not asleep:
            look_x = math.sin(t * 0.45) * 0.28
            look_y = math.cos(t * 0.31) * 0.18

        if asleep:
            painter.setPen(QPen(QColor(226, 236, 255), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for dx in (-eye_dx, eye_dx):
                eye = QPointF(cx + dx, eye_y)
                path = QPainterPath(QPointF(eye.x() - s * 0.11, eye.y()))
                path.quadTo(QPointF(eye.x(), eye.y() + s * 0.075), QPointF(eye.x() + s * 0.11, eye.y()))
                painter.drawPath(path)
        else:
            for dx in (-eye_dx, eye_dx):
                eye = QPointF(cx + dx, eye_y)
                painter.setPen(QPen(QColor(21, 31, 83, 245), 1.3))
                painter.setBrush(QColor(248, 251, 255))
                painter.drawEllipse(eye, s * 0.145, s * 0.185)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(244, 158, 193, 80))
                painter.drawEllipse(QPointF(eye.x(), eye.y() + s * 0.12), s * 0.09, s * 0.035)
                pupil = QPointF(eye.x() + look_x * s * 0.055, eye.y() + look_y * s * 0.07)
                painter.setBrush(QColor(13, 21, 58))
                painter.drawEllipse(pupil, s * 0.067, s * 0.085)
                painter.setBrush(QColor(255, 255, 255, 235))
                painter.drawEllipse(QPointF(pupil.x() - s * 0.022, pupil.y() - s * 0.03), s * 0.022, s * 0.026)

        # blush + mouth
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 135, 183, 45))
        painter.drawEllipse(QPointF(cx - s * 0.35, cy + s * 0.19), s * 0.085, s * 0.045)
        painter.drawEllipse(QPointF(cx + s * 0.35, cy + s * 0.19), s * 0.085, s * 0.045)

        painter.setPen(QPen(QColor(27, 36, 91), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        mouth_y = cy + s * 0.27
        if asleep:
            painter.drawLine(QPointF(cx - s * 0.055, mouth_y), QPointF(cx + s * 0.055, mouth_y))
        elif self._emergency:
            path = QPainterPath(QPointF(cx - s * 0.07, mouth_y + s * 0.025))
            path.quadTo(QPointF(cx, mouth_y - s * 0.03), QPointF(cx + s * 0.07, mouth_y + s * 0.025))
            painter.drawPath(path)
        elif self._bubble_mood == "thinking":
            painter.setBrush(QColor(27, 36, 91))
            painter.drawEllipse(QPointF(cx, mouth_y), s * 0.026, s * 0.034)
        else:
            path = QPainterPath(QPointF(cx - s * 0.10, mouth_y - s * 0.01))
            path.quadTo(QPointF(cx, mouth_y + s * 0.075), QPointF(cx + s * 0.10, mouth_y - s * 0.01))
            painter.drawPath(path)

        if self._point_target is not None:
            pulse = (math.sin(t * 4.0) + 1.0) / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 218, 120, 120 + int(80 * pulse)))
            painter.drawEllipse(QPointF(cx + s * 0.43, cy - s * 0.40), 2.0 + pulse, 2.0 + pulse)

        if self._asleep:
            font = QFont(self._font_family, 12)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor(189, 207, 255, 210))
            for i, (dx, dy) in enumerate(((s * 1.10, -s * 0.75), (s * 1.30, -s * 1.05), (s * 1.50, -s * 1.35))):
                painter.drawText(
                    QPointF(cx + dx, cy + dy + math.sin(t * 1.6 + i) * 1.5),
                    "z" if i < 2 else "Z",
                )

    def _bubble_geometry(self, text: str) -> tuple[QRectF, bool]:
        font = QFont(self._text_family, 12)
        font.setPixelSize(14)
        metrics = QFontMetrics(font)
        max_text_width = 252
        bounds = metrics.boundingRect(
            0,
            0,
            max_text_width,
            2000,
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        bubble_w = max(150, min(286, bounds.width() + 28))
        bubble_h = max(40, bounds.height() + 22)
        cx, cy = self._pos.x(), self._pos.y()
        bubble_y = cy - self.POINTER_SIZE * 0.72 - bubble_h - 20
        below = bubble_y < 10
        if below:
            bubble_y = cy + self.POINTER_SIZE * 0.62 + 18
        bubble_x = max(10.0, min(self.width() - bubble_w - 10.0, cx - bubble_w / 2))
        return QRectF(bubble_x, bubble_y, bubble_w, bubble_h), below

    def _paint_bubble(self, painter: QPainter) -> None:
        text = self._bubble.strip()
        if not text:
            return
        if len(text) > 300:
            text = text[:299].rstrip() + "…"
        font = QFont(self._text_family, 12)
        font.setPixelSize(14)
        metrics = QFontMetrics(font)
        bubble_rect, below = self._bubble_geometry(text)
        mood_colors = {
            "happy": QColor("#8faaff"),
            "thinking": QColor("#ffd166"),
            "error": QColor("#ff6b7d"),
            "pointing": QColor("#7ee7c7"),
            "speaking": QColor("#c49bff"),
        }
        border = mood_colors.get(self._bubble_mood, QColor("#8faaff"))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(5, 9, 23, 100))
        painter.drawRoundedRect(bubble_rect.translated(0, 3), 14, 14)
        painter.setBrush(QColor(16, 22, 46, 244))
        painter.setPen(QPen(border, 1.5))
        painter.drawRoundedRect(bubble_rect, 14, 14)

        tail_x = max(bubble_rect.left() + 24, min(bubble_rect.right() - 24, self._pos.x()))
        tail = QPainterPath()
        if below:
            tail.moveTo(tail_x - 8, bubble_rect.top() + 1)
            tail.lineTo(tail_x + 7, bubble_rect.top() + 1)
            tail.lineTo(tail_x, bubble_rect.top() - 9)
        else:
            tail.moveTo(tail_x - 8, bubble_rect.bottom() - 1)
            tail.lineTo(tail_x + 7, bubble_rect.bottom() - 1)
            tail.lineTo(tail_x, bubble_rect.bottom() + 9)
        painter.setBrush(QColor(16, 22, 46, 244))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(tail)

        painter.setFont(font)
        painter.setPen(QColor(239, 244, 255))
        painter.drawText(
            bubble_rect.adjusted(14, 9, -14, -10),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.setBrush(border)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(bubble_rect.left() + 10, bubble_rect.top() + 9), 2.0, 2.0)

    def _paint_action(self, painter: QPainter) -> None:
        font = QFont(self._font_family, 8)
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        label = f"AUTOMATION · {self._action}"
        width = metrics.horizontalAdvance(label) + 16
        rect = QRectF(
            max(8.0, min(self.width() - width - 8, self._pos.x() - width / 2)),
            max(8.0, self._pos.y() - self.POINTER_SIZE * 0.74 - 22),
            width,
            19,
        )
        painter.setBrush(QColor(255, 178, 78, 235))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 9, 9)
        painter.setPen(QColor(31, 25, 19))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_recording(self, painter: QPainter, t: float) -> None:
        font = QFont(self._text_family, 9)
        font.setPixelSize(10)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text = self._recording_label
        width = metrics.horizontalAdvance(text) + 38
        rect = QRectF(
            max(8.0, min(self.width() - width - 8, self._pos.x() + 30)),
            max(8.0, self._pos.y() - 70),
            width,
            24,
        )
        pulse = (math.sin(t * 4.0) + 1.0) / 2.0
        painter.setPen(QPen(QColor(255, 116, 137, 200), 1.0))
        painter.setBrush(QColor(34, 15, 27, 238))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 76, 101, 170 + int(85 * pulse)))
        painter.drawEllipse(QPointF(rect.left() + 13, rect.center().y()), 4.0, 4.0)
        painter.setPen(QColor(255, 214, 220))
        painter.drawText(
            rect.adjusted(23, 0, -8, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )

    def _paint_emergency_badge(self, painter: QPainter) -> None:
        font = QFont(self._font_family, 9)
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        text = "CONTROLS LOCKED"
        width = metrics.horizontalAdvance(text) + 38
        rect = QRectF(
            max(8.0, min(self.width() - width - 8, self._pos.x() - width / 2)),
            max(8.0, self._pos.y() + 58),
            width,
            28,
        )
        painter.setPen(QPen(QColor(255, 146, 158, 210), 1.2))
        painter.setBrush(QColor(66, 13, 29, 245))
        painter.drawRoundedRect(rect, 14, 14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 80, 104))
        painter.drawEllipse(QPointF(rect.left() + 14, rect.center().y()), 4.5, 4.5)
        painter.setPen(QColor(255, 226, 230))
        painter.drawText(
            rect.adjusted(25, 0, -10, 0),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            text,
        )
