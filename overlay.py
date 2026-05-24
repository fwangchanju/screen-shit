"""
화면 캡쳐 오버레이
섹션을 자동 감지하고 스포트라이트 효과로 하이라이트합니다.
클릭하면 해당 영역을 편집기로 전달합니다.
"""
import ctypes
import tkinter as tk
from PIL import Image, ImageTk, ImageGrab, ImageEnhance

from regions import get_all_regions, find_best_region

# DPI 인식 설정 (고해상도 모니터 지원)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


class CaptureOverlay:
    OUTLINE_COLOR = "#0078D4"
    OUTLINE_WIDTH = 3
    DIM_FACTOR = 0.55

    def __init__(self, master=None):
        self.master = master
        self.screenshot = None
        self.dimmed_tk = None
        self.regions = []
        self.current_region = None
        self._region_tk = None  # GC 방지용 참조
        self.captured_image = None

    def start(self):
        """오버레이를 시작하고 캡쳐된 이미지를 반환합니다 (취소 시 None)."""
        # 멀티모니터: 가상 데스크톱 전체 캡처
        try:
            vx = ctypes.windll.user32.GetSystemMetrics(76)
            vy = ctypes.windll.user32.GetSystemMetrics(77)
            vw = ctypes.windll.user32.GetSystemMetrics(78)
            vh = ctypes.windll.user32.GetSystemMetrics(79)
        except Exception:
            vx, vy, vw, vh = 0, 0, 0, 0

        self.screenshot = ImageGrab.grab(all_screens=True)
        sw, sh = self.screenshot.size
        if vw <= 0:
            vw, vh, vx, vy = sw, sh, 0, 0

        enhancer = ImageEnhance.Brightness(self.screenshot)
        dimmed = enhancer.enhance(self.DIM_FACTOR)

        self.regions = get_all_regions(self.screenshot, (sw, sh))

        if self.master:
            root = tk.Toplevel(self.master)
        else:
            root = tk.Tk()
        self.root = root

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry(f"{vw}x{vh}+{vx}+{vy}")
        root.focus_force()

        canvas = tk.Canvas(root, cursor="crosshair", highlightthickness=0, bd=0)
        canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas = canvas

        self.dimmed_tk = ImageTk.PhotoImage(dimmed)
        canvas.create_image(0, 0, anchor=tk.NW, image=self.dimmed_tk)

        # 하이라이트용 이미지 레이어 (선택된 영역을 원본 밝기로)
        self._region_item = canvas.create_image(0, 0, anchor=tk.NW)

        # 테두리 사각형
        self._rect_item = canvas.create_rectangle(
            0, 0, 0, 0,
            outline=self.OUTLINE_COLOR,
            width=self.OUTLINE_WIDTH,
            fill="",
        )

        # 안내 텍스트 (그림자 + 본문)
        cx = sw // 2
        canvas.create_text(cx + 1, 31, text="클릭하여 캡쳐  |  ESC 취소",
                           fill="black", font=("맑은 고딕", 12))
        canvas.create_text(cx, 30, text="클릭하여 캡쳐  |  ESC 취소",
                           fill="white", font=("맑은 고딕", 12))

        canvas.bind("<Motion>", self._on_move)
        canvas.bind("<Button-1>", self._on_click)
        root.bind("<Escape>", lambda e: root.destroy())

        if self.master:
            self.master.wait_window(root)
        else:
            root.mainloop()

        return self.captured_image

    # ------------------------------------------------------------------
    def _on_move(self, event):
        sw, sh = self.screenshot.size
        region = find_best_region(event.x, event.y, self.regions, (sw, sh))
        if region == self.current_region:
            return
        self.current_region = region

        if region is None:
            self.canvas.coords(self._rect_item, 0, 0, 0, 0)
            self.canvas.itemconfig(self._region_item, image="")
            return

        x1, y1, x2, y2 = region
        crop = self.screenshot.crop((x1, y1, x2, y2))
        tk_crop = ImageTk.PhotoImage(crop)
        self._region_tk = tk_crop  # 참조 유지

        self.canvas.coords(self._region_item, x1, y1)
        self.canvas.itemconfig(self._region_item, image=tk_crop)
        self.canvas.coords(self._rect_item, x1, y1, x2, y2)

    def _on_click(self, event):
        if self.current_region:
            x1, y1, x2, y2 = self.current_region
            self.captured_image = self.screenshot.crop((x1, y1, x2, y2))
        self.root.destroy()
