"""
Stroke geometry: thinning, painter paths and the eraser.

A finished stroke holds its points as an (n, 3) array of world (x, y, z), so a
repaint projects every point in one numpy call instead of a Python loop.
"""
import numpy as np
from PySide6.QtCore import QByteArray, QDataStream
from PySide6.QtGui import QPainterPath

# world units a point may sit off the line between its neighbours before it's kept
SIMPLIFY_TOLERANCE = 1.0


def simplify(points: np.ndarray, tolerance: float = SIMPLIFY_TOLERANCE) -> np.ndarray:
    """Ramer-Douglas-Peucker on the ground (x, z): drops points that lie on a straight run."""
    if len(points) < 3:
        return points
    flat = points[:, [0, 2]]
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    pending = [(0, len(points) - 1)]
    while pending:
        first, last = pending.pop()
        if last - first < 2:
            continue
        start, end = flat[first], flat[last]
        chord = end - start
        length = np.hypot(*chord)
        inner = flat[first + 1:last] - start
        if length == 0:
            distances = np.hypot(inner[:, 0], inner[:, 1])
        else:
            distances = np.abs(chord[0] * inner[:, 1] - chord[1] * inner[:, 0]) / length
        worst = int(np.argmax(distances))
        if distances[worst] > tolerance:
            middle = first + 1 + worst
            keep[middle] = True
            pending += [(first, middle), (middle, last)]
    return points[keep]


def painter_path(pixel_x: np.ndarray, pixel_y: np.ndarray, visible: np.ndarray) -> QPainterPath:
    """
    One QPainterPath for a stroke, built from arrays without a per-point loop.

    Points behind the camera are dropped and the line restarts after them.
    The path is assembled in Qt's own serialised form (count, then a type, x,
    y per element) and read back through QDataStream.
    """
    starts = visible & ~np.concatenate(([False], visible[:-1]))
    elements = np.empty(int(visible.sum()), dtype=[("type", ">i4"), ("x", ">f8"), ("y", ">f8")])
    elements["type"] = np.where(starts[visible], 0, 1)  # 0 = moveTo, 1 = lineTo
    elements["x"] = pixel_x[visible]
    elements["y"] = pixel_y[visible]

    serialised = (np.array([len(elements)], ">i4").tobytes() + elements.tobytes()
                  + np.array([0], ">i4").tobytes())  # trailing fill rule
    path = QPainterPath()
    QDataStream(QByteArray(serialised)) >> path
    return path


def erase(stroke_points, pixel_x, pixel_y, visible, centre_x, centre_y, radius, to_ground):
    """
    What is left of a stroke after the eraser circle passes over it.

    None means the eraser missed it entirely. Otherwise every segment through
    the circle is cut exactly where it crosses the edge - a thinned stroke can
    have segments hundreds of pixels long, so dropping whole segments would
    erase far more than the eraser covers. to_ground turns a cut pixel back
    into a world point.
    """
    inside = visible & ((pixel_x - centre_x) ** 2 + (pixel_y - centre_y) ** 2 <= radius ** 2)

    # where each segment enters and leaves the circle, as fractions along it
    ax, ay = pixel_x[:-1] - centre_x, pixel_y[:-1] - centre_y
    dx, dy = pixel_x[1:] - pixel_x[:-1], pixel_y[1:] - pixel_y[:-1]
    a = np.maximum(dx * dx + dy * dy, 1e-9)
    b = 2 * (ax * dx + ay * dy)
    c = ax * ax + ay * ay - radius * radius
    discriminant = b * b - 4 * a * c
    root = np.sqrt(np.maximum(discriminant, 0.0))
    enter, leave = (-b - root) / (2 * a), (-b + root) / (2 * a)
    crossed = visible[:-1] & visible[1:] & (discriminant > 0) & (enter <= 1) & (leave >= 0)

    if not inside.any() and not crossed.any():
        return None

    def cut(i, t):
        return to_ground(pixel_x[i] + t * dx[i], pixel_y[i] + t * dy[i])

    pieces, run = [], []
    for i in range(len(stroke_points)):
        if not inside[i]:
            run.append(tuple(stroke_points[i]))
        if i == len(stroke_points) - 1 or not crossed[i]:
            continue
        if enter[i] > 0:
            run.append(cut(i, enter[i]))
        if run:
            pieces.append(np.array(run))
        run = [cut(i, leave[i])] if leave[i] < 1 else []
    if run:
        pieces.append(np.array(run))
    return pieces
