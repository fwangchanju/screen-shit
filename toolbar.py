"""
메인 툴바 창.
항상 최상단 고정, 타이틀바 없음, 드래그로 이동 가능.

레이아웃:
┌──────────────────────────────────────────────────────┐
│ [📋 캡처목록] | [✂ 직접지정] [⬛ 단위영역] [⬜ 크기지정] | [단축키 F8▼] [🗜 압축ON] │
└──────────────────────────────────────────────────────┘

main.py의 호출 방식:
    toolbar = Toolbar(root, mode_var=mode_var, on_capture=trigger_capture)
    toolbar.run()
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────────
# config 임포트 (없으면 기본값 사용)
# ──────────────────────────────────────────────────────────────
try:
    from config import get as _cfg_get, save as _cfg_save
except Exception:
    _cfg_get = lambda: {"hotkey": "f8", "compress": False}  # type: ignore
    _cfg_save = lambda c: None  # type: ignore


HOTKEY_OPTIONS = [f"f{i}" for i in range(1, 13)]  # f1 ~ f12
HOTKEY_DISPLAY = {f"f{i}": f"F{i}" for i in range(1, 13)}

TOOLBAR_BG   = "#F3F3F3"
BTN_BG       = "#F3F3F3"
BTN_HOVER_BG = "#E5F0FF"
BTN_ACTIVE_BG = "#CCE4FF"
BORDER_COLOR = "#DEDEDE"
ACCENT_COLOR = "#0078D4"


# ──────────────────────────────────────────────────────────────
# Toolbar 클래스
# ──────────────────────────────────────────────────────────────

class Toolbar:
    """메인 툴바 창.

    Parameters
    ----------
    root : tk.Tk
        메인 tkinter 루트 창 (main.py에서 전달).
    mode_var : tk.StringVar, optional
        현재 선택된 캡처 모드 ('direct' | 'smart' | 'fixed').
    on_capture : Callable[[tk.Tk, tk.StringVar], None], optional
        캡처 버튼 / 단축키 트리거 시 호출되는 콜백.
    on_show_list : Callable[[], None], optional
        캡처 목록 버튼 클릭 시 호출됩니다.
    on_hotkey_changed : Callable[[str], None], optional
        단축키 변경 시 호출됩니다. 인자: 새 단축키 문자열 (예: 'f8')
    """

    def __init__(
        self,
        root: tk.Tk,
        mode_var: Optional[tk.StringVar] = None,
        on_capture: Optional[Callable] = None,
        on_show_list: Optional[Callable[[], None]] = None,
        on_hotkey_changed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._root = root
        self._mode_var = mode_var if mode_var is not None else tk.StringVar(value="smart")
        self._on_capture = on_capture
        self._on_show_list = on_show_list
        self._on_hotkey_changed = on_hotkey_changed

        # 창 이동을 위한 상태
        self._drag_start_x: int = 0
        self._drag_start_y: int = 0

        # 설정 로드
        cfg = _cfg_get()
        self._hotkey: str = cfg.get("hotkey", "f8")
        self._compress: bool = cfg.get("compress", False)

        # 툴바 창 (overrideredirect Toplevel)
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)        # 타이틀바 없음
        self.win.attributes("-topmost", True)  # 항상 위
        self.win.configure(bg=TOOLBAR_BG)

        self._build()
        self._position_window()

    # ──────────────────────────────────────────────
    # 창 구성
    # ──────────────────────────────────────────────

    def _build(self) -> None:
        """툴바 위젯을 구성합니다."""
        outer = tk.Frame(self.win, bg=BORDER_COLOR, bd=1, relief=tk.RIDGE)
        outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        inner = tk.Frame(outer, bg=TOOLBAR_BG, pady=2)
        inner.pack(fill=tk.BOTH, expand=True)

        self._main_frame = inner

        def sep():
            tk.Frame(inner, width=1, bg=BORDER_COLOR).pack(
                side=tk.LEFT, fill=tk.Y, padx=4, pady=4
            )

        # ── 캡처 목록 버튼 ──
        self._btn_list = self._make_icon_button(
            inner, "📋", "캡처목록", self._on_list_click
        )

        sep()

        # ── 캡처 모드 버튼 (선택만 — 캡쳐는 단축키로) ──
        self._btn_direct = self._make_icon_button(
            inner, "✂", "직접지정", lambda: self._select_mode("direct"),
            with_indicator=True,
        )
        self._btn_smart = self._make_icon_button(
            inner, "⬛", "단위영역", lambda: self._select_mode("smart"),
            with_indicator=True,
        )
        self._btn_fixed = self._make_icon_button(
            inner, "⬜", "크기지정", lambda: self._select_mode("fixed"),
            with_indicator=True,
        )

        # 모드 변경 시 자동 강조 갱신
        self._mode_var.trace_add("write", lambda *_: self._update_mode_highlight())
        self._update_mode_highlight()

        sep()

        # ── 단축키 콤보박스 ──
        self._hotkey_var = tk.StringVar(value=HOTKEY_DISPLAY.get(self._hotkey, "F8"))
        self._hotkey_frame = self._make_hotkey_widget(inner)

        # ── 압축 토글 버튼 ──
        self._compress_frame, self._compress_icon_lbl, self._compress_text_lbl = \
            self._make_compress_button(inner)

        sep()

        # ── 최소화 버튼 ──
        self._make_icon_button(inner, "—", "최소화", self._minimize_to_tray)

        # ── F-키 단축키 (창 포커스 시) ──
        self.win.bind(f"<{self._hotkey.upper()}>",
                      lambda e: self._trigger_default_capture())
        # 루트에도 바인딩
        self._root.bind(f"<{self._hotkey.upper()}>",
                        lambda e: self._trigger_default_capture())

        # ── 우클릭 메뉴 (종료) ──
        self.win.bind("<Button-3>", self._show_context_menu)
        outer.bind("<Button-3>", self._show_context_menu)
        inner.bind("<Button-3>", self._show_context_menu)

        # ── 드래그로 창 이동 ──
        for widget in (self.win, outer, inner):
            widget.bind("<ButtonPress-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)

    def _make_icon_button(self, parent: tk.Widget, icon: str, text: str,
                          command: Callable, with_indicator: bool = False) -> tk.Frame:
        """아이콘(위) + 텍스트(아래) 스타일의 Frame 기반 버튼을 만들어 반환합니다."""
        frame = tk.Frame(parent, bg=BTN_BG, padx=8, pady=2, cursor="hand2")
        frame.pack(side=tk.LEFT, padx=1)

        lbl_icon = tk.Label(frame, text=icon, bg=BTN_BG,
                            font=("맑은 고딕", 16))
        lbl_icon.pack(pady=(4, 0))

        lbl_text = tk.Label(frame, text=text, bg=BTN_BG,
                            font=("맑은 고딕", 8))
        lbl_text.pack()

        # 활성 모드 표시용 하단 인디케이터
        if with_indicator:
            indicator = tk.Frame(frame, height=3, bg=BTN_BG)
            indicator.pack(fill=tk.X, pady=(2, 0))
            frame._indicator = indicator
            frame._lbl_icon = lbl_icon
            frame._lbl_text = lbl_text
        else:
            frame._indicator = None

        def _all_widgets():
            ws = [frame, lbl_icon, lbl_text]
            if with_indicator:
                ws.append(indicator)
            return ws

        def on_enter(e):
            if not getattr(frame, '_active', False):
                frame.config(bg=BTN_HOVER_BG)
                lbl_icon.config(bg=BTN_HOVER_BG)
                lbl_text.config(bg=BTN_HOVER_BG)

        def on_leave(e):
            if not getattr(frame, '_active', False):
                frame.config(bg=BTN_BG)
                lbl_icon.config(bg=BTN_BG)
                lbl_text.config(bg=BTN_BG)

        def on_click(e):
            command()

        def on_press(e):
            frame.config(bg=BTN_ACTIVE_BG)
            lbl_icon.config(bg=BTN_ACTIVE_BG)
            lbl_text.config(bg=BTN_ACTIVE_BG)

        for w in _all_widgets():
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_press)
            w.bind("<ButtonRelease-1>", lambda e, fn=on_click: fn(e))

        # 드래그 이동도 유지
        for w in _all_widgets():
            w.bind("<ButtonPress-1>", lambda e, fn=on_press: (fn(e), self._on_drag_start(e)), add="+")
            w.bind("<B1-Motion>", self._on_drag_motion, add="+")

        frame._active = False
        return frame

    def _make_hotkey_widget(self, parent: tk.Widget) -> tk.Frame:
        """단축키 콤보박스 위젯을 만들어 반환합니다."""
        frame = tk.Frame(parent, bg=BTN_BG, padx=6, pady=2)
        frame.pack(side=tk.LEFT, padx=1)

        lbl_title = tk.Label(frame, text="단축키", bg=BTN_BG,
                             font=("맑은 고딕", 8))
        lbl_title.pack(pady=(4, 0))

        combo = ttk.Combobox(
            frame,
            values=[f"F{i}" for i in range(1, 13)],
            state="readonly",
            width=4,
            font=("맑은 고딕", 10),
        )
        combo.set(HOTKEY_DISPLAY.get(self._hotkey, "F8"))
        combo.pack(pady=(0, 4))
        combo.bind("<<ComboboxSelected>>", self._on_hotkey_combo_select)
        self._hotkey_combo = combo

        # 콤보박스는 드래그 이동에 방해되지 않도록 frame/label에만 바인딩
        for w in (frame, lbl_title):
            w.bind("<ButtonPress-1>", self._on_drag_start)
            w.bind("<B1-Motion>", self._on_drag_motion)

        return frame

    def _make_compress_button(self, parent: tk.Widget):
        """압축 토글 버튼(Frame + 라벨 2개)을 만들어 반환합니다."""
        icon_text, label_text, fg_color = self._compress_parts()

        frame = tk.Frame(parent, bg=BTN_BG, padx=8, pady=4, cursor="hand2")
        frame.pack(side=tk.LEFT, padx=1)

        lbl_icon = tk.Label(frame, text=icon_text, bg=BTN_BG,
                            font=("맑은 고딕", 16))
        lbl_icon.pack()

        lbl_text = tk.Label(frame, text=label_text, bg=BTN_BG,
                            font=("맑은 고딕", 8), fg=fg_color)
        lbl_text.pack()

        def on_enter(e):
            frame.config(bg=BTN_HOVER_BG)
            lbl_icon.config(bg=BTN_HOVER_BG)
            lbl_text.config(bg=BTN_HOVER_BG)

        def on_leave(e):
            frame.config(bg=BTN_BG)
            lbl_icon.config(bg=BTN_BG)
            lbl_text.config(bg=BTN_BG)

        def on_press(e):
            frame.config(bg=BTN_ACTIVE_BG)
            lbl_icon.config(bg=BTN_ACTIVE_BG)
            lbl_text.config(bg=BTN_ACTIVE_BG)

        def on_click(e):
            self._toggle_compress()

        for w in (frame, lbl_icon, lbl_text):
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", on_press)
            w.bind("<ButtonRelease-1>", on_click)
            w.bind("<ButtonPress-1>", self._on_drag_start, add="+")
            w.bind("<B1-Motion>", self._on_drag_motion, add="+")

        return frame, lbl_icon, lbl_text

    def _compress_parts(self):
        """압축 상태에 따른 (아이콘, 텍스트, 색상) 튜플을 반환합니다."""
        if self._compress:
            return "📷", "저화질", "#CC6600"   # 압축ON = 저화질
        else:
            return "📷", "고화질", "#2E7D32"   # 압축OFF = 고화질

    # ──────────────────────────────────────────────
    # 창 위치
    # ──────────────────────────────────────────────

    def _position_window(self) -> None:
        """창을 화면 상단 중앙에 배치합니다."""
        self.win.update_idletasks()
        w = self.win.winfo_width()
        sw = self.win.winfo_screenwidth()
        x = (sw - w) // 2
        self.win.geometry(f"+{x}+10")

    # ──────────────────────────────────────────────
    # 드래그 이동
    # ──────────────────────────────────────────────

    def _on_drag_start(self, event) -> None:
        self._drag_start_x = event.x_root - self.win.winfo_x()
        self._drag_start_y = event.y_root - self.win.winfo_y()

    def _on_drag_motion(self, event) -> None:
        new_x = event.x_root - self._drag_start_x
        new_y = event.y_root - self._drag_start_y
        self.win.geometry(f"+{new_x}+{new_y}")

    def _update_mode_highlight(self) -> None:
        """현재 선택된 모드 버튼을 강조합니다. 비활성 버튼 hover 잔상도 즉각 해제."""
        mode = self._mode_var.get()
        mapping = {
            "direct": self._btn_direct,
            "smart": self._btn_smart,
            "fixed": self._btn_fixed,
        }
        for m, frame in mapping.items():
            active = (m == mode)
            frame._active = active
            # bg 강제 리셋 (hover 잔상 제거)
            frame.config(bg=BTN_BG)
            frame._lbl_icon.config(bg=BTN_BG, fg=ACCENT_COLOR if active else "black")
            frame._lbl_text.config(
                bg=BTN_BG,
                fg=ACCENT_COLOR if active else "#333333",
                font=("맑은 고딕", 8, "bold") if active else ("맑은 고딕", 8),
            )
            ind = frame._indicator
            if ind is not None:
                ind.config(bg=ACCENT_COLOR if active else BTN_BG)

    # ──────────────────────────────────────────────
    # 버튼 핸들러
    # ──────────────────────────────────────────────

    def _on_list_click(self) -> None:
        """캡처 목록 버튼 클릭."""
        if self._on_show_list:
            self._on_show_list()

    def _select_mode(self, mode: str) -> None:
        """이미 선택된 모드를 다시 클릭하면 캡쳐 시작, 다른 모드면 선택만."""
        if self._mode_var.get() == mode:
            self._trigger_default_capture()
        else:
            self._mode_var.set(mode)

    def _trigger_capture(self, mode: str) -> None:
        """캡처 모드를 설정하고 캡처를 트리거합니다."""
        self._mode_var.set(mode)
        if self._on_capture:
            self._on_capture(self._root, self._mode_var)

    def _trigger_default_capture(self) -> None:
        """현재 선택된 모드로 캡처를 트리거합니다."""
        if self._on_capture:
            self._on_capture(self._root, self._mode_var)

    def _on_hotkey_combo_select(self, event) -> None:
        """콤보박스에서 단축키가 선택됐을 때."""
        display = self._hotkey_combo.get()  # e.g. "F8"
        hk = display.lower()               # e.g. "f8"
        self._change_hotkey(hk)

    def _minimize_to_tray(self) -> None:
        """툴바를 숨겨 트레이로 최소화합니다."""
        self.win.withdraw()

    def _quit_app(self) -> None:
        """앱 종료."""
        self._root.quit()
        self._root.destroy()

    def _change_hotkey(self, hk: str) -> None:
        """단축키를 변경하고 config에 저장 + 콜백을 호출합니다."""
        # 기존 바인딩 해제
        try:
            old = self._hotkey
            self.win.unbind(f"<{old.upper()}>")
            self._root.unbind(f"<{old.upper()}>")
        except Exception:
            pass

        self._hotkey = hk
        self._hotkey_var.set(HOTKEY_DISPLAY.get(hk, hk.upper()))
        try:
            self._hotkey_combo.set(HOTKEY_DISPLAY.get(hk, hk.upper()))
        except Exception:
            pass

        # config 저장
        try:
            cfg = _cfg_get()
            cfg["hotkey"] = hk
            _cfg_save(cfg)
        except Exception:
            pass

        # 새 바인딩 등록
        try:
            self.win.bind(f"<{hk.upper()}>",
                          lambda e: self._trigger_default_capture())
            self._root.bind(f"<{hk.upper()}>",
                            lambda e: self._trigger_default_capture())
        except Exception:
            pass

        # 외부 콜백 (전역 단축키 재등록)
        if self._on_hotkey_changed:
            self._on_hotkey_changed(hk)

    def _toggle_compress(self) -> None:
        """압축 토글."""
        self._compress = not self._compress
        icon_text, label_text, fg_color = self._compress_parts()
        self._compress_icon_lbl.config(text=icon_text)
        self._compress_text_lbl.config(text=label_text, fg=fg_color)

        try:
            cfg = _cfg_get()
            cfg["compress"] = self._compress
            _cfg_save(cfg)
        except Exception:
            pass

    # ──────────────────────────────────────────────
    # 우클릭 컨텍스트 메뉴
    # ──────────────────────────────────────────────

    def _show_context_menu(self, event) -> None:
        """우클릭 시 컨텍스트 메뉴(종료 포함)를 표시합니다."""
        menu = tk.Menu(self.win, tearoff=0)
        menu.add_command(label="종료", command=self._root.quit)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ──────────────────────────────────────────────
    # 퍼블릭 인터페이스
    # ──────────────────────────────────────────────

    def run(self) -> None:
        """툴바 메인루프를 실행합니다."""
        self._root.mainloop()

    def get_win(self) -> tk.Toplevel:
        """툴바 창을 반환합니다."""
        return self.win
