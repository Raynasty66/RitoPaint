"""
Transparent, always-on-top overlay for the League of Legends window.

Strokes are stored as world ground coordinates, not pixels, so they stay
pinned to the map as the camera pans. Each point carries the terrain height
under it, so marks in the river and on the base ramps sit where they were drawn.

Requires League running in Windowed mode, and the Replay API enabled in
game.cfg so the camera pose can be read from /replay/render. See the README.
"""
import sys
import keyboard
from calculations import GroundPlaneProjector
from camera_feed import CameraFeed
from dock import BrushDock
from terrain import FlatTerrain, Terrain
from window_helper import find_window, get_client_rect_on_screen, is_in_front, set_main_window, set_click_through
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QPainter, QPen, QColor
from PySide6.QtCore import Qt, QTimer, Signal


class Overlay(QWidget):
    """
    The drawing surface: frameless and translucent, sized to League's client
    area so its pixels line up with the rendered view.

    Outside draw mode it is click-through at the Win32 level, so clicks reach
    the game. The rect is measured once, at construction.
    """

    # emitted from the keyboard thread, so it has to be a signal
    quit_requested = Signal()

    def __init__(self, left, top, width, height):
        super().__init__()

        # aligned to League's client area, so pixel (0, 0) here is pixel (0, 0)
        # of the rendered view
        self.move(left, top)
        self.resize(width, height)
        self.setWindowTitle("RiotPaint Overlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # coming back into view must not pull focus off League
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.drawing_window = int(self.winId())
        self.league_window = find_window("League of Legends (TM) Client")
        self.projector = GroundPlaneProjector(pixel_width=width, pixel_height=height,
                                              terrain=load_terrain())

        self.ground_strokes = []
        self.current_stroke = {}
        self.current_color = "red"
        self.brush_width = 4

        self.draw_mode = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self.draw_mode)
        self.dock = None  # set from __main__ once BrushDock exists
        self.dock_was_open = False

        self.camera_feed = CameraFeed(poll_hz=120)
        self.camera_feed.start()

        self.camera_timer = QTimer(self)
        self.camera_timer.timeout.connect(self.refresh_camera_position)
        self.camera_timer.start(8)

        # strokes only show while League (or the overlay, in draw mode) is in front
        self.focus_timer = QTimer(self)
        self.focus_timer.timeout.connect(self.follow_league_focus)
        self.focus_timer.start(100)

        self.quit_requested.connect(self.shutdown)

    def showEvent(self, event):
        # WA_TransparentForMouseEvents does not reach the native window
        set_click_through(self.drawing_window, not self.draw_mode)
        super().showEvent(event)

    def shutdown(self):
        """Stops the camera thread, then ends the event loop."""
        self.camera_feed.stop()
        QApplication.quit()

    def refresh_camera_position(self):
        """Reads the newest camera sample off the feed and updates the projector."""
        # raise the lead if strokes still lag behind fast pans
        render = self.camera_feed.predicted(lead_seconds=0.0)
        if render is None:
            return

        camera_position = render.get("cameraPosition")
        if not camera_position:
            return

        # y is the camera's height, which changes every time the view zooms
        self.projector.update_camera_position(camera_position["x"], camera_position["z"],
                                              camera_position.get("y"))
        self.update()

    def follow_league_focus(self):
        """Hides the overlay, strokes and dock alike, whenever another app is in front."""
        if self.league_window is None:
            return
        in_front = is_in_front(self.league_window) or is_in_front(self.drawing_window)
        if in_front and not self.isVisible():
            self.show()
            if self.dock_was_open and self.draw_mode:
                self.dock.show()
        elif not in_front and self.isVisible():
            # the dock is its own top-level window, so it doesn't hide with the overlay
            self.dock_was_open = self.dock is not None and self.dock.isVisible()
            if self.dock_was_open:
                self.dock.hide()
            self.hide()

    def closeEvent(self, event):
        self.camera_feed.stop()
        super().closeEvent(event)

    def toggle_draw_mode(self):
        # the hotkey is global - ignore it while the user is in another app
        if not self.isVisible():
            return
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
        if self.draw_mode and self.dock is not None and self.dock.isVisible():
            # drive the slider, not brush_width - its valueChanged signal is
            # what keeps the two in sync
            step = 1 if event.angleDelta().y() < 0 else -1
            self.dock.slider.setValue(self.dock.slider.value() + step)

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
            for ground_point in stroke["points"]:
                pixel = self.projector.ground_to_pixel(*ground_point)
                if pixel is None:
                    previous_pixel = None
                    continue
                if previous_pixel is not None:
                    painter.drawLine(previous_pixel[0], previous_pixel[1], pixel[0], pixel[1])
                else:
                    painter.drawPoint(*pixel)
                previous_pixel = pixel


def load_terrain():
    """Summoner's Rift heights from the League install, or a flat map if they can't be read."""
    try:
        return Terrain.from_install()
    except (OSError, KeyError, ValueError) as exc:
        print(f"Terrain heights unavailable, drawing on a flat map: {exc}")
        return FlatTerrain()


def get_league_window_rect(app):
    """
    The gameplay window's client rect in Qt's logical pixel space, or the whole
    screen when no such window is up.
    """
    qt_logical_screen_width = app.primaryScreen().size().width()

    hwnd = find_window("League of Legends (TM) Client")
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

    dock = BrushDock(window)
    window.dock = dock

    keyboard.add_hotkey('`', window.toggle_draw_mode)
    keyboard.add_hotkey('.', dock.toggle)
    keyboard.add_hotkey('ctrl+shift+q', window.quit_requested.emit)

    sys.exit(app.exec())
