"""
단위영역 캡처 모듈
기존 overlay.py의 CaptureOverlay를 SmartCapture 인터페이스로 리팩토링합니다.
Win32 창 목록 + OpenCV 블록 감지로 섹션을 자동 인식하고,
클릭 시 해당 섹션을 캡처합니다.
"""
from __future__ import annotations

import tkinter as tk
from PIL import Image, ImageTk, ImageGrab, ImageEnhance

from regions import get_all_regions, find_best_region


class SmartCapture:
    OUTLINE_COLOR = "#0078D4"
    OUTLINE_WIDTH = 3
    DIM_FACTOR = 0.55

    def __init__(self, master=None, on_drag_start=None, on_overlay_ready=None):
        self.master = master
        self._on_drag_start = on_drag_start
        self._on_overlay_ready = on_overlay_ready
        self._kb_esc_hook = None
        self.screenshot: Image.Image | None = None
        self.dimmed_tk: ImageTk.PhotoImage | None = None
        self.regions: list = []
        self.current_region: tuple | None = None
        self._region_tk: ImageTk.PhotoImage | None = None  # GC 방지
        self.captured_image: Image.Image | None = None
        self.root: tk.Toplevel | tk.Tk | None = None
        self.canvas: tk.Canvas | None = None

    def start(self) -> Image.Image | None:
        """오버레이를 시작하고 캡처된 이미지를 반환합니다. 취소 시 None."""
        self.screenshot = ImageGrab.grab(all_screens=False)
        sw, sh = self.screenshot.size

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
        root.geometry(f"{sw}x{sh}+0+0")
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

        # 오버레이 생성 완료 → 50ms 후 콜백 (툴바를 오버레이 위로 lift)
        if self._on_overlay_ready:
            root.after(50, self._on_overlay_ready)

        canvas.bind("<Motion>", self._on_move)
        canvas.bind("<Button-1>", self._on_click)
        root.bind("<Escape>", lambda e: self._cancel())

        # 3-2 item 7: keyboard 레벨 ESC 훅 (포커스 미확보 시 보완)
        try:
            import keyboard as _kb
            self._kb_esc_hook = _kb.add_hotkey(
                'esc', lambda: root.after(0, self._cancel), suppress=False)
        except Exception:
            pass

        if self.master:
            self.master.wait_window(root)
        else:
            root.mainloop()

        return self.captured_image

    # ------------------------------------------------------------------
    def _on_move(self, event: tk.Event) -> None:
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
        self._region_tk = tk_crop  # 참조 유지 (GC 방지)

        self.canvas.coords(self._region_item, x1, y1)
        self.canvas.itemconfig(self._region_item, image=tk_crop)
        self.canvas.coords(self._rect_item, x1, y1, x2, y2)

    def _remove_kb_hook(self) -> None:
        """keyboard ESC 훅을 안전하게 제거합니다."""
        if self._kb_esc_hook is not None:
            try:
                import keyboard as _kb
                _kb.remove_hotkey(self._kb_esc_hook)
            except Exception:
                pass
            self._kb_esc_hook = None

    def _on_click(self, event: tk.Event) -> None:
        # 3-2 item 2: 클릭 시 툴바 숨기기
        if self._on_drag_start:
            try:
                self._on_drag_start()
            except Exception:
                pass
        self._remove_kb_hook()
        if self.current_region:
            x1, y1, x2, y2 = self.current_region
            self.captured_image = self.screenshot.crop((x1, y1, x2, y2))
        self.root.destroy()

    def _cancel(self) -> None:
        """캡처를 취소합니다."""
        self._remove_kb_hook()
        self.captured_image = None
        if self.root:
            try:
                self.root.destroy()
            except Exception:
                pass
