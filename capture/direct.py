"""
직접지정 캡처 모듈
전체화면 오버레이에서 마우스 드래그로 영역을 선택합니다.

기능:
- 드래그 중: 선택 영역 밝게, 나머지 어두운 오버레이
- 드래그 중 하단 크기 표시 (예: "367 x 514")
- 돋보기: 마우스 커서 주변을 4배 확대하여 커서 옆에 표시 (100x100px)
- Ctrl + 드래그: 끝점이 1/8 속도로 느리게 이동 (정밀 선택)
- 드래그 완료 후 선택 영역 이동/크기 조정: 모서리·가장자리 핸들 드래그
- 드래그 완료 후 방향키로 선택 영역 전체 이동, Enter로 확정
- ESC: 취소
"""
from __future__ import annotations

import tkinter as tk
from PIL import Image, ImageTk, ImageGrab, ImageEnhance

_DARKEN_FACTOR = 0.45
_OUTLINE_COLOR = "#0078D4"
_OUTLINE_WIDTH = 2
_SIZE_LABEL_FONT = ("맑은 고딕", 11, "bold")

# 돋보기 설정
_MAGNIFIER_SIZE = 150   # 돋보기 박스 크기 (픽셀)
_MAGNIFIER_ZOOM = 4     # 확대 배율
_MAGNIFIER_OFFSET = 16  # 커서와 돋보기 박스 사이 간격

# 핸들 감지 범위 (픽셀)
_HANDLE_SIZE = 8

# drag_done 상태에서의 커서 매핑
_CURSOR_MAP = {
    'move': 'fleur',
    'nw': 'size_nw_se', 'se': 'size_nw_se',
    'ne': 'size_ne_sw', 'sw': 'size_ne_sw',
    'n': 'sb_v_double_arrow', 's': 'sb_v_double_arrow',
    'e': 'sb_h_double_arrow', 'w': 'sb_h_double_arrow',
    'none': 'crosshair',
}


class DirectCapture:
    def __init__(self, master=None, on_drag_start=None, on_overlay_ready=None):
        self.master = master
        self._on_drag_start = on_drag_start
        self._on_overlay_ready = on_overlay_ready
        self.screenshot: Image.Image | None = None
        self.dimmed_tk: ImageTk.PhotoImage | None = None
        self.captured_image: Image.Image | None = None
        self.root: tk.Toplevel | tk.Tk | None = None
        self.canvas: tk.Canvas | None = None

        # 드래그 상태
        self._drag_start: tuple[int, int] | None = None
        self._drag_end: tuple[int, int] | None = None
        self._dragging = False
        self._drag_done = False  # 드래그 완료 후 조작 모드

        # Ctrl 드래그용 누적 변수
        self._slow_accum: tuple[float, float] = (0.0, 0.0)
        self._last_raw: tuple[int, int] = (0, 0)

        # 선택 영역 상호작용 (drag_done 상태에서 핸들 조작)
        self._interact_zone: str | None = None
        self._interact_start_mouse: tuple[int, int] | None = None
        self._interact_start_rect: tuple[int, int, int, int] | None = None
        # Ctrl 미세조정용 누적 (interact 중)
        self._interact_slow_accum: tuple[float, float] = (0.0, 0.0)
        self._interact_last_raw: tuple[int, int] = (0, 0)

        # 캔버스 아이템 ID
        self._bright_item: int | None = None
        self._rect_item: int | None = None
        self._size_label_item: int | None = None
        self._size_shadow_item: int | None = None
        self._magnifier_item: int | None = None
        self._magnifier_border: int | None = None

        # GC 방지 참조
        self._bright_tk: ImageTk.PhotoImage | None = None
        self._magnifier_tk: ImageTk.PhotoImage | None = None

    def start(self) -> Image.Image | None:
        """오버레이를 시작하고 캡처된 이미지를 반환합니다. 취소 시 None."""
        import ctypes
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
        dimmed = enhancer.enhance(_DARKEN_FACTOR)

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

        # 선택 영역 밝기 레이어
        self._bright_item = canvas.create_image(0, 0, anchor=tk.NW)

        # 선택 사각형 테두리
        self._rect_item = canvas.create_rectangle(
            0, 0, 0, 0,
            outline=_OUTLINE_COLOR,
            width=_OUTLINE_WIDTH,
            fill="",
        )

        # 크기 라벨 (그림자 + 본문)
        self._size_shadow_item = canvas.create_text(
            0, 0, text="", fill="black", font=_SIZE_LABEL_FONT,
            anchor=tk.NW, state=tk.HIDDEN,
        )
        self._size_label_item = canvas.create_text(
            0, 0, text="", fill="white", font=_SIZE_LABEL_FONT,
            anchor=tk.NW, state=tk.HIDDEN,
        )

        # 돋보기 테두리 + 이미지
        self._magnifier_border = canvas.create_rectangle(
            0, 0, 0, 0,
            outline="#ffffff",
            width=2,
            fill="",
            state=tk.HIDDEN,
        )
        self._magnifier_item = canvas.create_image(0, 0, anchor=tk.NW, state=tk.HIDDEN)

        # 오버레이 생성 완료 → 50ms 후 콜백 (툴바를 오버레이 위로 lift)
        if self._on_overlay_ready:
            root.after(50, self._on_overlay_ready)

        # 이벤트 바인딩
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<Motion>", self._on_motion)
        root.bind("<Escape>", lambda e: self._cancel())
        root.bind("<Return>", lambda e: self._confirm())
        root.bind("<KP_Enter>", lambda e: self._confirm())
        root.bind("<Left>", lambda e: self._nudge(-1, 0))
        root.bind("<Right>", lambda e: self._nudge(1, 0))
        root.bind("<Up>", lambda e: self._nudge(0, -1))
        root.bind("<Down>", lambda e: self._nudge(0, 1))

        # 3-2 item 7: keyboard 라이브러리 레벨 ESC 훅 (포커스 문제 보완)
        self._kb_esc_hook = None
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
    # 히트 테스트
    # ------------------------------------------------------------------

    def _hit_test(self, mx: int, my: int) -> str:
        """마우스 위치 기준 상호작용 구역을 반환합니다.

        Returns: 'move' | 'nw' | 'ne' | 'sw' | 'se' |
                 'n' | 's' | 'e' | 'w' | 'none'
        """
        x1, y1, x2, y2 = self._get_rect()
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

        # 내부: 이동
        if x1 <= mx <= x2 and y1 <= my <= y2:
            return 'move'
        return 'none'

    # ------------------------------------------------------------------
    # 이벤트 핸들러
    # ------------------------------------------------------------------

    def _on_motion(self, event: tk.Event) -> None:
        """마우스 이동 이벤트."""
        if self._drag_done:
            zone = self._hit_test(event.x, event.y)
            self.canvas.config(cursor=_CURSOR_MAP.get(zone, 'crosshair'))
        elif not self._dragging:
            self._update_magnifier(event.x, event.y)

    def _on_press(self, event: tk.Event) -> None:
        """마우스 버튼 누름 이벤트."""
        # 3-2 item 2: 드래그 시작 시 툴바 숨기기
        if self._on_drag_start and not self._drag_done:
            try:
                self._on_drag_start()
            except Exception:
                pass

        if self._drag_done:
            zone = self._hit_test(event.x, event.y)
            if zone == 'none':
                self._drag_done = False
                self._drag_start = (event.x, event.y)
                self._drag_end = (event.x, event.y)
                self._dragging = True
                self._slow_accum = (0.0, 0.0)
                self._last_raw = (event.x, event.y)
                self._interact_zone = None
            else:
                self._interact_zone = zone
                self._interact_start_mouse = (event.x, event.y)
                self._interact_start_rect = self._get_rect()
                self._interact_slow_accum = (0.0, 0.0)
                self._interact_last_raw = (event.x, event.y)
                self._dragging = True
            return

        # 새 선택 시작
        self._drag_start = (event.x, event.y)
        self._drag_end = (event.x, event.y)
        self._dragging = True
        self._drag_done = False
        self._slow_accum = (0.0, 0.0)
        self._last_raw = (event.x, event.y)
        self._interact_zone = None

    def _on_drag(self, event: tk.Event) -> None:
        """마우스 드래그 이벤트."""
        if not self._dragging:
            return

        # drag_done 상태에서 핸들 조작 중
        if self._drag_done and self._interact_zone:
            self._do_interact(event)
            return

        # 일반 드래그: Ctrl 키 감지
        raw_x, raw_y = event.x, event.y

        if event.state & 0x4:  # Ctrl 키 (tkinter state bitmask)
            # Ctrl 모드: 누적된 부분 이동량으로 느리게 (1/8 속도)
            dx = (raw_x - self._last_raw[0]) / 8
            dy = (raw_y - self._last_raw[1]) / 8
            self._slow_accum = (
                self._slow_accum[0] + dx,
                self._slow_accum[1] + dy,
            )
            # 1픽셀 이상 누적됐을 때만 실제 이동
            ex = self._drag_end[0] + int(self._slow_accum[0])
            ey = self._drag_end[1] + int(self._slow_accum[1])
            self._slow_accum = (
                self._slow_accum[0] - int(self._slow_accum[0]),
                self._slow_accum[1] - int(self._slow_accum[1]),
            )
            self._drag_end = (ex, ey)
        else:
            self._drag_end = (raw_x, raw_y)
            self._slow_accum = (0.0, 0.0)

        self._last_raw = (raw_x, raw_y)
        self._update_selection()
        self._update_magnifier(raw_x, raw_y)

    def _on_release(self, event: tk.Event) -> None:
        """마우스 버튼 릴리즈 이벤트."""
        if not self._dragging:
            return
        self._dragging = False

        # 핸들 조작 완료
        if self._interact_zone:
            self._interact_zone = None
            return

        self._drag_end = (event.x, event.y)
        self._drag_done = True

        # 선택 영역이 너무 작으면 (클릭 수준) 무시
        x1, y1, x2, y2 = self._get_rect()
        if abs(x2 - x1) < 5 and abs(y2 - y1) < 5:
            self._drag_done = False
            self._drag_start = None
            self._drag_end = None
            self._clear_selection()
            return

        self._update_selection()
        self._hide_magnifier()
        # 간편캡처: 드래그 완료 즉시 확정 → 편집기 진입
        self._confirm()

    # ------------------------------------------------------------------
    # 핸들 상호작용 (drag_done 상태)
    # ------------------------------------------------------------------

    def _do_interact(self, event) -> None:
        """핸들 드래그로 선택 영역을 이동/크기 조정합니다. Ctrl: 1/8 속도 미세조정."""
        raw_x, raw_y = event.x, event.y
        zone = self._interact_zone

        if event.state & 0x4:  # Ctrl 키
            ddx = (raw_x - self._interact_last_raw[0]) / 8
            ddy = (raw_y - self._interact_last_raw[1]) / 8
            ax = self._interact_slow_accum[0] + ddx
            ay = self._interact_slow_accum[1] + ddy
            ix = int(ax)
            iy = int(ay)
            self._interact_slow_accum = (ax - ix, ay - iy)
            # 누적량을 기준점에 반영
            self._interact_start_mouse = (
                self._interact_start_mouse[0] - ix,
                self._interact_start_mouse[1] - iy,
            )
        else:
            self._interact_slow_accum = (0.0, 0.0)

        self._interact_last_raw = (raw_x, raw_y)

        x1, y1, x2, y2 = self._interact_start_rect
        sx, sy = self._interact_start_mouse
        dx = raw_x - sx
        dy = raw_y - sy

        if zone == 'move':
            self._drag_start = (x1 + dx, y1 + dy)
            self._drag_end = (x2 + dx, y2 + dy)
        elif zone == 'se':
            self._drag_end = (x2 + dx, y2 + dy)
        elif zone == 'nw':
            self._drag_start = (x1 + dx, y1 + dy)
        elif zone == 'ne':
            self._drag_start = (x1, y1 + dy)
            self._drag_end = (x2 + dx, y2)
        elif zone == 'sw':
            self._drag_start = (x1 + dx, y1)
            self._drag_end = (x2, y2 + dy)
        elif zone == 'n':
            self._drag_start = (x1, y1 + dy)
        elif zone == 's':
            self._drag_end = (x2, y2 + dy)
        elif zone == 'e':
            self._drag_end = (x2 + dx, y2)
        elif zone == 'w':
            self._drag_start = (x1 + dx, y1)

        self._update_selection()

    # ------------------------------------------------------------------
    # 방향키 이동
    # ------------------------------------------------------------------

    def _nudge(self, dx: int, dy: int) -> None:
        """방향키로 선택 영역 전체를 이동합니다."""
        if not self._drag_done:
            return
        if self._drag_start is None or self._drag_end is None:
            return
        sx, sy = self._drag_start
        ex, ey = self._drag_end
        self._drag_start = (sx + dx, sy + dy)
        self._drag_end = (ex + dx, ey + dy)
        self._update_selection()

    # ------------------------------------------------------------------
    # 확정 / 취소
    # ------------------------------------------------------------------

    def _remove_kb_hook(self) -> None:
        """keyboard ESC 훅을 안전하게 제거합니다."""
        if self._kb_esc_hook is not None:
            try:
                import keyboard as _kb
                _kb.remove_hotkey(self._kb_esc_hook)
            except Exception:
                pass
            self._kb_esc_hook = None

    def _confirm(self) -> None:
        self._remove_kb_hook()
        if self._drag_done and self._drag_start and self._drag_end:
            x1, y1, x2, y2 = self._get_rect()
            sw, sh = self.screenshot.size
            x1 = max(0, min(x1, sw))
            y1 = max(0, min(y1, sh))
            x2 = max(0, min(x2, sw))
            y2 = max(0, min(y2, sh))
            if x2 > x1 and y2 > y1:
                self.captured_image = self.screenshot.crop((x1, y1, x2, y2))
        self.root.destroy()

    def _cancel(self) -> None:
        self._remove_kb_hook()
        self.captured_image = None
        self.root.destroy()

    # ------------------------------------------------------------------
    # UI 업데이트
    # ------------------------------------------------------------------

    def _get_rect(self) -> tuple[int, int, int, int]:
        """정규화된 (x1, y1, x2, y2) 반환."""
        if self._drag_start is None or self._drag_end is None:
            return (0, 0, 0, 0)
        sx, sy = self._drag_start
        ex, ey = self._drag_end
        return (min(sx, ex), min(sy, ey), max(sx, ex), max(sy, ey))

    def _update_selection(self) -> None:
        x1, y1, x2, y2 = self._get_rect()
        w = x2 - x1
        h = y2 - y1

        if w <= 0 or h <= 0:
            self._clear_selection()
            return

        # 선택 영역: 원본 밝기
        crop = self.screenshot.crop((x1, y1, x2, y2))
        tk_crop = ImageTk.PhotoImage(crop)
        self._bright_tk = tk_crop  # GC 방지

        self.canvas.coords(self._bright_item, x1, y1)
        self.canvas.itemconfig(self._bright_item, image=tk_crop)

        # 테두리 사각형
        self.canvas.coords(self._rect_item, x1, y1, x2, y2)

        # 크기 라벨 위치 (선택 영역 하단 좌측, 화면 밖으로 나가지 않도록)
        sw, sh = self.screenshot.size
        label_text = f"{w} x {h}"
        lx = x1 + 4
        ly = y2 + 6
        if ly + 24 > sh:
            ly = y1 - 24
        if lx + len(label_text) * 9 > sw:
            lx = sw - len(label_text) * 9

        self.canvas.itemconfig(self._size_shadow_item, text=label_text, state=tk.NORMAL)
        self.canvas.itemconfig(self._size_label_item, text=label_text, state=tk.NORMAL)
        self.canvas.coords(self._size_shadow_item, lx + 1, ly + 1)
        self.canvas.coords(self._size_label_item, lx, ly)

    def _clear_selection(self) -> None:
        self.canvas.itemconfig(self._bright_item, image="")
        self.canvas.coords(self._rect_item, 0, 0, 0, 0)
        self.canvas.itemconfig(self._size_label_item, state=tk.HIDDEN)
        self.canvas.itemconfig(self._size_shadow_item, state=tk.HIDDEN)

    def _update_magnifier(self, mx: int, my: int) -> None:
        """마우스 커서 주변을 돋보기로 확대 표시합니다."""
        import PIL.ImageDraw as ImageDraw

        half = _MAGNIFIER_SIZE // _MAGNIFIER_ZOOM // 2  # 원본에서 캡처할 반경
        sw, sh = self.screenshot.size

        src_x1 = max(0, mx - half)
        src_y1 = max(0, my - half)
        src_x2 = min(sw, mx + half)
        src_y2 = min(sh, my + half)

        if src_x2 <= src_x1 or src_y2 <= src_y1:
            self._hide_magnifier()
            return

        # 원본 캡처 후 확대
        region = self.screenshot.crop((src_x1, src_y1, src_x2, src_y2))
        magnified = region.resize(
            (_MAGNIFIER_SIZE, _MAGNIFIER_SIZE),
            Image.NEAREST,
        )

        # 십자선 그리기
        draw = ImageDraw.Draw(magnified)
        cx = _MAGNIFIER_SIZE // 2
        cy = _MAGNIFIER_SIZE // 2
        draw.line([(cx, 0), (cx, _MAGNIFIER_SIZE)], fill="#ff0000", width=1)
        draw.line([(0, cy), (_MAGNIFIER_SIZE, cy)], fill="#ff0000", width=1)

        tk_mag = ImageTk.PhotoImage(magnified)
        self._magnifier_tk = tk_mag  # GC 방지

        # 19회차 item 11: 돋보기 중심을 커서 위치에 맞춤
        bx = mx - _MAGNIFIER_SIZE // 2
        by = my - _MAGNIFIER_SIZE // 2
        # 화면 경계 클리핑
        bx = max(0, min(bx, sw - _MAGNIFIER_SIZE))
        by = max(0, min(by, sh - _MAGNIFIER_SIZE))

        self.canvas.coords(self._magnifier_border, bx - 2, by - 2,
                           bx + _MAGNIFIER_SIZE + 2, by + _MAGNIFIER_SIZE + 2)
        self.canvas.itemconfig(self._magnifier_border, state=tk.NORMAL)
        self.canvas.coords(self._magnifier_item, bx, by)
        self.canvas.itemconfig(self._magnifier_item, image=tk_mag, state=tk.NORMAL)

    def _hide_magnifier(self) -> None:
        self.canvas.itemconfig(self._magnifier_item, state=tk.HIDDEN)
        self.canvas.itemconfig(self._magnifier_border, state=tk.HIDDEN)

