"""
The floating brush dock: HSV wheel, quick-pick swatches, brush size.

Custom-painted, focus-less widgets - a stock widget taking focus would pull
League out of the foreground mid-draw. Writes straight to
Overlay.current_color / Overlay.brush_width.
"""
import colorsys
import math

from PySide6.QtCore import Qt, QRectF, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from window_helper import set_no_activate

PANEL_COLOR = QColor(0x0E, 0x10, 0x16, 230)      # #0e1016 at ~90% opacity
PANEL_BORDER = QColor(255, 255, 255, 28)
PANEL_RADIUS = 20
LABEL_COLOR = "#7c869c"

MIN_BRUSH = 2
MAX_BRUSH = 40

# red, coral, yellow, mint, blue, white
QUICK_COLORS = ["#ff4d4d", "#ff7f50", "#ffd23f", "#3ddc97", "#4d8bff", "#ffffff"]


def _focusless(widget):
    widget.setFocusPolicy(Qt.NoFocus)
    return widget


class PenIcon(QWidget):
    """White pen mark for the dock header."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(18, 18)
        _focusless(self)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        body = QPainterPath()
        body.moveTo(5.4, 11.0)
        body.lineTo(12.6, 3.4)
        body.lineTo(15.0, 5.7)
        body.lineTo(7.8, 13.3)
        body.closeSubpath()
        painter.fillPath(body, QColor(255, 255, 255, 235))

        nib = QPainterPath()
        nib.moveTo(5.4, 11.0)
        nib.lineTo(7.8, 13.3)
        nib.lineTo(3.6, 15.2)
        nib.closeSubpath()
        painter.fillPath(nib, QColor(255, 255, 255, 160))


class HueSatWheel(QWidget):
    """
    Hue around the ring, saturation from center to rim.

    Rasterized once at full brightness; brightness is a black wash at paint
    time, so dragging the value bar never re-runs the per-pixel loop.
    """

    hueSatChanged = Signal(float, float)
    DIAMETER = 128

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.DIAMETER, self.DIAMETER)
        self.setCursor(Qt.CrossCursor)
        _focusless(self)

        self._hue = 0.0
        self._saturation = 1.0
        self._value = 1.0
        self._wheel = self._render_wheel(self.DIAMETER)

    @staticmethod
    def _render_wheel(diameter):
        radius = diameter / 2.0
        pixels = bytearray(diameter * diameter * 4)

        for y in range(diameter):
            dy = y - radius + 0.5
            for x in range(diameter):
                dx = x - radius + 0.5
                distance = math.hypot(dx, dy)
                edge = radius - distance
                if edge <= -0.5:
                    continue

                hue = (math.atan2(-dy, dx) / (2 * math.pi)) % 1.0
                red, green, blue = colorsys.hsv_to_rgb(hue, min(1.0, distance / radius), 1.0)

                index = (y * diameter + x) * 4
                pixels[index] = int(blue * 255)          # ARGB32 is BGRA in memory
                pixels[index + 1] = int(green * 255)
                pixels[index + 2] = int(red * 255)
                pixels[index + 3] = 255 if edge >= 0.5 else int((edge + 0.5) * 255)  # feather the rim

        return QImage(bytes(pixels), diameter, diameter, QImage.Format_ARGB32).copy()

    def hue_saturation(self):
        return self._hue, self._saturation

    def set_hue_saturation(self, hue, saturation):
        self._hue, self._saturation = hue, saturation
        self.update()

    def set_value(self, value):
        self._value = value
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawImage(0, 0, self._wheel)

        if self._value < 1.0:
            circle = QPainterPath()
            circle.addEllipse(QRectF(self.rect()))
            painter.setClipPath(circle)
            painter.fillRect(self.rect(), QColor(0, 0, 0, int((1.0 - self._value) * 255)))
            painter.setClipping(False)

        radius = self.DIAMETER / 2.0
        angle = self._hue * 2 * math.pi
        marker_x = radius + math.cos(angle) * self._saturation * radius
        marker_y = radius - math.sin(angle) * self._saturation * radius
        marker = QRectF(marker_x - 6, marker_y - 6, 12, 12)

        painter.setBrush(QColor.fromHsvF(self._hue, self._saturation, self._value))
        painter.setPen(QPen(QColor(0, 0, 0, 130), 3))
        painter.drawEllipse(marker)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 1.6))
        painter.drawEllipse(marker)

    def _pick(self, position):
        radius = self.DIAMETER / 2.0
        dx, dy = position.x() - radius, position.y() - radius
        self._hue = (math.atan2(-dy, dx) / (2 * math.pi)) % 1.0
        self._saturation = min(1.0, math.hypot(dx, dy) / radius)
        self.update()
        self.hueSatChanged.emit(self._hue, self._saturation)

    def mousePressEvent(self, event):
        self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position())


class ValueBar(QWidget):
    """Vertical brightness bar, black at the bottom and full color at the top."""

    valueChanged = Signal(float)
    WIDTH = 16
    PADDING = 4

    def __init__(self, height, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, height)
        _focusless(self)

        self._hue = 0.0
        self._saturation = 1.0
        self._value = 1.0

    def set_hue_saturation(self, hue, saturation):
        self._hue, self._saturation = hue, saturation
        self.update()

    def set_value(self, value):
        self._value = value
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        track = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QLinearGradient(0, track.top(), 0, track.bottom())
        gradient.setColorAt(0.0, QColor.fromHsvF(self._hue, self._saturation, 1.0))
        gradient.setColorAt(1.0, QColor(0, 0, 0))

        rounded = QPainterPath()
        rounded.addRoundedRect(track, self.WIDTH / 2.0, self.WIDTH / 2.0)
        painter.fillPath(rounded, gradient)
        painter.setPen(QPen(PANEL_BORDER, 1))
        painter.drawPath(rounded)

        handle_y = self.PADDING + (1.0 - self._value) * self._usable_height()
        handle = QRectF(-1, handle_y - 2.5, self.WIDTH + 2, 5)
        painter.setBrush(QColor(255, 255, 255, 240))
        painter.setPen(QPen(QColor(0, 0, 0, 120), 1))
        painter.drawRoundedRect(handle, 2.5, 2.5)

    def _usable_height(self):
        return max(1.0, self.height() - 2 * self.PADDING)

    def _pick(self, position):
        fraction = (position.y() - self.PADDING) / self._usable_height()
        self._value = max(0.0, min(1.0, 1.0 - fraction))
        self.update()
        self.valueChanged.emit(self._value)

    def mousePressEvent(self, event):
        self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position())


class SwatchRow(QWidget):
    """Quick-pick colors as filled circles; the active one wears a ring."""

    colorPicked = Signal(QColor)
    DOT = 18
    HEIGHT = 26

    def __init__(self, colors, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.PointingHandCursor)
        _focusless(self)

        self._colors = [QColor(name) for name in colors]
        self._active = -1

    def set_active_color(self, color):
        names = [swatch.name() for swatch in self._colors]
        active = names.index(color.name()) if color.name() in names else -1
        if active != self._active:
            self._active = active
            self.update()

    def _centers(self):
        count = len(self._colors)
        span = (self.width() - self.DOT) / max(1, count - 1)
        return [(self.DOT / 2.0 + index * span, self.HEIGHT / 2.0) for index in range(count)]

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        for index, (color, (x, y)) in enumerate(zip(self._colors, self._centers())):
            if index == self._active:
                painter.setBrush(Qt.NoBrush)
                painter.setPen(QPen(QColor(255, 255, 255, 220), 1.6))
                painter.drawEllipse(QRectF(x - 12, y - 12, 24, 24))

            painter.setBrush(color)
            painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
            painter.drawEllipse(QRectF(x - self.DOT / 2.0, y - self.DOT / 2.0, self.DOT, self.DOT))

    def mousePressEvent(self, event):
        position = event.position()
        for index, (x, y) in enumerate(self._centers()):
            if math.hypot(position.x() - x, position.y() - y) <= self.DOT:
                self.colorPicked.emit(QColor(self._colors[index]))
                return


class SizeSlider(QWidget):
    """Brush size track; QSlider's value()/setValue()/valueChanged API."""

    valueChanged = Signal(int)
    HEIGHT = 22
    HANDLE = 7

    def __init__(self, value, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.SizeHorCursor)
        _focusless(self)

        self._value = self._clamp(value)
        self._color = QColor("white")

    @staticmethod
    def _clamp(value):
        return max(MIN_BRUSH, min(MAX_BRUSH, int(round(value))))

    def value(self):
        return self._value

    def setValue(self, value):
        value = self._clamp(value)
        if value != self._value:
            self._value = value
            self.update()
            self.valueChanged.emit(value)

    def set_color(self, color):
        self._color = color
        self.update()

    def _track(self):
        return self.HANDLE, self.width() - self.HANDLE

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        left, right = self._track()
        middle = self.HEIGHT / 2.0
        fraction = (self._value - MIN_BRUSH) / (MAX_BRUSH - MIN_BRUSH)
        handle_x = left + fraction * (right - left)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRoundedRect(QRectF(left, middle - 2, right - left, 4), 2, 2)
        painter.setBrush(self._color)
        painter.drawRoundedRect(QRectF(left, middle - 2, handle_x - left, 4), 2, 2)

        painter.setBrush(QColor(255, 255, 255, 240))
        painter.setPen(QPen(QColor(0, 0, 0, 110), 1))
        painter.drawEllipse(QRectF(handle_x - self.HANDLE, middle - self.HANDLE,
                                   self.HANDLE * 2, self.HANDLE * 2))

    def _pick(self, position):
        left, right = self._track()
        fraction = (position.x() - left) / max(1, right - left)
        fraction = max(0.0, min(1.0, fraction))
        self.setValue(MIN_BRUSH + fraction * (MAX_BRUSH - MIN_BRUSH))

    def mousePressEvent(self, event):
        self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position())


class SizePreview(QWidget):
    """A dot at the literal brush width, so the size is visible pre-stroke."""

    SIDE = MAX_BRUSH + 8

    def __init__(self, value, color, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIDE, self.SIDE)
        _focusless(self)

        self._value = value
        self._color = color

    def set_size(self, value):
        self._value = value
        self.update()

    def set_color(self, color):
        self._color = color
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = self.SIDE / 2.0

        painter.setPen(QPen(QColor(255, 255, 255, 25), 1))
        painter.setBrush(QColor(255, 255, 255, 12))
        painter.drawEllipse(QRectF(0.5, 0.5, self.SIDE - 1, self.SIDE - 1))

        radius = self._value / 2.0
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)
        painter.drawEllipse(QRectF(center - radius, center - radius, self._value, self._value))


class BrushDock(QWidget):
    """
    Compact floating dock for brush color and size, toggled with the . key.

    Its own top-level window on purpose: click-through is toggled on the
    overlay's HWND alone, so clicks land here and clicks elsewhere reach the
    game.
    """

    def __init__(self, overlay):
        super().__init__(overlay)
        self.overlay = overlay

        self.setWindowTitle("RiotPaint Brush Dock")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint |
                            Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        _focusless(self)

        color = QColor(overlay.current_color)
        if not color.isValid():
            color = QColor("red")
        self._hue, self._saturation, self._value = color.hueF() % 1.0, color.saturationF(), color.valueF()

        self._build(color, overlay.brush_width)
        self._drag_offset = None

        # hotkeys fire on the keyboard thread - the timer applies them
        self._toggle_requested = False
        self._pending_size_delta = 0
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll)
        self.poll_timer.start(16)

        # native flag too - Qt's hint alone does not always reach the real window
        set_no_activate(int(self.winId()))

    def _build(self, color, brush_width):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(PenIcon())
        title = QLabel("BRUSH")
        title.setFont(QFont(self.font().family(), 8, QFont.DemiBold))
        title.setStyleSheet(f"color: {LABEL_COLOR}; letter-spacing: 2px;")
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)

        picker = QHBoxLayout()
        picker.setSpacing(12)
        self.wheel = HueSatWheel()
        self.wheel.set_hue_saturation(self._hue, self._saturation)
        self.wheel.set_value(self._value)
        self.wheel.hueSatChanged.connect(self._on_hue_sat)
        picker.addWidget(self.wheel)

        self.value_bar = ValueBar(HueSatWheel.DIAMETER)
        self.value_bar.set_hue_saturation(self._hue, self._saturation)
        self.value_bar.set_value(self._value)
        self.value_bar.valueChanged.connect(self._on_value)
        picker.addWidget(self.value_bar)
        root.addLayout(picker)

        self.swatches = SwatchRow(QUICK_COLORS)
        self.swatches.set_active_color(color)
        self.swatches.colorPicked.connect(self._on_swatch)
        root.addWidget(self.swatches)

        size_row = QHBoxLayout()
        size_row.setSpacing(12)
        self.slider = SizeSlider(brush_width)  # Overlay.wheelEvent drives it by this name
        self.slider.set_color(color)
        self.slider.valueChanged.connect(self._on_size)
        size_row.addWidget(self.slider, 1)

        self.preview = SizePreview(self.slider.value(), color)
        size_row.addWidget(self.preview)
        root.addLayout(size_row)

        self.adjustSize()
        self.setFixedSize(self.sizeHint())
        self.move(self.overlay.x() + self.overlay.width() - self.width() - 24,
                  self.overlay.y() + 24)

    # -- brush state ---------------------------------------------------------

    def _push_color(self):
        color = QColor.fromHsvF(self._hue, self._saturation, self._value)
        self.overlay.current_color = color.name()

        self.slider.set_color(color)
        self.preview.set_color(color)
        self.swatches.set_active_color(color)

    def _on_hue_sat(self, hue, saturation):
        self._hue, self._saturation = hue, saturation
        self.value_bar.set_hue_saturation(hue, saturation)
        self._push_color()

    def _on_value(self, value):
        self._value = value
        self.wheel.set_value(value)
        self._push_color()

    def _on_swatch(self, color):
        self._hue = max(0.0, color.hueF())  # white/grey report hue -1
        self._saturation, self._value = color.saturationF(), color.valueF()
        self.wheel.set_hue_saturation(self._hue, self._saturation)
        self.wheel.set_value(self._value)
        self.value_bar.set_hue_saturation(self._hue, self._saturation)
        self.value_bar.set_value(self._value)
        self._push_color()

    def _on_size(self, value):
        self.overlay.brush_width = value
        self.preview.set_size(value)

    # -- hotkeys -------------------------------------------------------------

    def toggle(self):
        self._toggle_requested = True

    def nudge_size(self, delta):
        self._pending_size_delta += delta

    def _poll(self):
        if self._toggle_requested:
            self._toggle_requested = False
            if self.overlay.draw_mode:
                self.setVisible(not self.isVisible())

        if not self.overlay.draw_mode and self.isVisible():
            self.hide()

        if self._pending_size_delta:
            delta, self._pending_size_delta = self._pending_size_delta, 0
            if self.overlay.draw_mode:  # otherwise the keys belong to the game
                self.slider.setValue(self.slider.value() + delta)

    # -- chrome --------------------------------------------------------------

    def showEvent(self, event):
        # again on show - Qt can rebuild the native window and drop the ex-style
        set_no_activate(int(self.winId()))
        super().showEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        panel = QPainterPath()
        panel.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                             PANEL_RADIUS, PANEL_RADIUS)
        painter.fillPath(panel, PANEL_COLOR)
        painter.setPen(QPen(PANEL_BORDER, 1))
        painter.drawPath(panel)

    # the controls take their own clicks - a press here is on the edge
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.SizeAllCursor)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event):
        self._drag_offset = None
        self.unsetCursor()
