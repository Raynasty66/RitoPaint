"""
Reports which window the overlay locks onto, and whether it lands on it.

    python check_alignment.py

Lists every candidate window with its owning executable, class, size and state,
names the one the overlay picks, and prints the per-edge difference between the
two rects. Read-only: it never moves or resizes anything.
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from window_helper import find_window

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def get_window_class(hwnd):
    name = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, name, 64)
    return name.value


def get_window_title(hwnd):
    title = ctypes.create_unicode_buffer(300)
    user32.GetWindowTextW(hwnd, title, 300)
    return title.value


def process_name(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return f"pid {pid.value} (no access)"
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value.rsplit("\\", 1)[-1]
        return f"pid {pid.value}"
    finally:
        kernel32.CloseHandle(handle)


def client_box(hwnd):
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return (origin.x, origin.y,
            origin.x + rect.right - rect.left, origin.y + rect.bottom - rect.top)


def frame_box(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def state_of(hwnd):
    if user32.IsIconic(hwnd):
        return "minimized"
    return "on screen" if user32.IsWindowVisible(hwnd) else "hidden"


def main():
    app = QApplication(sys.argv)
    from draw_overlay import get_league_window_rect

    candidates = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _):
        if ("league of legends" in get_window_title(hwnd).lower()
                or get_window_class(hwnd) in ("RiotWindowClass", "RCLIENT")):
            candidates.append(hwnd)
        return True

    user32.EnumWindows(collect, 0)

    print(f"{len(candidates)} candidate window(s), in z-order:\n")
    for hwnd in candidates:
        left, top, right, bottom = client_box(hwnd)
        print(f"  {process_name(hwnd):24s} {get_window_class(hwnd):20s} "
              f"{right - left:5d}x{bottom - top:<5d} {state_of(hwnd):10s} "
              f"{get_window_title(hwnd)[:44]}")

    target = find_window("League of Legends (TM) Client")
    if target is None:
        print("\nNo match - the overlay will cover the full screen.")
        return 1

    print(f"\nthe overlay locks onto: {process_name(target)} "
          f"[{get_window_class(target)}] '{get_window_title(target)}'")

    left, top, width, height = get_league_window_rect(app)
    print(f"computed rect: {left},{top} {width}x{height} (logical)")
    if width == 0 or height == 0:
        print("-> 0 in a dimension: draw_overlay.py will raise ZeroDivisionError here")
        return 1

    overlay = QWidget()
    overlay.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
    overlay.setAttribute(Qt.WA_TranslucentBackground)
    overlay.move(left, top)
    overlay.resize(width, height)
    overlay.show()
    app.processEvents()

    overlay_rect, target_rect = frame_box(int(overlay.winId())), client_box(target)
    deltas = [abs(a - b) for a, b in zip(overlay_rect, target_rect)]
    print(f"\noverlay  {overlay_rect}")
    print(f"target   {target_rect}")
    print(f"off by   {deltas}  ->  {'ALIGNED' if max(deltas) <= 3 else 'MISALIGNED'}")

    overlay.close()
    return 0 if max(deltas) <= 3 else 1


if __name__ == "__main__":
    sys.exit(main())
