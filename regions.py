"""
화면 섹션 자동 감지 모듈
Win32 창 목록 + OpenCV 블록 감지를 조합합니다.
"""


def get_all_regions(screenshot, screen_size):
    regions = []
    regions.extend(_get_window_regions(screen_size))
    try:
        regions.extend(_get_cv_regions(screenshot))
    except ImportError:
        pass
    return regions


def _get_window_regions(screen_size):
    try:
        import win32gui
    except ImportError:
        return []

    screen_w, screen_h = screen_size
    regions = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if not win32gui.GetWindowText(hwnd):
            return
        try:
            x1, y1, x2, y2 = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(screen_w, x2)
        y2 = min(screen_h, y2)
        if x2 - x1 >= 50 and y2 - y1 >= 50:
            regions.append((x1, y1, x2, y2))

    win32gui.EnumWindows(_cb, None)
    return regions


def _get_cv_regions(screenshot, min_area=8000):
    import cv2
    import numpy as np

    img = np.array(screenshot.convert("RGB"))
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 100)

    kernel = np.ones((5, 5), np.uint8)
    edges = cv2.dilate(edges, kernel, iterations=2)
    edges = cv2.erode(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w >= 50 and h >= 50:
            regions.append((x, y, x + w, y + h))
    return regions


def find_best_region(x, y, regions, screen_size):
    """커서 위치를 포함하는 가장 작은 영역 반환."""
    screen_w, screen_h = screen_size
    candidates = [(screen_w * screen_h, (0, 0, screen_w, screen_h))]

    for r in regions:
        x1, y1, x2, y2 = r
        if x1 <= x <= x2 and y1 <= y <= y2:
            candidates.append(((x2 - x1) * (y2 - y1), r))

    candidates.sort(key=lambda t: t[0])
    return candidates[0][1]
