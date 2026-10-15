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
import numpy as np
from calculations import GroundPlaneProjector
from camera_feed import CameraFeed
from dock import BrushDock
from strokes import erase, painter_path, simplify
from terrain import FlatTerrain, Terrain
from window_helper import find_window, get_client_rect_on_screen, is_in_front, set_main_window, set_click_through
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget
from PySide6.QtGui import QAction, QIcon, QPainter, QPen, QPixmap, QColor
from PySide6.QtCore import QPointF, Qt, QTimer, Signal

# mouse moves closer than this to the last kept point add nothing visible
MIN_POINT_SPACING_PX = 2.0
MIN_ERASER_RADIUS_PX = 8.0


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

        self.ground_strokes = []  # finished strokes, points as (n, 3) arrays
        self.current_stroke = {}
        self.last_stroke_pixel = None
        self.eraser_pixel = None  # where the eraser is while the right button is held
        self.current_color = "red"
        self.brush_width = 4

        self.draw_mode = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self.draw_mode)
        self.dock = None  # set from __main__ once BrushDock exists
        self.dock_was_open = False

        # each reply waits for the next game frame, so the frame cap sets the real rate
        self.camera_feed = CameraFeed(poll_hz=240)
        self.camera_feed.start()

        # the default coarse timer rounds 8 ms up to the 15.6 ms Windows tick
        self.camera_timer = QTimer(self)
        self.camera_timer.setTimerType(Qt.PreciseTimer)
        self.camera_timer.timeout.connect(self.refresh_camera_position)
        self.camera_timer.start(8)
        self.camera_pose = None

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
        _, render = self.camera_feed.latest()
        if render is None:
            return

        camera_position = render.get("cameraPosition")
        if not camera_position:
            return

        # a still camera needs no repaint
        pose = (camera_position["x"], camera_position["z"], camera_position.get("y"))
        if pose == self.camera_pose:
            return
        self.camera_pose = pose

        # y is the camera's height, which changes every time the view zooms
        self.projector.update_camera_position(*pose)
        self.update()

    def clear_strokes(self):
        self.ground_strokes = []
        self.current_stroke = {}
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
        if not self.draw_mode:
            return
        x, y = event.position().x(), event.position().y()
        if event.button() == Qt.RightButton:
            self.eraser_pixel = (x, y)
            self.erase_at(x, y)
        elif event.button() == Qt.LeftButton:
            self.current_stroke = {"points": [self.projector.pixel_to_ground(x, y)],
                                   "color": self.current_color,
                                   "width": self.brush_width}
            self.last_stroke_pixel = (x, y)
        self.update()

    def mouseMoveEvent(self, event):
        if not self.draw_mode:
            return
        x, y = event.position().x(), event.position().y()
        if self.eraser_pixel is not None:
            self.erase_along(x, y)
        elif self.current_stroke:
            last_x, last_y = self.last_stroke_pixel
            if (x - last_x) ** 2 + (y - last_y) ** 2 < MIN_POINT_SPACING_PX ** 2:
                return
            self.current_stroke["points"].append(self.projector.pixel_to_ground(x, y))
            self.last_stroke_pixel = (x, y)
            self.update()

    def mouseReleaseEvent(self, event):
        if not self.draw_mode:
            return
        if event.button() == Qt.RightButton:
            self.eraser_pixel = None
        elif event.button() == Qt.LeftButton and self.current_stroke:
            points = simplify(np.array(self.current_stroke["points"]))
            self.ground_strokes.append(dict(self.current_stroke, points=points))
            self.current_stroke = {}
        self.update()

    def eraser_radius(self):
        return max(MIN_ERASER_RADIUS_PX, self.brush_width * 1.5)

    def erase_along(self, x, y):
        """Erases at steps of half the radius, so a fast drag leaves no gaps."""
        last_x, last_y = self.eraser_pixel
        steps = max(1, int(np.hypot(x - last_x, y - last_y) / (self.eraser_radius() / 2)))
        for i in range(1, steps + 1):
            self.erase_at(last_x + (x - last_x) * i / steps, last_y + (y - last_y) * i / steps)
        self.eraser_pixel = (x, y)
        self.update()

    def erase_at(self, x, y):
        """Cuts every stroke under the eraser circle, keeping the pieces either side."""
        kept = []
        for stroke in self.ground_strokes:
            pieces = erase(stroke["points"], *self.projector.ground_to_pixels(stroke["points"]),
                           x, y, self.eraser_radius(), self.projector.pixel_to_ground)
            if pieces is None:
                kept.append(stroke)
            else:
                kept += [dict(stroke, points=piece) for piece in pieces]
        self.ground_strokes = kept

    def paintEvent(self, event):
        """Every point's pixel is recomputed here from its world coordinate."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 1))
        all_strokes = self.ground_strokes + ([self.current_stroke] if self.current_stroke else [])

        for stroke in all_strokes:
            painter.setPen(QPen(QColor(stroke["color"]), stroke["width"],
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))

            pixel_x, pixel_y, visible = self.projector.ground_to_pixels(np.asarray(stroke["points"]))
            if visible.sum() == 1:
                painter.drawPoint(QPointF(pixel_x[visible][0], pixel_y[visible][0]))
            elif visible.any():
                painter.drawPath(painter_path(pixel_x, pixel_y, visible))

        if self.eraser_pixel is not None:
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1.5))
            radius = self.eraser_radius()
            painter.drawEllipse(QPointF(*self.eraser_pixel), radius, radius)


def load_terrain():
    """Summoner's Rift heights from the League install, or a flat map if they can't be read."""
    try:
        return Terrain.from_install()
    except (OSError, KeyError, ValueError) as exc:
        print(f"Terrain heights unavailable, drawing on a flat map: {exc}")
        return FlatTerrain()


def make_tray_icon(app, overlay):
    """Tray menu that stays reachable while the overlay is hidden behind another app."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QColor("#ff4d4d"))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(8, 8, 48, 48)
    painter.end()

    tray = QSystemTrayIcon(QIcon(pixmap), app)
    tray.setToolTip("RiotPaint")
    menu = QMenu()
    clear = QAction("Clear strokes", menu)
    clear.triggered.connect(overlay.clear_strokes)
    quit_action = QAction("Quit RiotPaint", menu)
    quit_action.triggered.connect(overlay.shutdown)
    menu.addAction(clear)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.show()
    return tray, menu


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
    tray = make_tray_icon(app, window)  # held so it isn't garbage-collected

    keyboard.add_hotkey('`', window.toggle_draw_mode)
    keyboard.add_hotkey('.', dock.toggle)
    keyboard.add_hotkey('ctrl+shift+q', window.quit_requested.emit)

    sys.exit(app.exec())
