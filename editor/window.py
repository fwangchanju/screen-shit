"""
결과창 (편집기) 메인 클래스.

레이아웃:
┌────────────────────────────────────────────────┬──────┐
│  상단 툴바                                      │      │
├────────────────────────────────────────────────┤  우  │
│                                                │  측  │
│              메인 캔버스                        │  패  │
│           (스크롤 가능)                         │  널  │
│                                                │      │
├────────────────────────────────────────────────┤      │
│  하단 상태바: 이미지 크기 / 줌 / 확대축소       │      │
└────────────────────────────────────────────────┴──────┘

외부에서 사용하는 진입점:
    open_editor(image, master=root, history_idx=idx)
"""
from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from io import BytesIO
from typing import Any, List, Optional

from PIL import Image, ImageTk

# ──────────────────────────────────────────────────────────────
# 선택적 임포트
# ──────────────────────────────────────────────────────────────

try:
    from editor.tools import Operation, render_all, find_op_at
except ImportError:
    try:
        from tools import Operation, render_all, find_op_at  # type: ignore
    except ImportError:
        raise

try:
    from editor.history_panel import HistoryPanel
except ImportError:
    from history_panel import HistoryPanel  # type: ignore

# ──────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────

ACTIVE_BG = "#D0E8FF"
NORMAL_BG = "SystemButtonFace"
SHAPE_TOOLS = ["rect", "ellipse", "arrow", "line"]
SHAPE_LABELS = {"rect": "사각형", "ellipse": "원", "arrow": "화살표", "line": "직선"}
ZOOM_STEPS = [0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


# ──────────────────────────────────────────────────────────────
# 클립보드 유틸
# ──────────────────────────────────────────────────────────────

def copy_to_clipboard(image: Image.Image) -> bool:
    """PIL Image를 Windows 클립보드에 BMP 형식으로 복사합니다."""
    try:
        import win32clipboard
        output = BytesIO()
        image.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]
        output.close()
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        win32clipboard.CloseClipboard()
        return True
    except Exception as e:
        print(f"클립보드 복사 실패: {e}")
        return False


# ──────────────────────────────────────────────────────────────
# HistoryAdapter: CaptureHistory 또는 list를 통일된 인터페이스로 감쌈
# ──────────────────────────────────────────────────────────────

class _HistoryAdapter:
    """CaptureHistory 객체 또는 PIL.Image 리스트를 통일된 list-like로 감쌉니다."""

    def __init__(self, source: Any) -> None:
        self._src = source

    def __len__(self) -> int:
        if hasattr(self._src, "count"):
            return self._src.count()
        return len(self._src)

    def __getitem__(self, idx: int) -> Image.Image:
        if hasattr(self._src, "get"):
            return self._src.get(idx)
        item = self._src[idx]
        if isinstance(item, Image.Image):
            return item
        if hasattr(item, "image"):
            return item.image
        if hasattr(item, "get_image"):
            return item.get_image()
        raise TypeError(f"알 수 없는 history 항목 타입: {type(item)}")

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]


# ──────────────────────────────────────────────────────────────
# EditorWindow
# ──────────────────────────────────────────────────────────────

class EditorWindow:
    """결과창 메인 클래스.

    Parameters
    ----------
    history : CaptureHistory | list
        캡처 이미지 저장소 (CaptureHistory 객체 또는 PIL.Image 리스트).
    initial_idx : int
        처음 표시할 이미지의 인덱스.
    master : tk.Widget, optional
        부모 tkinter 위젯. None이면 새 Tk 루트를 생성합니다.
    """

    def __init__(self, history: Any, initial_idx: int,
                 master: Optional[tk.Widget] = None) -> None:
        self._history = _HistoryAdapter(history)
        self._current_idx: int = initial_idx

        # 편집 상태
        self._base_image: Optional[Image.Image] = None
        self._ops: List[Operation] = []
        self._redo_stack: List[Operation] = []
        self._tag_counter: int = 0

        # config 로드 (도구별 굵기 + 마지막 색상)
        try:
            from config import get as cfg_get
            cfg = cfg_get()
        except Exception:
            cfg = {}
        defaults = {"pen": 3, "highlighter": 12, "shape": 2,
                    "eraser": 10, "crop": 2, "mosaic": 2}
        defaults.update(cfg.get("tool_sizes", {}))
        self._tool_sizes: dict = defaults

        # 도구 상태
        self._tool: str = "pen"
        self._sub_tool: str = "rect"
        self._color: str = cfg.get("last_color", "#E74C3C")

        # 색상 선택 팝업 참조 (중복 방지)
        self._color_popup: Optional[tk.Toplevel] = None

        # 드로잉 상태
        self._drawing: bool = False
        self._start: tuple = (0, 0)
        self._pen_points: list = []
        self._preview_item = None
        self._pen_preview_items: list = []  # 펜/형광펜 실시간 획 누적용

        # 텍스트 인라인 편집 상태
        self._text_widget: Optional[tk.Text] = None
        self._text_window = None
        self._text_rect: Optional[tuple] = None

        # 줌
        self._zoom: float = 1.0
        self._zoom_idx: int = ZOOM_STEPS.index(1.0)

        # 창 구성
        if master is not None:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()

        self.root.title("스마트 캡쳐 - 편집기")
        self.root.resizable(True, True)

        self._build_ui()
        self.load_image(initial_idx)

    # ──────────────────────────────────────────────
    # 창 구성
    # ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        """전체 UI를 구성합니다."""
        self._build_toolbar()

        # 중앙 + 우측 컨테이너
        content = tk.Frame(self.root)
        content.pack(fill=tk.BOTH, expand=True)

        # 캔버스 영역 (좌측)
        canvas_area = tk.Frame(content)
        canvas_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_canvas(canvas_area)
        self._build_statusbar(canvas_area)

        # 우측 히스토리 패널
        # HistoryPanel은 list-like를 기대하므로 adapter를 전달
        self._history_panel = HistoryPanel(
            parent_frame=content,
            history=self._history,
            on_select_callback=self._on_history_select,
        )

        self._bind_keys()

    def _build_toolbar(self) -> None:
        """상단 툴바를 구성합니다."""
        bar = tk.Frame(self.root, bd=1, relief=tk.GROOVE)
        bar.pack(side=tk.TOP, fill=tk.X)

        def sep():
            ttk.Separator(bar, orient=tk.VERTICAL).pack(
                side=tk.LEFT, fill=tk.Y, padx=6, pady=2
            )

        # ── 히스토리 그룹 ──
        self._tb_btn(bar, "↩ 취소", self._undo)
        self._tb_btn(bar, "↪ 복원", self._redo)
        self._tb_btn(bar, "🔄 초기화", self._reset)
        sep()

        # ── 도구 그룹 ──
        self._tool_btns: dict = {}

        def mk_tool(icon: str, tool: str) -> tk.Button:
            btn = self._tb_btn(bar, icon, lambda t=tool: self._set_tool(t))
            self._tool_btns[tool] = btn
            return btn

        mk_tool("✏ 펜", "pen")
        mk_tool("🖊 형광펜", "highlighter")

        # 도형: 메인 버튼(현재 도형 즉시 선택) + ▼ 드롭다운
        shape_frame = tk.Frame(bar)
        shape_frame.pack(side=tk.LEFT, padx=1, pady=2)
        self._shape_main_btn = tk.Button(
            shape_frame, text=self._shape_label(), relief=tk.FLAT,
            font=("맑은 고딕", 9),
            command=lambda: self._select_shape(self._sub_tool),
        )
        self._shape_main_btn.pack(side=tk.LEFT)
        self._tool_btns["shape"] = self._shape_main_btn
        shape_dd_btn = tk.Button(
            shape_frame, text="▼", relief=tk.FLAT,
            font=("맑은 고딕", 7), width=2,
            command=self._show_shape_menu,
        )
        shape_dd_btn.pack(side=tk.LEFT)
        self._shape_dd_btn = shape_dd_btn

        mk_tool("T 텍스트", "text")
        mk_tool("🧹 지우개", "eraser")
        sep()

        # ── 편집 그룹 ──
        mk_tool("✂ 자르기", "crop")
        mk_tool("⬛ 모자이크", "mosaic")
        sep()

        # ── 색상 ──
        tk.Label(bar, text="색상", font=("맑은 고딕", 9)).pack(side=tk.LEFT, padx=(4, 1))
        # 현재 색상 표시 박스 (작은 사각형)
        self._color_display = tk.Frame(
            bar, bg=self._color, width=14, height=14,
            relief=tk.GROOVE, bd=1,
        )
        self._color_display.pack(side=tk.LEFT, pady=4)
        self._color_display.pack_propagate(False)
        # ▼ 버튼: 팔레트 팝업 열기
        self._color_btn = tk.Button(
            bar, text="▼", font=("맑은 고딕", 7), width=2,
            relief=tk.FLAT, command=self._pick_color,
        )
        self._color_btn.pack(side=tk.LEFT, padx=(0, 2), pady=4)

        # ── 굵기 슬라이더 + 숫자 입력 ──
        tk.Label(bar, text="굵기", font=("맑은 고딕", 9)).pack(side=tk.LEFT)
        self._width_var = tk.IntVar(value=self._tool_sizes.get("pen", 3))
        self._width_slider = tk.Scale(
            bar, from_=1, to=30, orient=tk.HORIZONTAL,
            variable=self._width_var, length=70,
            command=self._on_slider_change, showvalue=False,
        )
        self._width_slider.pack(side=tk.LEFT, padx=2)
        self._width_entry = tk.Entry(
            bar, textvariable=self._width_var, width=3,
            font=("맑은 고딕", 9), justify=tk.CENTER,
        )
        self._width_entry.pack(side=tk.LEFT, padx=(0, 2))
        self._width_entry.bind("<Return>", self._on_entry_width)
        self._width_entry.bind("<FocusOut>", self._on_entry_width)
        sep()

        # ── 저장 / 복사 ──
        self._tb_btn(bar, "💾 저장", self._save)
        self._tb_btn(bar, "📋 복사", self._copy)

        # 초기 도구 강조
        self._highlight_tool("pen")

    def _tb_btn(self, parent: tk.Widget, text: str, command) -> tk.Button:
        """툴바 버튼을 만들고 반환합니다."""
        btn = tk.Button(
            parent, text=text, relief=tk.FLAT,
            font=("맑은 고딕", 9),
            command=command,
        )
        btn.pack(side=tk.LEFT, padx=1, pady=2)
        return btn

    def _build_canvas(self, parent: tk.Widget) -> None:
        """스크롤 가능한 메인 캔버스를 구성합니다."""
        frame = tk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)

        h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            frame, cursor="crosshair",
            xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set,
            highlightthickness=0, bg="#C8C8C8",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        self._bg_item = self.canvas.create_image(0, 0, anchor=tk.NW)
        self._bg_tk: Optional[ImageTk.PhotoImage] = None

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<MouseWheel>", self._on_canvas_scroll)

    def _build_statusbar(self, parent: tk.Widget) -> None:
        """하단 상태바를 구성합니다."""
        bar = tk.Frame(parent, bd=1, relief=tk.SUNKEN)
        bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._status_size = tk.Label(
            bar, text="크기: -", font=("맑은 고딕", 9), anchor=tk.W
        )
        self._status_size.pack(side=tk.LEFT, padx=8)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, pady=2)

        self._status_zoom = tk.Label(
            bar, text="100%", font=("맑은 고딕", 9)
        )
        self._status_zoom.pack(side=tk.LEFT, padx=8)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, pady=2)

        tk.Button(bar, text="+", font=("맑은 고딕", 9),
                  relief=tk.FLAT, command=self._zoom_in,
                  width=2).pack(side=tk.LEFT, padx=2)
        tk.Button(bar, text="-", font=("맑은 고딕", 9),
                  relief=tk.FLAT, command=self._zoom_out,
                  width=2).pack(side=tk.LEFT, padx=2)
        tk.Button(bar, text="1:1", font=("맑은 고딕", 9),
                  relief=tk.FLAT, command=self._zoom_reset,
                  width=3).pack(side=tk.LEFT, padx=2)

    def _bind_keys(self) -> None:
        """키보드 단축키를 등록합니다."""
        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Control-y>", lambda e: self._redo())
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Control-c>", lambda e: self._copy())

    # ──────────────────────────────────────────────
    # 이미지 로드 / 렌더링
    # ──────────────────────────────────────────────

    def load_image(self, idx: int) -> None:
        """history[idx] 이미지를 캔버스에 로드합니다. 편집 내용이 초기화됩니다."""
        self._current_idx = idx
        img = self._history[idx]
        self._base_image = img.convert("RGBA")
        self._ops = []
        self._redo_stack = []

        # 줌 초기화
        self._zoom = 1.0
        self._zoom_idx = ZOOM_STEPS.index(1.0)

        # 히스토리 패널 선택 갱신
        if hasattr(self, "_history_panel"):
            self._history_panel.set_selected(idx)

        self._refresh_canvas()
        self._update_status()

    def _get_rendered(self) -> Image.Image:
        """base_image + ops를 렌더링한 PIL Image(RGB)를 반환합니다."""
        if self._base_image is None:
            return Image.new("RGB", (1, 1))
        result = render_all(self._base_image, self._ops)
        return result.convert("RGB")

    def _refresh_canvas(self) -> None:
        """캔버스에 현재 이미지를 표시합니다 (줌 적용)."""
        if self._base_image is None:
            return
        rendered = self._get_rendered()
        iw, ih = rendered.size
        new_w = max(1, int(iw * self._zoom))
        new_h = max(1, int(ih * self._zoom))
        if new_w != iw or new_h != ih:
            display = rendered.resize((new_w, new_h), Image.LANCZOS)
        else:
            display = rendered
        self._bg_tk = ImageTk.PhotoImage(display)
        self.canvas.itemconfig(self._bg_item, image=self._bg_tk)
        self.canvas.config(scrollregion=(0, 0, new_w, new_h))

    def _update_status(self) -> None:
        """하단 상태바를 갱신합니다."""
        if self._base_image:
            iw, ih = self._base_image.size
            self._status_size.config(text=f"크기: {iw} × {ih}")
        zoom_pct = int(self._zoom * 100)
        self._status_zoom.config(text=f"{zoom_pct}%")

    # ──────────────────────────────────────────────
    # 줌
    # ──────────────────────────────────────────────

    def _zoom_in(self) -> None:
        if self._zoom_idx < len(ZOOM_STEPS) - 1:
            self._zoom_idx += 1
            self._zoom = ZOOM_STEPS[self._zoom_idx]
            self._refresh_canvas()
            self._update_status()

    def _zoom_out(self) -> None:
        if self._zoom_idx > 0:
            self._zoom_idx -= 1
            self._zoom = ZOOM_STEPS[self._zoom_idx]
            self._refresh_canvas()
            self._update_status()

    def _zoom_reset(self) -> None:
        self._zoom = 1.0
        self._zoom_idx = ZOOM_STEPS.index(1.0)
        self._refresh_canvas()
        self._update_status()

    def _on_canvas_scroll(self, event) -> None:
        """Ctrl+휠로 줌 조절, 그 외에는 세로 스크롤."""
        if event.state & 0x4:  # Ctrl 키
            if event.delta > 0:
                self._zoom_in()
            else:
                self._zoom_out()
        else:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ──────────────────────────────────────────────
    # 도구 관련
    # ──────────────────────────────────────────────

    def _set_tool(self, tool: str) -> None:
        """도구를 전환합니다. 이전 도구의 굵기를 저장하고 새 도구의 굵기를 복원합니다."""
        # 텍스트 입력 중이면 먼저 확정
        if self._text_widget is not None:
            self._finish_text_input()

        # 현재 도구 굵기 저장 (모든 도구)
        save_key = self._tool if self._tool != "shape" else "shape"
        self._tool_sizes[save_key] = self._width_var.get()
        try:
            from config import get as cfg_get, save as cfg_save
            cfg = cfg_get()
            cfg.setdefault("tool_sizes", {})[save_key] = self._tool_sizes[save_key]
            cfg_save(cfg)
        except Exception:
            pass

        self._tool = tool
        self._highlight_tool(tool)

        # 새 도구 굵기 복원 (모든 도구 슬라이더 활성)
        restore_key = tool if tool != "shape" else "shape"
        new_width = self._tool_sizes.get(restore_key, 3)
        self._width_var.set(new_width)
        self._width_slider.config(state=tk.NORMAL)

    def _shape_label(self) -> str:
        icons = {"rect": "▭ 사각형", "ellipse": "○ 원",
                 "arrow": "→ 화살표", "line": "— 직선"}
        return icons.get(self._sub_tool, "▭ 사각형")

    def _highlight_tool(self, tool: str) -> None:
        """현재 선택된 도구 버튼을 강조합니다."""
        for t, btn in self._tool_btns.items():
            active = (t == tool)
            btn.config(relief=tk.SUNKEN if active else tk.FLAT,
                       bg=ACTIVE_BG if active else NORMAL_BG)
        # 도형 드롭다운 버튼도 같이 강조
        if hasattr(self, '_shape_dd_btn'):
            self._shape_dd_btn.config(
                bg=ACTIVE_BG if tool == "shape" else NORMAL_BG)

    def _on_slider_change(self, val) -> None:
        """굵기 슬라이더 변경 핸들러."""
        w = int(float(val))
        save_key = self._tool if self._tool != "shape" else "shape"
        self._tool_sizes[save_key] = w

    def _on_entry_width(self, event=None) -> None:
        """굵기 Entry 입력 확정 시 범위 클리핑."""
        try:
            v = int(self._width_var.get())
            v = max(1, min(30, v))
            self._width_var.set(v)
            save_key = self._tool if self._tool != "shape" else "shape"
            self._tool_sizes[save_key] = v
        except (ValueError, tk.TclError):
            self._width_var.set(self._tool_sizes.get(
                self._tool if self._tool != "shape" else "shape", 3))

    def _show_shape_menu(self) -> None:
        """도형 서브 툴 드롭다운 메뉴를 표시합니다."""
        menu = tk.Menu(self.root, tearoff=0)
        for sub, label in SHAPE_LABELS.items():
            menu.add_command(
                label=label,
                command=lambda s=sub: self._select_shape(s),
            )
        try:
            x = self._shape_dd_btn.winfo_rootx()
            y = self._shape_dd_btn.winfo_rooty() + self._shape_dd_btn.winfo_height()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _select_shape(self, sub: str) -> None:
        """도형 서브 툴을 선택하고 즉시 활성화합니다."""
        self._sub_tool = sub
        if hasattr(self, '_shape_main_btn'):
            self._shape_main_btn.config(text=self._shape_label())
        self._set_tool("shape")

    # 기본 색상 팔레트 (Excel 스타일, 10열×6행)
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

    def _pick_color(self) -> None:
        """Excel 스타일 색상 팔레트 팝업을 표시합니다. 이미 열려있으면 닫습니다."""
        if self._color_popup is not None:
            try:
                self._color_popup.destroy()
            except Exception:
                pass
            self._color_popup = None
            return

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        self._color_popup = popup

        def on_close():
            self._color_popup = None
            try:
                popup.destroy()
            except Exception:
                pass

        popup.bind("<FocusOut>", lambda e: on_close())
        popup.bind("<Escape>", lambda e: on_close())

        COLS = 10
        CELL = 18
        PAD = 4

        frame = tk.Frame(popup, bg="#2b2b2b", padx=PAD, pady=PAD)
        frame.pack()

        for i, color in enumerate(self._PALETTE):
            row, col = divmod(i, COLS)
            btn = tk.Frame(frame, bg=color, width=CELL, height=CELL,
                           cursor="hand2", relief=tk.RAISED, bd=1)
            btn.grid(row=row, column=col, padx=1, pady=1)
            btn.bind("<Button-1>", lambda e, c=color: self._apply_color(c, on_close))
            btn.bind("<Enter>", lambda e, b=btn: b.config(relief=tk.SUNKEN))
            btn.bind("<Leave>", lambda e, b=btn: b.config(relief=tk.RAISED))

        # 위치: 색상 버튼 아래
        self.root.update_idletasks()
        bx = self._color_btn.winfo_rootx()
        by = self._color_btn.winfo_rooty() + self._color_btn.winfo_height() + 2
        popup.geometry(f"+{bx}+{by}")
        popup.focus_force()

    def _apply_color(self, color: str, close_fn) -> None:
        self._color = color
        self._color_display.config(bg=color)
        close_fn()
        try:
            from config import get as cfg_get, save as cfg_save
            c = cfg_get()
            c["last_color"] = color
            cfg_save(c)
        except Exception:
            pass

    # ──────────────────────────────────────────────
    # 마우스 이벤트
    # ──────────────────────────────────────────────

    def _canvas_coords(self, event) -> tuple:
        """캔버스 픽셀 좌표 → 이미지 실제 좌표 (줌 보정)."""
        cx = int(self.canvas.canvasx(event.x) / self._zoom)
        cy = int(self.canvas.canvasy(event.y) / self._zoom)
        return cx, cy

    def _next_tag(self) -> str:
        self._tag_counter += 1
        return f"op_{self._tag_counter}"

    def _press(self, event) -> None:
        # 텍스트 위젯 외부 클릭 시 확정 (FocusOut보다 먼저 처리)
        if self._text_widget is not None:
            self._finish_text_input()
            if self._tool == "text":
                return  # 텍스트 도구면 새 영역 선택 시작 전 이번 클릭은 확정에 사용

        x, y = self._canvas_coords(event)
        self._start = (x, y)
        self._drawing = True
        self._pen_points = [(x, y)]
        self._remove_preview()  # 이전 획 모두 제거 (pen_preview_items 포함)

        if self._tool == "text":
            pass  # drawing=True → _drag에서 preview, _release에서 위젯 생성
            # drawing=True → _drag에서 preview 사각형, _release에서 위젯 생성

        elif self._tool == "eraser":
            self._drawing = False
            idx = find_op_at(self._ops, x, y, radius=10)
            if idx is not None:
                self._ops.pop(idx)
                self._redo_stack.clear()
                self._refresh_canvas()

    def _drag(self, event) -> None:
        if not self._drawing:
            return
        x, y = self._canvas_coords(event)
        x0, y0 = self._start
        color = self._color
        w = self._width_var.get()
        zoom = self._zoom

        def cs(v: float) -> int:
            return int(v * zoom)

        if self._tool == "pen":
            # 이전 획을 지우지 않고 누적 — 실시간 드로잉
            self._pen_points.append((x, y))
            pts = self._pen_points
            if len(pts) >= 2:
                p1, p2 = pts[-2], pts[-1]
                flat = [cs(p1[0]), cs(p1[1]), cs(p2[0]), cs(p2[1])]
                item = self.canvas.create_line(
                    *flat, fill=color, width=max(1, int(w * zoom)),
                    smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND,
                )
                self._pen_preview_items.append(item)

        elif self._tool == "highlighter":
            # 형광펜도 실시간 누적
            self._pen_points.append((x, y))
            pts = self._pen_points
            if len(pts) >= 2:
                p1, p2 = pts[-2], pts[-1]
                flat = [cs(p1[0]), cs(p1[1]), cs(p2[0]), cs(p2[1])]
                item = self.canvas.create_line(
                    *flat, fill=color, width=max(1, int(w * zoom)),
                    smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND,
                    stipple="gray50",
                )
                self._pen_preview_items.append(item)

        elif self._tool == "shape":
            self._remove_preview()
            sub = self._sub_tool
            sx0, sy0, sx1, sy1 = cs(x0), cs(y0), cs(x), cs(y)
            lw = max(1, int(w * zoom))
            if sub == "rect":
                self._preview_item = self.canvas.create_rectangle(
                    sx0, sy0, sx1, sy1, outline=color, width=lw)
            elif sub == "ellipse":
                self._preview_item = self.canvas.create_oval(
                    sx0, sy0, sx1, sy1, outline=color, width=lw)
            elif sub == "line":
                self._preview_item = self.canvas.create_line(
                    sx0, sy0, sx1, sy1, fill=color, width=lw)
            elif sub == "arrow":
                self._preview_item = self.canvas.create_line(
                    sx0, sy0, sx1, sy1, fill=color, width=lw,
                    arrow=tk.LAST,
                    arrowshape=(max(8, w * 3), max(10, w * 4), max(3, w)),
                )

        elif self._tool in ("crop", "mosaic"):
            self._remove_preview()
            sx0, sy0, sx1, sy1 = cs(x0), cs(y0), cs(x), cs(y)
            outline = "#0078D4" if self._tool == "crop" else color
            self._preview_item = self.canvas.create_rectangle(
                sx0, sy0, sx1, sy1,
                outline=outline, width=2, dash=(4, 4),
            )

        elif self._tool == "text":
            self._remove_preview()
            sx0, sy0, sx1, sy1 = cs(x0), cs(y0), cs(x), cs(y)
            self._preview_item = self.canvas.create_rectangle(
                sx0, sy0, sx1, sy1,
                outline="#0078D4", width=1, dash=(4, 4),
            )

    def _release(self, event) -> None:
        if not self._drawing:
            return
        self._drawing = False
        x, y = self._canvas_coords(event)
        x0, y0 = self._start
        self._remove_preview()
        color = self._color
        w = self._width_var.get()
        tag = self._next_tag()

        # 너무 작은 드래그는 무시 (펜/형광펜/텍스트 제외)
        if abs(x - x0) < 2 and abs(y - y0) < 2 and self._tool not in ("pen", "highlighter", "text"):
            return

        if self._tool == "pen":
            pts = self._pen_points + [(x, y)]
            if len(pts) < 2:
                return
            self._commit(Operation("pen", {"points": pts, "color": color, "width": w}, tag))

        elif self._tool == "highlighter":
            pts = self._pen_points + [(x, y)]
            if len(pts) < 2:
                return
            self._commit(Operation("highlighter", {
                "points": pts, "color": color, "width": w, "alpha": 128,
            }, tag))

        elif self._tool == "shape":
            self._commit(Operation("shape", {
                "sub_tool": self._sub_tool,
                "x0": x0, "y0": y0, "x1": x, "y1": y,
                "color": color, "width": w,
            }, tag))

        elif self._tool == "mosaic":
            self._commit(Operation("mosaic", {
                "x0": x0, "y0": y0, "x1": x, "y1": y,
                "block_size": 15,
            }, tag))

        elif self._tool == "crop":
            # crop은 이미지 자체를 변경하므로 base_image를 업데이트
            op = Operation("crop", {
                "x0": x0, "y0": y0, "x1": x, "y1": y,
            }, tag)
            try:
                new_img = render_all(self._base_image, [op])
                self._base_image = new_img.convert("RGBA")
                self._ops = []
                self._redo_stack = []
            except Exception as e:
                print(f"자르기 오류: {e}")

        elif self._tool == "text":
            # 드래그 영역에 텍스트 입력 위젯 생성
            if abs(x - x0) < 5 and abs(y - y0) < 5:
                self._start_text_input(x0, y0, x0 + 200, y0 + 50)
            else:
                self._start_text_input(x0, y0, x, y)
            return  # refresh는 _finish_text_input에서

        self._refresh_canvas()
        self._update_status()

    def _start_text_input(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """지정 영역에 텍스트 인라인 입력 위젯을 생성합니다."""
        zoom = self._zoom
        cx0, cy0 = int(min(x0, x1) * zoom), int(min(y0, y1) * zoom)
        w_px = max(60, int(abs(x1 - x0) * zoom))
        h_px = max(30, int(abs(y1 - y0) * zoom))
        font_size = max(10, self._width_var.get() * 4)

        text_widget = tk.Text(
            self.canvas,
            font=("맑은 고딕", font_size),
            bg="white", fg=self._color,
            relief=tk.SOLID, bd=1,
            wrap=tk.WORD, insertbackground=self._color,
        )
        self._text_rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        self._text_widget = text_widget
        self._text_window = self.canvas.create_window(
            cx0, cy0, anchor=tk.NW,
            window=text_widget,
            width=w_px, height=h_px,
        )
        text_widget.focus_force()
        text_widget.bind("<Escape>", lambda e: self._cancel_text_input())
        # Enter: 줄바꿈 (기본 동작 유지), FocusOut: 자동 확정
        text_widget.bind("<FocusOut>", self._finish_text_input)

    def _finish_text_input(self, event=None) -> Optional[str]:
        """텍스트 입력을 확정하고 Operation으로 커밋합니다."""
        if self._text_widget is None:
            return None
        text = self._text_widget.get("1.0", tk.END).strip()
        rect = self._text_rect
        self.canvas.delete(self._text_window)
        self._text_widget.destroy()
        self._text_widget = None
        self._text_window = None
        self._text_rect = None

        if text and rect:
            x0, y0, x1, y1 = rect
            tag = self._next_tag()
            font_size = max(10, self._width_var.get() * 4)
            op = Operation("text", {
                "x": int(x0), "y": int(y0),
                "text": text,
                "color": self._color,
                "font_size": font_size,
                "box_width": int(abs(x1 - x0)),
            }, tag)
            self._commit(op)
            self._refresh_canvas()
        return "break"

    def _cancel_text_input(self) -> None:
        """텍스트 입력을 취소합니다."""
        if self._text_widget is None:
            return
        self.canvas.delete(self._text_window)
        self._text_widget.destroy()
        self._text_widget = None
        self._text_window = None
        self._text_rect = None

    def _remove_preview(self) -> None:
        if self._preview_item is not None:
            self.canvas.delete(self._preview_item)
            self._preview_item = None
        for item in self._pen_preview_items:
            self.canvas.delete(item)
        self._pen_preview_items.clear()

    # ──────────────────────────────────────────────
    # 편집 히스토리 (undo/redo)
    # ──────────────────────────────────────────────

    def _commit(self, op: Operation) -> None:
        self._ops.append(op)
        self._redo_stack.clear()

    def _undo(self) -> None:
        if not self._ops:
            return
        op = self._ops.pop()
        self._redo_stack.append(op)
        self._refresh_canvas()

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        op = self._redo_stack.pop()
        self._ops.append(op)
        self._refresh_canvas()

    def _reset(self) -> None:
        """모든 편집 내용을 초기화합니다."""
        self._ops = []
        self._redo_stack = []
        self.load_image(self._current_idx)

    # ──────────────────────────────────────────────
    # 저장 / 복사
    # ──────────────────────────────────────────────

    def _get_final_image(self) -> Image.Image:
        """최종 이미지를 반환합니다 (압축 설정 적용)."""
        try:
            from config import get as cfg_get
            cfg = cfg_get()
            compress = cfg.get("compress", False)
            quality = cfg.get("compress_quality", 85)
        except Exception:
            compress = False
            quality = 85

        img = self._get_rendered()
        if compress:
            buf = BytesIO()
            img.save(buf, "JPEG", quality=quality)
            buf.seek(0)
            img = Image.open(buf).copy()
        return img

    def _save(self) -> None:
        img = self._get_final_image()
        try:
            from config import get as cfg_get
            compress = cfg_get().get("compress", False)
        except Exception:
            compress = False

        ext = ".jpg" if compress else ".png"
        ftypes = [("PNG 이미지", "*.png"), ("JPEG 이미지", "*.jpg"), ("모든 파일", "*.*")]
        path = filedialog.asksaveasfilename(
            defaultextension=ext, filetypes=ftypes, title="이미지 저장"
        )
        if path:
            img.save(path)
            self._flash("저장 완료: " + path)

    def _copy(self) -> None:
        img = self._get_final_image()
        if copy_to_clipboard(img):
            self._flash("클립보드에 복사됨!")
        else:
            messagebox.showwarning("복사 실패", "클립보드 복사에 실패했습니다.")

    def _flash(self, msg: str) -> None:
        orig = self.root.title()
        self.root.title(msg)
        self.root.after(2000, lambda: self.root.title(orig))

    # ──────────────────────────────────────────────
    # 히스토리 패널 콜백
    # ──────────────────────────────────────────────

    def _on_history_select(self, idx: int) -> None:
        """우측 패널에서 썸네일을 클릭했을 때."""
        self.load_image(idx)

    # ──────────────────────────────────────────────
    # 퍼블릭 인터페이스
    # ──────────────────────────────────────────────

    def show(self) -> None:
        """창을 표시합니다. master가 없으면 mainloop를 실행합니다."""
        self.root.geometry("1440x810")

        if not isinstance(self.root, tk.Toplevel):
            self.root.mainloop()
        else:
            self.root.deiconify()


# ──────────────────────────────────────────────────────────────
# 모듈 레벨 진입점 (main.py에서 호출)
# ──────────────────────────────────────────────────────────────

def open_editor(image: Image.Image, master: Optional[tk.Widget] = None,
                history_idx: int = 0, history=None) -> EditorWindow:
    """편집기 창을 열고 EditorWindow 인스턴스를 반환합니다.

    Parameters
    ----------
    image : PIL.Image
        표시할 이미지 (history가 없을 때 단독으로 사용).
    master : tk.Widget, optional
        부모 tkinter 위젯.
    history_idx : int
        history에서 초기 선택할 인덱스.
    history : CaptureHistory | list, optional
        캡처 히스토리 저장소. None이면 image를 단일 항목 리스트로 감쌉니다.
    """
    if history is None:
        # history가 없으면 현재 이미지만 포함하는 리스트로 처리
        try:
            import history as hist_module
            history = hist_module.get_history()
        except Exception:
            history = [image]
            history_idx = 0

    editor = EditorWindow(history=history, initial_idx=history_idx, master=master)
    editor.show()
    return editor
