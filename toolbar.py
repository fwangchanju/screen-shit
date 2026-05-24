"""
메인 툴바 창.
항상 최상단 고정, 타이틀바 없음, 상단 중앙 고정 (이동 불가).
기본적으로 숨겨진 상태로 시작.

레이아웃:
┌──────────────────────────────────────────────┐
│  [✂] [⬛] [⬜]   ┃   [📋] [⚙] [✕]          │
│       캡처                  옵션              │
└──────────────────────────────────────────────┘
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


try:
    from config import get as _cfg_get, save as _cfg_save
except Exception:
    _cfg_get = lambda: {}  # type: ignore
    _cfg_save = lambda c: None  # type: ignore

_AUTORUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTORUN_APP = "SmartCapture"


def _get_autorun() -> bool:
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(k, _AUTORUN_APP)
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


def _set_autorun(enable: bool) -> None:
    try:
        import winreg, sys
        from pathlib import Path
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            if getattr(sys, "frozen", False):
                cmd = sys.executable
            else:
                script = Path(__file__).parent / "main.py"
                cmd = f'"{sys.executable}" "{script}"'
            winreg.SetValueEx(k, _AUTORUN_APP, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(k, _AUTORUN_APP)
            except FileNotFoundError:
                pass
        winreg.CloseKey(k)
    except Exception as e:
        print(f"[경고] 자동실행 설정 실패: {e}")


TOOLBAR_BG    = "#F3F3F3"
BTN_BG        = "#F3F3F3"
BTN_HOVER_BG  = "#E5F0FF"
BTN_ACTIVE_BG = "#CCE4FF"
BORDER_COLOR  = "#DEDEDE"
ACCENT_COLOR  = "#0078D4"
GROUP_LABEL_FG = "#888888"

# 편집기와 동일한 색상 팔레트
_PALETTE = [
    "#FFFFFF", "#000000", "#E74C3C", "#E67E22", "#F1C40F", "#2ECC71",
    "#1ABC9C", "#3498DB", "#9B59B6", "#34495E",
    "#F8F9FA", "#343A40", "#C0392B", "#D35400", "#D4AC0D", "#1E8449",
    "#148F77", "#2471A3", "#7D3C98", "#212F3C",
    "#FADBD8", "#FAD7A0", "#FCF3CF", "#D5F5E3", "#D1F2EB", "#D6EAF8",
    "#E8DAEF", "#D5D8DC", "#F5CBA7", "#A9CCE3",
    "#F1948A", "#F0A500", "#F9E79F", "#ABEBC6", "#A2D9CE", "#AED6F1",
    "#C39BD3", "#ABB2B9", "#EB984E", "#5DADE2",
    "#EC407A", "#FF7043", "#FFCA28", "#66BB6A", "#26A69A", "#42A5F5",
    "#AB47BC", "#78909C", "#FF8A65", "#26C6DA",
    "#880E4F", "#BF360C", "#F57F17", "#1B5E20", "#004D40", "#0D47A1",
    "#4A148C", "#263238", "#E65100", "#006064",
]


def _show_palette_popup(parent: tk.Widget, anchor: tk.Widget,
                        on_color: Callable[[str], None]) -> None:
    """편집기와 동일한 색상 팔레트 팝업을 표시합니다."""
    popup = tk.Toplevel(parent)
    popup.overrideredirect(True)
    popup.attributes("-topmost", True)

    COLS, CELL, PAD = 10, 18, 4
    frame = tk.Frame(popup, bg="#2b2b2b", padx=PAD, pady=PAD)
    frame.pack()

    def close():
        try:
            popup.destroy()
        except Exception:
            pass

    popup.bind("<FocusOut>", lambda e: close())
    popup.bind("<Escape>",   lambda e: close())

    for i, color in enumerate(_PALETTE):
        r, c = divmod(i, COLS)
        btn = tk.Frame(frame, bg=color, width=CELL, height=CELL,
                       cursor="hand2", relief=tk.RAISED, bd=1)
        btn.grid(row=r, column=c, padx=1, pady=1)
        btn.bind("<Button-1>", lambda e, col=color: (on_color(col), close()))
        btn.bind("<Enter>",    lambda e, b=btn: b.config(relief=tk.SUNKEN))
        btn.bind("<Leave>",    lambda e, b=btn: b.config(relief=tk.RAISED))

    parent.update_idletasks()
    bx = anchor.winfo_rootx()
    by = anchor.winfo_rooty() + anchor.winfo_height() + 2
    # 화면 아래 벗어나면 위쪽에 표시
    sh = anchor.winfo_screenheight()
    popup.update_idletasks()
    ph = popup.winfo_reqheight()
    if by + ph > sh:
        by = anchor.winfo_rooty() - ph - 2
    popup.geometry(f"+{bx}+{by}")
    popup.focus_force()


class _Tooltip:
    """마우스 오버 시 툴팁을 표시합니다."""

    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        self._win: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None

    def bind(self, widget: tk.Widget, text_fn: Callable[[], str],
             delay: int = 600) -> None:
        """위젯에 툴팁을 바인딩합니다. text_fn은 표시할 텍스트를 반환하는 callable."""
        widget.bind("<Enter>",   lambda e: self._schedule(widget, text_fn, delay), add="+")
        widget.bind("<Leave>",   lambda e: self._cancel(), add="+")
        widget.bind("<Button-1>", lambda e: self._hide(), add="+")

    def _schedule(self, widget: tk.Widget, text_fn: Callable[[], str],
                  delay: int) -> None:
        self._cancel()
        self._after_id = self._root.after(delay,
                                          lambda: self._show(widget, text_fn()))

    def _cancel(self) -> None:
        if self._after_id:
            try:
                self._root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        self._hide()

    def _show(self, widget: tk.Widget, text: str) -> None:
        self._hide()
        if not text:
            return
        try:
            self._win = tk.Toplevel(self._root)
            self._win.overrideredirect(True)
            self._win.attributes("-topmost", True)
            tk.Label(self._win, text=text, bg="#FFFFD0", fg="#222222",
                     font=("맑은 고딕", 9), relief=tk.SOLID, bd=1,
                     padx=6, pady=3).pack()
            self._win.update_idletasks()
            x = widget.winfo_rootx()
            y = widget.winfo_rooty() + widget.winfo_height() + 4
            sw = widget.winfo_screenwidth()
            w = self._win.winfo_reqwidth()
            if x + w > sw:
                x = max(0, sw - w)
            self._win.geometry(f"+{x}+{y}")
        except Exception:
            self._win = None

    def _hide(self) -> None:
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


class Toolbar:
    def __init__(
        self,
        root: tk.Tk,
        mode_var: Optional[tk.StringVar] = None,
        on_capture: Optional[Callable] = None,
        on_show_list: Optional[Callable[[], None]] = None,
        on_hotkey_changed: Optional[Callable[[str], None]] = None,
        on_mode_hotkeys_changed: Optional[Callable[[], None]] = None,
    ) -> None:
        self._root = root
        self._mode_var = mode_var if mode_var is not None else tk.StringVar(value="")
        self._on_capture = on_capture
        self._on_show_list = on_show_list
        self._on_hotkey_changed = on_hotkey_changed
        self._on_mode_hotkeys_changed = on_mode_hotkeys_changed

        cfg = _cfg_get()
        self._hotkey: str = cfg.get("hotkey", "")
        self._settings_win: Optional[tk.Toplevel] = None

        self._tooltip = _Tooltip(root)

        # 18회차 item 6: image/툴바.png 아이콘 로드
        self._icon_photos: list = []  # GC 방지용 참조 저장
        self._icon_images: list = self._load_toolbar_icons()

        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TOOLBAR_BG)

        self._build()
        self._position_window()

        # 18회차: 기본 표시 (visible by default)

    # ──────────────────────────────────────────────
    # 아이콘 로드 (image/툴바.png)
    # ──────────────────────────────────────────────

    def _load_toolbar_icons(self) -> list:
        """개별 아이콘 파일(툴팁명.png)을 로드합니다.
        파일이 없으면 해당 슬롯을 None으로 채우며, 텍스트 폴백이 사용됩니다."""
        try:
            import sys
            from pathlib import Path
            from PIL import Image
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                base = Path(sys._MEIPASS)
            else:
                base = Path(__file__).parent
            img_dir = base / "image" / "toolbar"
            names = ["간편캡처", "단위영역", "크기고정", "캡처목록", "설정", "닫기"]
            # 레이블이 좌측으로 이동해 하단 텍스트가 사라진 만큼 아이콘 크기 확대
            # 16px(아이콘) + 제거된 텍스트 행(~12px) = 28px 정사각형
            ICON_SIZE = (28, 28)
            icons = []
            for name in names:
                path = img_dir / f"{name}.png"
                if path.exists():
                    try:
                        img = Image.open(path).convert("RGBA")
                        img = img.resize(ICON_SIZE, Image.LANCZOS)
                        icons.append(img)
                    except Exception:
                        icons.append(None)
                else:
                    icons.append(None)
            return icons
        except Exception:
            return []

    # ──────────────────────────────────────────────
    # 창 구성
    # ──────────────────────────────────────────────

    def _build(self) -> None:
        outer = tk.Frame(self.win, bg=BORDER_COLOR, bd=1, relief=tk.RIDGE)
        outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        body = tk.Frame(outer, bg=TOOLBAR_BG, padx=4, pady=4)
        body.pack(fill=tk.BOTH, expand=True)

        def _get_img(idx: int):
            imgs = self._icon_images
            if imgs and idx < len(imgs) and imgs[idx] is not None:
                from PIL import ImageTk
                ph = ImageTk.PhotoImage(imgs[idx])
                self._icon_photos.append(ph)  # GC 방지
                return ph
            return None

        # ── 캡처 그룹: 레이블 좌측 + 버튼들 ──
        cap_grp = tk.Frame(body, bg=TOOLBAR_BG)
        cap_grp.pack(side=tk.LEFT)


        self._btn_direct = self._make_icon_button(
            cap_grp, "✂", lambda: self._select_mode("direct"),
            tooltip_fn=lambda: self._tip_text("direct", "간편캡처"),
            img=_get_img(0),
        )
        self._btn_smart = self._make_icon_button(
            cap_grp, "⬛", lambda: self._select_mode("smart"),
            tooltip_fn=lambda: self._tip_text("smart", "단위영역"),
            img=_get_img(1),
        )
        self._btn_fixed = self._make_icon_button(
            cap_grp, "⬜", lambda: self._select_mode("fixed"),
            tooltip_fn=lambda: self._tip_text("fixed", "크기고정"),
            img=_get_img(2),
        )

        self._mode_var.trace_add("write", lambda *_: self._update_mode_highlight())
        self._update_mode_highlight()

        # ── 구분선 ──
        tk.Frame(body, width=2, bg="#AAAAAA").pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=2)

        # ── 옵션 그룹: 레이블 좌측 + 버튼들 ──
        opt_grp = tk.Frame(body, bg=TOOLBAR_BG)
        opt_grp.pack(side=tk.LEFT)


        self._btn_list = self._make_icon_button(
            opt_grp, "📋", self._on_list_click,
            tooltip_fn=lambda: "캡처목록",
            img=_get_img(3),
        )
        self._make_icon_button(
            opt_grp, "⚙", self._open_settings,
            tooltip_fn=lambda: "설정",
            img=_get_img(4),
        )
        self._make_icon_button(
            opt_grp, "✕", self._close_toolbar,
            tooltip_fn=lambda: "닫기",
            img=_get_img(5),
        )

    def _make_icon_button(self, parent: tk.Widget, icon: str,
                          command: Callable,
                          tooltip_fn: Optional[Callable[[], str]] = None,
                          img=None) -> tk.Frame:
        # 20회차 item 1: 툴바 절반 크기 — 버튼 패딩 대폭 축소
        frame = tk.Frame(parent, bg=BTN_BG, padx=3, pady=0, cursor="hand2")
        frame.pack(side=tk.LEFT, padx=1)

        # 18회차 item 6: 이미지 아이콘 우선, 없으면 텍스트 폴백
        if img is not None:
            lbl_icon = tk.Label(frame, image=img, bg=BTN_BG)
        else:
            # 20회차 item 1: 폰트 크기 15 → 10
            lbl_icon = tk.Label(frame, text=icon, bg=BTN_BG, font=("맑은 고딕", 10))
        lbl_icon.pack(pady=(1, 1))

        frame._lbl_icon = lbl_icon

        all_w = [frame, lbl_icon]

        def _set_bg(bg: str) -> None:
            for w in all_w:
                w.config(bg=bg)

        def on_enter(e):
            if not getattr(frame, '_active', False):
                _set_bg(BTN_HOVER_BG)

        def on_leave(e):
            if not getattr(frame, '_active', False):
                _set_bg(BTN_BG)

        def on_press(e):
            _set_bg(BTN_ACTIVE_BG)

        def on_release(e):
            command()

        for w in all_w:
            w.bind("<Enter>",          on_enter)
            w.bind("<Leave>",          on_leave)
            w.bind("<Button-1>",       on_press)
            w.bind("<ButtonRelease-1>", lambda e, fn=on_release: fn(e))

        if tooltip_fn:
            self._tooltip.bind(frame,    tooltip_fn)
            self._tooltip.bind(lbl_icon, tooltip_fn)

        frame._active = False
        return frame

    # ──────────────────────────────────────────────
    # 창 위치 (상단 중앙)
    # ──────────────────────────────────────────────

    def _position_window(self) -> None:
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth() or 300
        try:
            import ctypes, ctypes.wintypes
            wa = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(wa), 0)
            screen_w = wa.right - wa.left
            x = wa.left + (screen_w - w) // 2
            y = wa.top + 4
        except Exception:
            sw = self.win.winfo_screenwidth()
            x = (sw - w) // 2
            y = 4
        self.win.geometry(f"+{x}+{y}")

    # ──────────────────────────────────────────────
    # 모드 하이라이트 (active = blue tint bg + blue icon)
    # ──────────────────────────────────────────────

    def _update_mode_highlight(self) -> None:
        mode = self._mode_var.get()
        mapping = {
            "direct": self._btn_direct,
            "smart":  self._btn_smart,
            "fixed":  self._btn_fixed,
        }
        for m, frame in mapping.items():
            active = bool(mode) and (m == mode)
            frame._active = active
            bg = BTN_ACTIVE_BG if active else BTN_BG
            frame.config(bg=bg)
            frame._lbl_icon.config(
                bg=bg,
                fg=ACCENT_COLOR if active else "black",
            )

    # ──────────────────────────────────────────────
    # 툴팁 텍스트
    # ──────────────────────────────────────────────

    def _tip_text(self, mode_key: str, label: str) -> str:
        try:
            cfg = _cfg_get()
            hk = cfg.get("mode_hotkeys", {}).get(mode_key, "") or ""
            if hk and hk != "없음":
                return f"{label}\n{self._hk_display(hk)}"
        except Exception:
            pass
        # 19회차 item 6: "지정된 단축키 없음" → "단축키 없음"으로 단축
        return f"{label}\n단축키 없음"

    # ──────────────────────────────────────────────
    # 버튼 핸들러
    # ──────────────────────────────────────────────

    def _on_list_click(self) -> None:
        if self._on_show_list:
            self._on_show_list()

    def _select_mode(self, mode: str) -> None:
        self._mode_var.set(mode)
        self._trigger_default_capture()

    def _trigger_default_capture(self) -> None:
        if self._on_capture:
            self._on_capture(self._root, self._mode_var)

    def _close_toolbar(self) -> None:
        self.win.withdraw()

    # ──────────────────────────────────────────────
    # 설정 창
    # ──────────────────────────────────────────────

    def _open_settings(self) -> None:
        if self._settings_win is not None:
            try:
                if self._settings_win.winfo_exists():
                    self._settings_win.lift()
                    self._settings_win.focus_force()
                    return
            except Exception:
                pass

        win = tk.Toplevel(self._root)
        win.title("환경설정")
        win.resizable(False, False)
        self._settings_win = win

        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        W, H = 580, 500
        win.geometry(f"{W}x{H}+{(sw - W) // 2}+{(sh - H) // 2}")
        win.focus_force()

        cfg = _cfg_get()

        # ── 레이아웃 ──
        main_frame = tk.Frame(win)
        main_frame.pack(fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(main_frame, width=120, bg="#E8E8E8", relief=tk.GROOVE, bd=1)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        content_host = tk.Frame(main_frame)
        content_host.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        frames: dict = {}

        def show_category(name: str) -> None:
            for f in frames.values():
                f.pack_forget()
            frames[name].pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
            for btn_name, btn in cat_btns.items():
                btn.config(
                    bg=ACCENT_COLOR if btn_name == name else "#E8E8E8",
                    fg="white" if btn_name == name else "#333333",
                )

        cat_btns: dict = {}
        # 카테고리명 변경 (17회차): 도구기본값→편집기, 저장설정→프로그램
        categories = [("단축키", "단축키"), ("편집기", "편집기"), ("프로그램", "프로그램")]

        for label, key in categories:
            btn = tk.Button(
                sidebar, text=label, font=("맑은 고딕", 10),
                relief=tk.FLAT, bg="#E8E8E8", fg="#333333",
                anchor=tk.W, padx=8, pady=6,
                command=lambda k=key: show_category(k),
            )
            btn.pack(fill=tk.X, pady=1)
            cat_btns[key] = btn
            frames[key] = tk.Frame(content_host)

        # ═══════════════════════════════════════════
        # 카테고리 1: 단축키
        # ═══════════════════════════════════════════
        f_hotkey = frames["단축키"]

        tk.Label(f_hotkey, text="단축키 설정", font=("맑은 고딕", 11, "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, 8))

        def _make_hk_row(parent, label_text: str, store: list) -> None:
            """인라인 단축키 입력 행 (17회차: 팝업 없이)."""
            row = tk.Frame(parent)
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=label_text, font=("맑은 고딕", 10),
                     width=16, anchor=tk.W).pack(side=tk.LEFT)
            disp = tk.Label(row, text=self._hk_display(store[0]),
                            font=("맑은 고딕", 10, "bold"), fg=ACCENT_COLOR,
                            width=12, anchor=tk.W)
            disp.pack(side=tk.LEFT, padx=4)

            btn_set = tk.Button(row, text="설정", font=("맑은 고딕", 9))
            btn_set.pack(side=tk.LEFT)
            _waiting = [False]

            def _start():
                if _waiting[0]:
                    return
                _waiting[0] = True
                disp.config(text="▌ 입력 대기...", fg="#E87C00")
                btn_set.config(state=tk.DISABLED)
                win.focus_force()

                def _on_key(event):
                    mods = []
                    if event.state & 0x4:      mods.append("ctrl")
                    if event.state & 0x20000:  mods.append("alt")
                    if event.state & 0x1:      mods.append("shift")
                    sym = event.keysym.lower()
                    if sym == "escape":
                        store[0] = "없음"
                        disp.config(text="없음", fg=ACCENT_COLOR)
                        btn_set.config(state=tk.NORMAL)
                        _waiting[0] = False
                        win.unbind("<KeyPress>")
                        return "break"
                    if sym in ("control_l", "control_r", "alt_l", "alt_r",
                               "shift_l", "shift_r", "meta_l", "meta_r"):
                        return
                    hk = "+".join(mods + [sym])
                    store[0] = hk
                    disp.config(text=self._hk_display(hk), fg=ACCENT_COLOR)
                    btn_set.config(state=tk.NORMAL)
                    _waiting[0] = False
                    win.unbind("<KeyPress>")
                    return "break"

                win.bind("<KeyPress>", _on_key)

            btn_set.config(command=_start)

        ttk.Separator(f_hotkey, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 4))
        tk.Label(f_hotkey, text="모드별 단축키", font=("맑은 고딕", 10, "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, 4))

        mode_hotkeys_cfg: dict = cfg.get("mode_hotkeys", {})
        MODE_ROWS = [
            ("direct", "간편캡처:"),
            ("smart",  "단위영역:"),
            ("fixed",  "크기고정:"),
        ]
        mode_hk_stores: dict = {}
        for mode_key, mode_label in MODE_ROWS:
            saved_hk = mode_hotkeys_cfg.get(mode_key, "없음")
            store = [saved_hk if saved_hk else "없음"]
            mode_hk_stores[mode_key] = store
            _make_hk_row(f_hotkey, mode_label, store)

        # 17회차: "바 보이기/숨기기" → "툴바 보이기/숨기기"
        ttk.Separator(f_hotkey, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(8, 4))
        saved_tt_hk = cfg.get("toolbar_toggle_hotkey", "") or "없음"
        toolbar_toggle_store = [saved_tt_hk]
        _make_hk_row(f_hotkey, "툴바 보이기/숨기기:", toolbar_toggle_store)

        # ── 단축키 초기화 (17회차: 되돌리기→취소, 기능 수정) ──
        ttk.Separator(f_hotkey, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 4))
        reset_row = tk.Frame(f_hotkey)
        reset_row.pack(fill=tk.X, pady=4)

        def _save_hotkeys_and_notify():
            c = _cfg_get()
            mhk = {mk: (s[0] if s[0] != "없음" else "없음")
                   for mk, s in mode_hk_stores.items()}
            c["mode_hotkeys"] = mhk
            c["toolbar_toggle_hotkey"] = (
                toolbar_toggle_store[0] if toolbar_toggle_store[0] != "없음" else "")
            _cfg_save(c)
            if self._on_mode_hotkeys_changed:
                self._on_mode_hotkeys_changed()

        def _do_reset():
            # 전부 "없음"으로
            for s in mode_hk_stores.values():
                s[0] = "없음"
            toolbar_toggle_store[0] = "없음"
            # 즉시 저장 + 핫키 해제
            _save_hotkeys_and_notify()
            # 창 닫고 재오픈하여 라벨 갱신
            win.destroy()
            self._settings_win = None
            self._root.after(80, self._open_settings)

        # 18회차 item 1: "취소" 버튼 제거 — "단축키 초기화" 버튼만 유지
        btn_reset = tk.Button(
            reset_row, text="단축키 초기화",
            font=("맑은 고딕", 9), bg="#CC4444", fg="white",
            relief=tk.FLAT, padx=8, command=_do_reset,
        )
        btn_reset.pack(side=tk.LEFT, padx=(0, 8))

        # ═══════════════════════════════════════════
        # 카테고리 2: 편집기 (구 도구기본값)
        # ═══════════════════════════════════════════
        f_tools = frames["편집기"]

        tk.Label(f_tools, text="편집기 기본값", font=("맑은 고딕", 11, "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, 8))

        sizes_cfg   = cfg.get("tool_sizes", {})
        colors_cfg  = cfg.get("tool_colors", {})

        TOOL_ROWS = [
            ("pen",         "펜",       3,  "#E74C3C"),
            ("highlighter", "형광펜",   12, "#FFFF00"),
            ("shape",       "도형",     2,  "#E74C3C"),
            ("eraser",      "지우개",   10, None),
            ("mosaic",      "모자이크", 2,  None),
        ]

        size_vars:  dict = {}
        color_vars: dict = {}

        for key, label, default_sz, default_col in TOOL_ROWS:
            row = tk.Frame(f_tools)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label + ":", font=("맑은 고딕", 10),
                     width=8, anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(row, text="크기", font=("맑은 고딕", 9)).pack(side=tk.LEFT, padx=(4, 2))
            sz_var = tk.IntVar(value=sizes_cfg.get(key, default_sz))
            size_vars[key] = sz_var
            tk.Spinbox(row, from_=1, to=50, textvariable=sz_var, width=4,
                       font=("맑은 고딕", 9)).pack(side=tk.LEFT)

            if default_col is not None:
                col_val = colors_cfg.get(key, default_col)
                color_vars[key] = [col_val]
                tk.Label(row, text="색상", font=("맑은 고딕", 9)).pack(
                    side=tk.LEFT, padx=(8, 2))

                cf = tk.Frame(row, bg=col_val, width=18, height=18,
                              relief=tk.GROOVE, bd=1)
                cf.pack(side=tk.LEFT, padx=(0, 2))
                cf.pack_propagate(False)

                # 17회차: 팔레트 팝업으로 변경 (편집기 + 버튼과 동일)
                btn_color = tk.Button(row, text="변경", font=("맑은 고딕", 8))

                def _make_picker(k=key, frame_w=cf, cv=color_vars[key],
                                 btn=btn_color):
                    def pick():
                        def on_color(c):
                            cv[0] = c
                            frame_w.config(bg=c)
                        _show_palette_popup(win, btn, on_color)
                    return pick

                btn_color.config(command=_make_picker())
                btn_color.pack(side=tk.LEFT)

        # ═══════════════════════════════════════════
        # 카테고리 3: 프로그램 (구 저장설정)
        # ═══════════════════════════════════════════
        f_save = frames["프로그램"]

        tk.Label(f_save, text="프로그램 설정", font=("맑은 고딕", 11, "bold"),
                 anchor=tk.W).pack(fill=tk.X, pady=(0, 8))

        autorun_var = tk.BooleanVar(value=_get_autorun())
        tk.Checkbutton(
            f_save, text="Windows 시작 시 자동 실행",
            variable=autorun_var, font=("맑은 고딕", 10),
        ).pack(anchor=tk.W, pady=(0, 8))
        # 17회차: 괄호 제거, 문장으로 변경
        tk.Label(f_save,
                 text="설정 파일은 실행 파일 위치에 자동 저장됩니다.",
                 font=("맑은 고딕", 9), fg="#888888").pack(anchor=tk.W, padx=4)

        # ── 하단 확인 버튼 ──
        btn_row = tk.Frame(win)
        btn_row.pack(side=tk.BOTTOM, fill=tk.X, padx=12, pady=8)

        def apply():
            c = _cfg_get()
            c.setdefault("tool_sizes", {}).update(
                {k: v.get() for k, v in size_vars.items()})
            c.setdefault("tool_colors", {}).update(
                {k: v[0] for k, v in color_vars.items()})
            mhk = {mk: (s[0] if s[0] != "없음" else "없음")
                   for mk, s in mode_hk_stores.items()}
            c["mode_hotkeys"] = mhk
            c["toolbar_toggle_hotkey"] = (
                toolbar_toggle_store[0] if toolbar_toggle_store[0] != "없음" else "")
            _cfg_save(c)
            _set_autorun(autorun_var.get())
            if self._on_mode_hotkeys_changed:
                self._on_mode_hotkeys_changed()
            win.destroy()
            self._settings_win = None

        tk.Button(
            btn_row, text="확인", command=apply,
            font=("맑은 고딕", 10), width=10,
            bg=ACCENT_COLOR, fg="white", relief=tk.FLAT,
        ).pack(side=tk.RIGHT)

        def on_close():
            self._settings_win = None
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        win.bind("<Escape>", lambda e: on_close())
        show_category("단축키")

    # ──────────────────────────────────────────────
    # 정적 유틸
    # ──────────────────────────────────────────────

    @staticmethod
    def _hk_display(hk: str) -> str:
        if not hk or hk == "없음":
            return "없음"
        parts = hk.lower().split("+")
        result = []
        for p in parts:
            if p == "ctrl":    result.append("Ctrl")
            elif p == "alt":   result.append("Alt")
            elif p == "shift": result.append("Shift")
            elif p.startswith("f") and p[1:].isdigit():
                result.append(p.upper())
            else:
                result.append(p.upper())
        return "+".join(result)

    @staticmethod
    def _hk_to_tkbind(hk: str) -> str:
        if not hk or hk == "없음":
            return ""
        parts = hk.lower().split("+")
        key = parts[-1]
        mods = parts[:-1]
        tk_mods = []
        for m in mods:
            if m == "ctrl":    tk_mods.append("Control")
            elif m == "alt":   tk_mods.append("Alt")
            elif m == "shift": tk_mods.append("Shift")
        if key.startswith("f") and key[1:].isdigit():
            key_tk = key.upper()
        else:
            key_tk = key
        return "<" + "-".join(tk_mods + [key_tk]) + ">"

    def _change_hotkey(self, hk: str) -> None:
        self._hotkey = hk
        if self._on_hotkey_changed:
            self._on_hotkey_changed(hk)

    # ──────────────────────────────────────────────
    # 퍼블릭 인터페이스
    # ──────────────────────────────────────────────

    def run(self) -> None:
        self._root.mainloop()

    def get_win(self) -> tk.Toplevel:
        return self.win
