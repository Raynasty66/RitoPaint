"""
Transparent, always-on-top overlay for the League of Legends window.

Strokes are stored as world ground coordinates, not pixels, so they stay
pinned to the map as the camera pans.
"""
import sys
import keyboard
from calculations import GroundPlaneProjector
from camera_feed import CameraFeed
from window_helper import find_window, get_client_rect_on_screen, set_main_window, set_click_through
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QSlider, QLineEdit
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtCore import Qt, QTimer


class Overlay(QWidget):
    def __init__(self, left, top, width, height):
        super().__init__()

        # aligned to League's client area, so pixel (0, 0) here is pixel (0, 0)
        # of the rendered view
        self.move(left, top)
        self.resize(width, height)
        self.setWindowTitle("RiotPaint Overlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.drawing_window = int(self.winId())
        self.league_window = find_window("League of Legends")
        self.projector = GroundPlaneProjector(pixel_width=width, pixel_height=height)

        self.ground_strokes = []
        self.current_stroke = {}
        self.current_color = "red"
        self.brush_width = 4

        self.draw_mode = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self.draw_mode)
        self.settings = None  # set from __main__ once SettingsWindow exists

        self.camera_feed = CameraFeed(poll_hz=120)
        self.camera_feed.start()

        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.refresh_camera_position)
        self.camera_timer.start(8)

    def refresh_camera_position(self):
        """Reads the newest camera sample off the feed and updates the projector."""
        # raise the lead if strokes still lag behind fast pans
        render = self.camera_feed.predicted(lead_seconds=0.0)
        if render is None:
            return

        camera_position = render.get("cameraPosition")
        if not camera_position:
            return

        self.projector.update_camera_position(camera_position["x"], camera_position["z"])
        self.update()

    def closeEvent(self, event):
        self.camera_feed.stop()
        super().closeEvent(event)

    def toggle_draw_mode(self):
        self.draw_mode = not self.draw_mode
        self.set_current_window()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self.draw_mode)
        set_click_through(self.drawing_window, not self.draw_mode)

    def set_current_window(self):
        if self.draw_mode:
            set_main_window(self.drawing_window)
        else:
            set_main_window(self.league_window)

    def wheelEvent(self, event):
        if self.draw_mode and self.settings is not None and self.settings.isVisible():
            # drive the slider, not brush_width - its valueChanged signal is
            # what keeps the two in sync
            step = 1 if event.angleDelta().y() < 0 else -1
            self.settings.slider.setValue(self.settings.slider.value() + step)

    def mousePressEvent(self, event):
        if self.draw_mode:
            ground_point = self.projector.pixel_to_ground(event.position().x(), event.position().y())
            self.current_stroke = {"points": [ground_point],
                                   "color": self.current_color,
                                   "width": self.brush_width}
            self.update()

    def mouseMoveEvent(self, event):
        if self.draw_mode and self.current_stroke:
            ground_point = self.projector.pixel_to_ground(event.position().x(), event.position().y())
            self.current_stroke["points"].append(ground_point)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.draw_mode:
            self.ground_strokes.append(self.current_stroke)
            self.current_stroke = {}
            self.update()

    def paintEvent(self, event):
        """Every point's pixel is recomputed here from its world coordinate."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        all_strokes = self.ground_strokes + ([self.current_stroke] if self.current_stroke else [])

        for stroke in all_strokes:
            pen = QPen(QColor(stroke["color"]))
            pen.setWidth(stroke["width"])
            painter.setPen(pen)

            previous_pixel = None
            for ground_x, ground_z in stroke["points"]:
                pixel = self.projector.ground_to_pixel(ground_x, ground_z)
                if pixel is None:
                    previous_pixel = None
                    continue
                if previous_pixel is not None:
                    painter.drawLine(previous_pixel[0], previous_pixel[1], pixel[0], pixel[1])
                else:
                    painter.drawPoint(*pixel)
                previous_pixel = pixel


class SettingsWindow(QWidget):
    """Sidebar panel for brush color and width, toggled with the . key."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window

        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background-color: white; color: black;")

        self.resize(220, 130)
        self.move(main_window.x() + main_window.width() - 240, main_window.y() + 20)

        layout = QVBoxLayout(self)

        self.color_input = QLineEdit(main_window.current_color)
        self.color_input.setPlaceholderText("#FFFFFF")
        self.color_input.returnPressed.connect(self.on_color_changed)
        layout.addWidget(self.color_input)

        self.label = QLabel(f"Brush width: {main_window.brush_width}")
        layout.addWidget(self.label)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 20)
        self.slider.setValue(main_window.brush_width)
        self.slider.valueChanged.connect(self.on_width_changed)
        layout.addWidget(self.slider)

        # hotkeys fire on the keyboard library's thread, but Qt windows can only
        # be shown from the GUI thread - so the hotkey sets a flag and this
        # timer does the work
        self._toggle_requested = False
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._apply_pending_toggle)
        self.poll_timer.start(16)

    def on_width_changed(self, value):
        self.main_window.brush_width = value
        self.label.setText(f"Brush width: {value}")

    def on_color_changed(self):
        text = self.color_input.text()
        if QColor.isValidColor(text):
            self.main_window.current_color = text

    def toggle(self):
        self._toggle_requested = True

    def _apply_pending_toggle(self):
        if self._toggle_requested:
            self._toggle_requested = False
            if self.main_window.draw_mode:
                self.setVisible(not self.isVisible())

        if not self.main_window.draw_mode and self.isVisible():
            self.hide()


def get_league_window_rect(app):
    """League's client rect, converted into Qt's logical pixel space."""
    qt_logical_screen_width = app.primaryScreen().size().width()

    hwnd = find_window("League of Legends")
    if hwnd is not None:
        return get_client_rect_on_screen(hwnd, qt_logical_screen_width)

    size = app.primaryScreen().size()
    return 0, 0, size.width(), size.height()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    left, top, width, height = get_league_window_rect(app)
    print(f"Overlay aligned to: left={left} top={top} width={width} height={height}")

    window = Overlay(left, top, width, height)
    window.show()

    settings = SettingsWindow(window)
    window.settings = settings

    keyboard.add_hotkey('`', window.toggle_draw_mode)
    keyboard.add_hotkey('.', settings.toggle)

    sys.exit(app.exec())
