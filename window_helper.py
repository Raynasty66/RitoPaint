"""
Locates the League of Legends window and toggles the overlay's click-through.

Win32 reports window geometry in physical pixels while Qt works in DPI-scaled
logical ones, so rects are converted on the way out.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
SM_CXSCREEN = 0
GA_ROOTOWNER = 3


def find_window(title_substring) -> int | None:
    """
    First top-level window whose title contains title_substring, or None.

    Matches come back in z-order, so pass a substring unique to the window you
    want. League's gameplay window is titled "League of Legends (TM) Client";
    the launcher and its helper windows are titled "League of Legends".
    """
    result = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if title_substring.lower() in buf.value.lower():
            result.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return result[0] if result else None


def get_client_rect_on_screen(hwnd, qt_logical_screen_width=None):
    """
    (left, top, width, height) of the window's client area - no title bar or
    borders - in screen coordinates.

    Win32 reports physical pixels while Qt reports DPI-scaled logical ones, so
    pass qt_logical_screen_width to get a result safe to mix with Qt coords.
    """
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top

    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    left, top = origin.x, origin.y

    if qt_logical_screen_width is not None:
        scale_factor = qt_logical_screen_width / user32.GetSystemMetrics(SM_CXSCREEN)
        left, top, width, height = (round(v * scale_factor) for v in (left, top, width, height))

    return left, top, width, height


def is_in_front(hwnd) -> bool:
    """True when hwnd, or a window it owns, is the foreground window and it isn't minimized."""
    foreground = user32.GetForegroundWindow()
    if not foreground or user32.IsIconic(hwnd):
        return False
    return user32.GetAncestor(foreground, GA_ROOTOWNER) == hwnd


def set_main_window(hwnd: int):
    user32.SetForegroundWindow(hwnd)


def set_click_through(hwnd, enabled):
    """
    Toggles WS_EX_TRANSPARENT directly. Qt's WA_TransparentForMouseEvents can
    fail to reach the native window when flipped after the window is shown -
    which is every mode toggle here - leaving clicks stuck on the overlay.
    """
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if enabled:
        style |= WS_EX_TRANSPARENT
    else:
        style &= ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


def set_no_activate(hwnd):
    """Lets a window be clicked without taking the foreground off League."""
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
