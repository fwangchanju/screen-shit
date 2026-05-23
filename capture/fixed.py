"""
크기지정 캡처 모듈
config에서 저장된 크기/위치를 불러와 고정 크기 영역을 캡처합니다.

기능:
- 전체화면 오버레이 위에 선택 영역 표시 (드래그로 이동 가능)
- 하단 컨트롤 패널: 너비/높이/X/Y 입력창
- 저장 버튼: 현재 크기/위치를 config에 저장
- 고정 버튼: ON이면 입력창 비활성화 + 이동 불가
- 선택 영역 밝게, 나머지 어두운 오버레이
- Enter 또는 캡처 버튼으로 확정
- ESC: 취소
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk, ImageGrab, ImageEnhance

import config as cfg_module

_DARKEN_FACTOR = 0.45
_OUTLINE_COLOR = "#0078D4"
_OUTLINE_WIDTH = 2

# 하단 컨트롤 패널 높이
_PANEL_HEIGHT = 56

# 핸들 감지 범위
_HANDLE_SIZE = 10

# 커서 매핑
_CURSOR_MAP = {
    'move': 'fleur',
    'nw': 'size_nw_se', 'se': 'size_nw_se',
    'ne': 'size_ne_sw', 'sw': 'size_ne_sw',
    'n': 'sb_v_double_arrow', 's': 'sb_v_double_arrow',
    'e': 'sb_h_double_arrow', 'w': 'sb_h_double_arrow',
    'none': 'crosshair',
}


class FixedCapture:
    def __init__(self, master=None):
        self.master = master
        self.screenshot: Image.Image | None = None
        self.dimmed_tk: ImageTk.PhotoImage | None = None
        self.captured_image: Image.Image | None = None
        self.root: tk.Toplevel | tk.Tk | None = None
        self.canvas: tk.Canvas | None = None
        self.config: dict = {}

        # 선택 영역
        self._rx: int = 100
        self._ry: int = 100
        self._rw: int = 400
        self._rh: int = 300
        self._locked: bool = False

        # 드래그 이동
        self._drag_offset: tuple[int, int] | None = None

        # 핸들 상호작용
        self._interact_zone: str | None = None
        self._interact_start_mouse: tuple[int, int] | None = None
        self._interact_start_rect: tuple[int, int, int, int] | None = None

        # 캔버스 아이템 ID
        self._bright_item: int | None = None
        self._rect_item: int | None = None

        # GC 방지
        self._bright_tk: ImageTk.PhotoImage | None = None

        # 입력창 변수
        self._var_w: tk.StringVar | None = None
        self._var_h: tk.StringVar | None = None
        self._var_x: tk.StringVar | None = None
        self._var_y: tk.StringVar | None = None
        self._var_locked: tk.BooleanVar | None = None
        self._entry_widgets: list[ttk.Entry] = []
        self._syncing: bool = False  # _sync_vars 중 trace 재진입 방지

    def start(self) -> Image.Image | None:
        """오버레이를 시작하고 캡처된 이미지를 반환합니다. 취소 시 None."""
        self.config = cfg_module.get()
        fc = self.config.get("fixed_capture", {})
        self._rx = int(fc.get("x", 100))
        self._ry = int(fc.get("y", 100))
        self._rw = int(fc.get("width", 400))
        self._rh = int(fc.get("height", 300))
        self._locked = bool(fc.get("locked", False))

        self.screenshot = ImageGrab.grab(all_screens=False)
        sw, sh = self.screenshot.size

        enhancer = ImageEnhance.Brightness(self.screenshot)
        dimmed = enhancer.enhance(_DARKEN_FACTOR)

        if self.master:
            root = tk.Toplevel(self.master)
        else:
            root = tk.Tk()
        self.root = root

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry(f"{sw}x{sh}+0+0")
        root.focus_force()

        # 캔버스 (화면 전체)
        canvas = tk.Canvas(root, cursor="fleur", highlightthickness=0, bd=0,
                           width=sw, height=sh)
        canvas.place(x=0, y=0)
        self.canvas = canvas

        self.dimmed_tk = ImageTk.PhotoImage(dimmed)
        canvas.create_image(0, 0, anchor=tk.NW, image=self.dimmed_tk)

        # 선택 영역 밝기 레이어
        self._bright_item = canvas.create_image(0, 0, anchor=tk.NW)

        # 테두리 사각형
        self._rect_item = canvas.create_rectangle(
            0, 0, 0, 0,
            outline=_OUTLINE_COLOR,
            width=_OUTLINE_WIDTH,
            fill="",
        )

        # 하단 컨트롤 패널 (화면 내부 하단에 오버레이)
        self._build_panel(root, sw, sh)

        # 초기 선택 영역 렌더링
        self._update_display()

        # 이벤트 바인딩
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_motion)
        root.bind("<Escape>", lambda e: self._cancel())
        root.bind("<Return>", lambda e: self._confirm())
        root.bind("<KP_Enter>", lambda e: self._confirm())
        root.bind("<Left>",  lambda e: self._nudge(-1, 0))
        root.bind("<Right>", lambda e: self._nudge(1, 0))
        root.bind("<Up>",    lambda e: self._nudge(0, -1))
        root.bind("<Down>",  lambda e: self._nudge(0, 1))

        if self.master:
            self.master.wait_window(root)
        else:
            root.mainloop()

        return self.captured_image

    # ------------------------------------------------------------------
    # 하단 컨트롤 패널
    # ------------------------------------------------------------------

    def _build_panel(self, root: tk.Toplevel | tk.Tk, sw: int, sh: int) -> None:
        panel = tk.Frame(root, bg="#2b2b2b", height=_PANEL_HEIGHT)
        panel.place(x=0, y=sh - _PANEL_HEIGHT, width=sw, height=_PANEL_HEIGHT)

        self._var_w = tk.StringVar(value=str(self._rw))
        self._var_h = tk.StringVar(value=str(self._rh))
        self._var_x = tk.StringVar(value=str(self._rx))
        self._var_y = tk.StringVar(value=str(self._ry))
        self._var_locked = tk.BooleanVar(value=self._locked)

        label_style = {"bg": "#2b2b2b", "fg": "#cccccc", "font": ("맑은 고딕", 10)}
        entry_style = {"width": 6, "font": ("맑은 고딕", 10)}

        col = 8

        # 너비
        tk.Label(panel, text="너비:", **label_style).place(x=col, y=14)
        col += 36
        e_w = tk.Entry(panel, textvariable=self._var_w, **entry_style)
        e_w.place(x=col, y=12)
        col += 58

        # 높이
        tk.Label(panel, text="높이:", **label_style).place(x=col, y=14)
        col += 36
        e_h = tk.Entry(panel, textvariable=self._var_h, **entry_style)
        e_h.place(x=col, y=12)
        col += 58

        # X
        tk.Label(panel, text="X:", **label_style).place(x=col, y=14)
        col += 22
        e_x = tk.Entry(panel, textvariable=self._var_x, **entry_style)
        e_x.place(x=col, y=12)
        col += 58

        # Y
        tk.Label(panel, text="Y:", **label_style).place(x=col, y=14)
        col += 22
        e_y = tk.Entry(panel, textvariable=self._var_y, **entry_style)
        e_y.place(x=col, y=12)
        col += 66

        self._entry_widgets = [e_w, e_h, e_x, e_y]

        # 입력창 변경 시 영역 업데이트
        for var in (self._var_w, self._var_h, self._var_x, self._var_y):
            var.trace_add("write", self._on_entry_change)

        # 저장 버튼
        btn_save = tk.Button(
            panel, text="저장", bg="#444444", fg="white",
            font=("맑은 고딕", 10), relief=tk.FLAT, padx=8,
            command=self._save_config,
        )
        btn_save.place(x=col, y=10)
        col += 50

        # 고정 버튼
        self._btn_lock = tk.Button(
            panel, text="🔒 고정", bg="#444444", fg="white",
            font=("맑은 고딕", 10), relief=tk.FLAT, padx=8,
            command=self._toggle_lock,
        )
        self._btn_lock.place(x=col, y=10)
        col += 66

        # 캡처 버튼
        btn_capture = tk.Button(
            panel, text="캡처", bg="#0078D4", fg="white",
            font=("맑은 고딕", 10, "bold"), relief=tk.FLAT, padx=10,
            command=self._confirm,
        )
        btn_capture.place(x=col, y=10)
        col += 58

        # ESC 안내
        tk.Label(panel, text="ESC 취소", **label_style).place(x=col, y=14)

        # 고정 상태 초기 적용
        self._apply_lock_state()

    # ------------------------------------------------------------------
    # 히트 테스트
    # ------------------------------------------------------------------

    def _hit_test(self, mx: int, my: int) -> str:
        """마우스 위치에 따른 상호작용 구역 반환."""
        x1, y1 = self._rx, self._ry
        x2, y2 = x1 + self._rw, y1 + self._rh
        H = _HANDLE_SIZE

        in_x = x1 - H <= mx <= x2 + H
        in_y = y1 - H <= my <= y2 + H
        if not (in_x and in_y):
            return 'none'

        near_left = abs(mx - x1) <= H
        near_right = abs(mx - x2) <= H
        near_top = abs(my - y1) <= H
        near_bottom = abs(my - y2) <= H

        if near_top and near_left:
            return 'nw'
        if near_top and near_right:
            return 'ne'
        if near_bottom and near_left:
            return 'sw'
        if near_bottom and near_right:
            return 'se'
        if near_top:
            return 'n'
        if near_bottom:
            return 's'
        if near_left:
            return 'w'
        if near_right:
            return 'e'
        if x1 <= mx <= x2 and y1 <= my <= y2:
            return 'move'
        return 'none'

    # ------------------------------------------------------------------
    # 이벤트 핸들러
    # ------------------------------------------------------------------

    def _on_motion(self, event: tk.Event) -> None:
        if self._locked:
            self.canvas.config(cursor="arrow")
            return
        zone = self._hit_test(event.x, event.y)
        self.canvas.config(cursor=_CURSOR_MAP.get(zone, 'crosshair'))

    def _on_press(self, event: tk.Event) -> None:
        if self._locked:
            return
        zone = self._hit_test(event.x, event.y)
        if zone == 'none':
            return
        self._interact_zone = zone
        self._interact_start_mouse = (event.x, event.y)
        self._interact_start_rect = (self._rx, self._ry,
                                     self._rx + self._rw, self._ry + self._rh)

    def _on_drag(self, event: tk.Event) -> None:
        if self._locked or self._interact_zone is None:
            return
        self._do_interact(event.x, event.y)

    def _do_interact(self, mx: int, my: int) -> None:
        """핸들 드래그로 선택 영역을 이동/크기 조정합니다."""
        x1, y1, x2, y2 = self._interact_start_rect
        sx, sy = self._interact_start_mouse
        dx = mx - sx
        dy = my - sy
        sw, sh = self.screenshot.size
        zone = self._interact_zone

        if zone == 'move':
            new_x = max(0, min(x1 + dx, sw - self._rw))
            new_y = max(0, min(y1 + dy, sh - self._rh))
            self._rx, self._ry = new_x, new_y
        elif zone == 'se':
            self._rw = max(10, x2 + dx - self._rx)
            self._rh = max(10, y2 + dy - self._ry)
        elif zone == 'nw':
            new_x = min(x1 + dx, x2 - 10)
            new_y = min(y1 + dy, y2 - 10)
            self._rw = x2 - new_x
            self._rh = y2 - new_y
            self._rx, self._ry = new_x, new_y
        elif zone == 'ne':
            new_y = min(y1 + dy, y2 - 10)
            self._rw = max(10, x2 + dx - self._rx)
            self._rh = y2 - new_y
            self._ry = new_y
        elif zone == 'sw':
            new_x = min(x1 + dx, x2 - 10)
            self._rw = x2 - new_x
            self._rh = max(10, y2 + dy - self._ry)
            self._rx = new_x
        elif zone == 'n':
            new_y = max(0, min(y1 + dy, y2 - 10))
            self._rh = y2 - new_y
            self._ry = new_y
        elif zone == 's':
            self._rh = max(10, y2 + dy - self._ry)
        elif zone == 'e':
            self._rw = max(10, x2 + dx - self._rx)
        elif zone == 'w':
            new_x = min(x1 + dx, x2 - 10)
            self._rw = x2 - new_x
            self._rx = new_x

        self._sync_vars()
        self._update_display()

    def _on_release(self, event: tk.Event) -> None:
        self._interact_zone = None
        self._interact_start_mouse = None
        self._interact_start_rect = None

    def _on_entry_change(self, *args) -> None:
        """입력창 변경 시 영역 좌표를 업데이트합니다."""
        if self._syncing:
            return
        try:
            w = max(10, int(self._var_w.get()))
            h = max(10, int(self._var_h.get()))
            x = int(self._var_x.get())
            y = int(self._var_y.get())
            self._rw = w
            self._rh = h
            self._rx = x
            self._ry = y
            self._update_display()
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # 저장 / 고정 / 확정 / 취소
    # ------------------------------------------------------------------

    def _save_config(self) -> None:
        """현재 크기/위치를 settings.json에 저장합니다."""
        self.config["fixed_capture"] = {
            "x": self._rx,
            "y": self._ry,
            "width": self._rw,
            "height": self._rh,
            "locked": self._locked,
        }
        cfg_module.save(self.config)

    def _toggle_lock(self) -> None:
        self._locked = not self._locked
        self._var_locked.set(self._locked)
        self._apply_lock_state()
        self.canvas.config(cursor="arrow" if self._locked else "fleur")

    def _apply_lock_state(self) -> None:
        state = tk.DISABLED if self._locked else tk.NORMAL
        for entry in self._entry_widgets:
            entry.config(state=state)
        if self._locked:
            self._btn_lock.config(text="🔒 고정됨", bg="#885500")
        else:
            self._btn_lock.config(text="🔒 고정", bg="#444444")

    def _nudge(self, dx: int, dy: int) -> None:
        """방향키로 선택 영역을 이동합니다."""
        if self._locked:
            return
        sw, sh = self.screenshot.size
        self._rx = max(0, min(self._rx + dx, sw - self._rw))
        self._ry = max(0, min(self._ry + dy, sh - self._rh))
        self._sync_vars()
        self._update_display()

    def _confirm(self) -> None:
        sw, sh = self.screenshot.size
        x1 = max(0, min(self._rx, sw))
        y1 = max(0, min(self._ry, sh))
        x2 = max(0, min(self._rx + self._rw, sw))
        y2 = max(0, min(self._ry + self._rh, sh))
        if x2 > x1 and y2 > y1:
            self.captured_image = self.screenshot.crop((x1, y1, x2, y2))
        # 확정 시 현재 크기/위치 자동 저장
        self._save_config()
        self.root.destroy()

    def _cancel(self) -> None:
        self.captured_image = None
        self.root.destroy()

    # ------------------------------------------------------------------
    # 디스플레이 업데이트
    # ------------------------------------------------------------------

    def _sync_vars(self) -> None:
        """내부 좌표를 입력창 변수에 동기화합니다."""
        self._syncing = True
        try:
            if self._var_w:
                self._var_w.set(str(self._rw))
            if self._var_h:
                self._var_h.set(str(self._rh))
            if self._var_x:
                self._var_x.set(str(self._rx))
            if self._var_y:
                self._var_y.set(str(self._ry))
        finally:
            self._syncing = False

    def _update_display(self) -> None:
        """선택 영역을 캔버스에 렌더링합니다."""
        if self.screenshot is None:
            return
        sw, sh = self.screenshot.size
        x1 = max(0, min(self._rx, sw))
        y1 = max(0, min(self._ry, sh))
        x2 = max(0, min(self._rx + self._rw, sw))
        y2 = max(0, min(self._ry + self._rh, sh))

        if x2 <= x1 or y2 <= y1:
            return

        crop = self.screenshot.crop((x1, y1, x2, y2))
        tk_crop = ImageTk.PhotoImage(crop)
        self._bright_tk = tk_crop  # GC 방지

        self.canvas.coords(self._bright_item, x1, y1)
        self.canvas.itemconfig(self._bright_item, image=tk_crop)
        self.canvas.coords(self._rect_item, x1, y1, x2, y2)
