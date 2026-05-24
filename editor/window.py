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

def _set_window_icon(win: "tk.Wm") -> None:
    """image/program/icon.png 를 창 아이콘으로 설정합니다.
    파일이 없거나 오류 시 무시합니다."""
    try:
        import sys
        from pathlib import Path
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).resolve().parent.parent
        icon_path = base / "image" / "program" / "icon.png"
        if icon_path.exists():
            img = Image.open(icon_path).convert("RGBA")
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(img)
            win.iconphoto(True, photo)
            # GC 방지: 창 객체에 참조 보관
            win._icon_photo = photo  # type: ignore[attr-defined]
    except Exception:
        pass


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
        defaults = {"pen": 3, "highlighter": 9, "shape": 2,
                    "eraser": 10, "crop": 2, "mosaic": 2}
        defaults.update(cfg.get("tool_sizes", {}))
        self._tool_sizes: dict = defaults

        # 도구 상태
        self._tool: str = "pen"
        self._sub_tool: str = "rect"
        self._color: str = cfg.get("last_color", "#E74C3C")
        # 도구별 독립 색상 (config에서 복원)
        _last = cfg.get("last_color", "#E74C3C")
        _default_colors: dict = {
            "pen": _last, "highlighter": "#FFFF00", "shape": _last,
            "text": _last, "mosaic": _last, "eraser": _last, "crop": _last,
        }
        _default_colors.update(cfg.get("tool_colors", {}))
        self._tool_colors: dict = _default_colors

        # 색상 선택 팝업 참조 (중복 방지)
        self._color_popup: Optional[tk.Toplevel] = None

        # 드로잉 상태
        self._drawing: bool = False
        self._start: tuple = (0, 0)
        self._pen_points: list = []
        self._preview_item = None
        self._pen_preview_items: list = []  # 펜/형광펜 실시간 획 누적용
        self._mosaic_preview_tk = None  # 모자이크 미리보기 GC 방지

        # 텍스트 인라인 편집 상태
        self._text_widget: Optional[tk.Text] = None
        self._text_window = None
        self._text_rect: Optional[tuple] = None

        # 줌
        self._zoom: float = 1.0
        self._zoom_idx: int = ZOOM_STEPS.index(1.0)

        # 캔버스 내 이미지 오프셋 (가운데 정렬용)
        self._img_x: int = 0
        self._img_y: int = 0

        # 19회차 item 3: 자르기 패널 (W/H 입력 + 자르기 버튼)
        self._crop_panel: Optional[tk.Frame] = None
        self._crop_panel_id: Optional[int] = None
        self._crop_var_w: Optional[tk.IntVar] = None
        self._crop_var_h: Optional[tk.IntVar] = None
        self._crop_panel_syncing: bool = False

        # 19회차 item 7: 도구 크기/색상 인디케이터 (canvas oval)
        self._tool_cursor_item: Optional[int] = None

        # 이미지별 편집 저장소 / 되돌리기 스택
        self._ops_store: dict = {}
        self._reset_stack: list = []
        self._reset_redo_stack: list = []
        self._base_image_stack: list = []       # 자르기 undo용
        self._base_image_redo_stack: list = []  # 자르기 redo용
        # 이미지 삭제 undo 스택: [(idx, PIL.Image, ops_store_entry)]
        self._del_undo_stack: list = []


        # 자르기 상태 (액자 핸들 방식)
        self._crop_rect: Optional[tuple] = None       # (x0, y0, x1, y1) 이미지 픽셀
        self._crop_handle: Optional[str] = None       # 드래그 중인 핸들
        self._crop_overlay_items: list = []           # 캔버스 오버레이 아이템 IDs

        # 창 구성
        if master is not None:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()

        self.root.title("스마트 캡쳐 - 편집기")
        self.root.resizable(True, True)
        _set_window_icon(self.root)

        self._build_ui()
        self.load_image(initial_idx)  # -1이면 빈 상태로 초기화

    # ──────────────────────────────────────────────
    # 창 구성
    # ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        """전체 UI를 구성합니다."""
        self._build_toolbar()
        self._build_prop_bar()

        # PanedWindow으로 패널 너비 드래그 조절 가능
        paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        panel_host = tk.Frame(paned, bg="#2D2D2D")
        paned.add(panel_host, weight=0)

        self._history_panel = HistoryPanel(
            parent_frame=panel_host,
            history=self._history,
            on_select_callback=self._on_history_select,
            on_copy_callback=self._copy_image_at,
            on_save_callback=self._save_image_at,
            on_delete_callback=self._delete_image_at,
        )

        canvas_area = tk.Frame(paned)
        paned.add(canvas_area, weight=1)

        self._build_canvas(canvas_area)
        self._build_statusbar(canvas_area)

        self._bind_keys()

    def _build_toolbar(self) -> None:
        """상단 툴바를 구성합니다."""
        # _width_var은 prop_bar에서도 사용하므로 먼저 초기화
        self._width_var = tk.IntVar(value=self._tool_sizes.get("pen", 3))

        # 에디터 아이콘 로드 (GC 방지를 위해 인스턴스 변수에 보관)
        self._editor_icons: dict = self._load_editor_icons()

        bar = tk.Frame(self.root, bd=1, relief=tk.GROOVE)
        bar.pack(side=tk.TOP, fill=tk.X)

        def sep():
            ttk.Separator(bar, orient=tk.VERTICAL).pack(
                side=tk.LEFT, fill=tk.Y, padx=6, pady=2
            )

        def ic(name):
            """아이콘 이미지를 반환. 없으면 None (텍스트 폴백)."""
            return self._editor_icons.get(name)

        # ── 히스토리 그룹 ──
        self._tb_btn(bar, "뒤로", self._undo,  icon_img=ic("뒤로"))
        self._tb_btn(bar, "앞으로", self._redo,  icon_img=ic("앞으로"))
        self._tb_btn(bar, "초기화",   self._reset, icon_img=ic("초기화"))
        sep()

        # ── 도구 그룹 ──
        self._tool_btns: dict = {}

        def mk_tool(label: str, tool: str, icon_name: str = "") -> tk.Button:
            """도구 버튼 생성. icon_name 아이콘 있으면 위/텍스트 아래 compound."""
            btn = self._tb_btn(bar, label, lambda t=tool: self._set_tool(t),
                               icon_img=ic(icon_name) if icon_name else None)
            self._tool_btns[tool] = btn
            return btn

        mk_tool("펜",    "pen",         "펜")
        mk_tool("형광펜", "highlighter", "형광펜")

        # ── 도형: 메인(현재 도형 텍스트, 고정 너비) + 드롭다운(도형.png + "도형선택") ──
        shape_frame = tk.Frame(bar)
        shape_frame.pack(side=tk.LEFT, padx=1, pady=2)
        # 메인: 다른 icon+text 버튼과 동일한 compound=TOP 스타일, 고정 너비
        # 현재 선택된 도형의 아이콘을 표시 (GC 방지: _editor_icons에 이미 저장됨)
        # width=50 픽셀 고정 (이미지가 설정되면 width는 픽셀 단위로 동작)
        _cur_shape_ic = self._editor_icons.get(self._shape_label())
        if _cur_shape_ic is not None:
            self._shape_main_btn = tk.Button(
                shape_frame,
                image=_cur_shape_ic,
                text=self._shape_label(),
                compound=tk.TOP,
                width=70,   # 40px 아이콘 기준 픽셀 너비
                relief=tk.FLAT,
                font=("맑은 고딕", 8),
                command=lambda: self._select_shape(self._sub_tool),
                padx=4, pady=2,
            )
        else:
            self._shape_main_btn = tk.Button(
                shape_frame,
                text=self._shape_label(),
                width=5,
                relief=tk.FLAT,
                font=("맑은 고딕", 9),
                command=lambda: self._select_shape(self._sub_tool),
                padx=4, pady=2,
            )
        self._shape_main_btn.pack(side=tk.LEFT, padx=1, pady=2)
        self._tool_btns["shape"] = self._shape_main_btn
        # 드롭다운: 도형.png 아이콘 + "도형선택" 텍스트
        _dd_ic = ic("도형")
        if _dd_ic is not None:
            shape_dd_btn = tk.Button(
                shape_frame, image=_dd_ic, text="도형선택",
                compound=tk.TOP, relief=tk.FLAT,
                font=("맑은 고딕", 8),
                command=self._show_shape_menu,
                padx=4, pady=2,
            )
        else:
            shape_dd_btn = tk.Button(
                shape_frame, text="▼ 도형선택", relief=tk.FLAT,
                font=("맑은 고딕", 9),
                command=self._show_shape_menu,
            )
        shape_dd_btn.pack(side=tk.LEFT)
        self._shape_dd_btn = shape_dd_btn

        mk_tool("텍스트", "text",   "텍스트")
        mk_tool("지우개", "eraser", "지우개")
        sep()

        # ── 편집 그룹 ──
        mk_tool("자르기",  "crop",   "자르기")
        mk_tool("모자이크", "mosaic", "모자이크")
        sep()

        # ── 복사 / 저장 / 삭제 ──
        self._tb_btn(bar, "복사", self._copy,   icon_img=ic("복사"))
        self._tb_btn(bar, "저장", self._save,   icon_img=ic("저장"))
        self._tb_btn(bar, "삭제", self._delete, icon_img=ic("삭제"))
        sep()

        # 초기 도구 강조
        self._highlight_tool("pen")

    def _load_editor_icons(self) -> dict:
        """image/editor/*.png 를 로드해 {파일명(확장자제외): PhotoImage} dict로 반환합니다.
        파일이 없거나 오류 시 해당 키를 포함하지 않습니다."""
        result: dict = {}
        try:
            import sys
            from pathlib import Path
            from PIL import Image, ImageTk
            if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
                base = Path(sys._MEIPASS)
            else:
                # editor/window.py → 상위(프로젝트 루트)
                base = Path(__file__).resolve().parent.parent
            img_dir = base / "image" / "editor"
            SIZE = (40, 40)
            for path in img_dir.glob("*.png"):
                try:
                    img = Image.open(path).convert("RGBA").resize(SIZE, Image.LANCZOS)
                    result[path.stem] = ImageTk.PhotoImage(img)
                except Exception:
                    pass
        except Exception:
            pass
        return result

    def _tb_btn(self, parent: tk.Widget, text: str, command,
                icon_img=None) -> tk.Button:
        """툴바 버튼을 만들고 반환합니다.
        icon_img 가 있으면 아이콘(위)+텍스트(아래) compound 버튼,
        없으면 텍스트/이모지 버튼."""
        if icon_img is not None:
            btn = tk.Button(
                parent, image=icon_img, text=text,
                compound=tk.TOP, relief=tk.FLAT,
                font=("맑은 고딕", 8),
                command=command, padx=4, pady=2,
            )
        else:
            btn = tk.Button(
                parent, text=text, relief=tk.FLAT,
                font=("맑은 고딕", 11),
                command=command,
            )
        btn.pack(side=tk.LEFT, padx=1, pady=2)
        return btn

    # ──────────────────────────────────────────────
    # 도구별 속성 바 (색상 + 두께 셀렉트 바)
    # ──────────────────────────────────────────────

    _PROP_COLORS = [
        "#000000", "#FFFFFF", "#E74C3C", "#3498DB", "#2ECC71",
        "#AAAAAA", "#FFFF00", "#9B59B6", "#1ABC9C", "#333333",
    ]
    _PROP_WIDTHS_PEN = [1, 3, 5, 8, 12]        # 펜/도형/기타
    _PROP_WIDTHS_HL  = [5, 9, 13, 17, 21]     # 형광펜 (차별화)

    def _build_prop_bar(self) -> None:
        """색상/두께 셀렉트 바 (툴바 아래 두 번째 행)."""
        bar = tk.Frame(self.root, bd=1, relief=tk.GROOVE, pady=2)
        bar.pack(side=tk.TOP, fill=tk.X)
        self._prop_bar = bar

        # ── 색상 ──
        tk.Label(bar, text="색상", font=("맑은 고딕", 9)).pack(side=tk.LEFT, padx=(6, 2))

        swatch_host = tk.Frame(bar)
        swatch_host.pack(side=tk.LEFT)
        self._prop_swatch_frames: list = []
        for i, col in enumerate(self._PROP_COLORS):
            fr = tk.Frame(swatch_host, bg=col, width=20, height=20,
                          cursor="hand2", relief=tk.RAISED, bd=1)
            fr.grid(row=i // 5, column=i % 5, padx=1, pady=1)
            fr.bind("<Button-1>", lambda e, c=col: self._apply_preset_color(c))
            self._prop_swatch_frames.append((col, fr))

        # 커스텀 색상 버튼 (19회차 item 8: 별도 색상 스워치 제거, 버튼만 유지)
        self._custom_color_btn = tk.Button(bar, text="+", font=("맑은 고딕", 9),
                                           relief=tk.FLAT, command=self._pick_color)
        self._custom_color_btn.pack(side=tk.LEFT, padx=(4, 4))

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=4, pady=3)

        # ── 두께 ──
        tk.Label(bar, text="두께", font=("맑은 고딕", 9)).pack(side=tk.LEFT, padx=(4, 2))

        # 5개 슬롯 고정 (도구별로 값만 갱신)
        self._prop_width_slots: list = []  # (frame, canvas, label)
        for i, w in enumerate(self._PROP_WIDTHS_PEN):
            wf = tk.Frame(bar, cursor="hand2", padx=4, pady=2, relief=tk.FLAT, bd=1)
            wf.pack(side=tk.LEFT, padx=1)
            line_h = 24
            cv = tk.Canvas(wf, width=44, height=line_h, bg="white", highlightthickness=0)
            cv.pack()
            lbl = tk.Label(wf, text=f"{w}px", font=("맑은 고딕", 8))
            lbl.pack()
            self._prop_width_slots.append((wf, cv, lbl))

        self._update_prop_bar()

    def _apply_preset_color(self, color: str) -> None:
        """셀렉트 바 색상 선택."""
        self._color = color
        key = self._tool if self._tool != "shape" else "shape"
        self._tool_colors[key] = color
        self._update_prop_bar()
        try:
            from config import get as cfg_get, save as cfg_save
            c = cfg_get()
            c["last_color"] = color
            c.setdefault("tool_colors", {})[key] = color
            cfg_save(c)
        except Exception:
            pass

    def _apply_preset_width(self, width: int) -> None:
        """셀렉트 바 두께 선택."""
        self._width_var.set(width)
        save_key = self._tool if self._tool != "shape" else "shape"
        self._tool_sizes[save_key] = width
        self._update_prop_bar()
        try:
            from config import get as cfg_get, save as cfg_save
            cfg = cfg_get()
            cfg.setdefault("tool_sizes", {})[save_key] = width
            cfg_save(cfg)
        except Exception:
            pass

    def _current_widths(self) -> list:
        if self._tool == "highlighter":
            return self._PROP_WIDTHS_HL
        return self._PROP_WIDTHS_PEN

    def _update_prop_bar(self) -> None:
        """현재 색상/두께에 맞게 셀렉트 바 강조 갱신."""
        if not hasattr(self, '_prop_swatch_frames'):
            return
        cur_color = self._color.lower()
        for col, fr in self._prop_swatch_frames:
            active = col.lower() == cur_color
            fr.config(relief=tk.SUNKEN if active else tk.RAISED, bd=2 if active else 1)
        # 19회차 item 8: _custom_color_frame 제거됨 — 두께 슬롯 선에 색상 반영

        if not hasattr(self, '_prop_width_slots'):
            return
        widths = self._current_widths()
        cur_w = self._width_var.get()
        for i, (wf, cv, lbl) in enumerate(self._prop_width_slots):
            w = widths[i]
            lbl.config(text=f"{w}px")
            cv.delete("all")
            vis_w = min(w, 20)
            cy = 12
            # 19회차 item 8: 두께 선을 현재 선택 색상으로 표시
            line_color = self._color if self._tool not in ("eraser", "mosaic", "crop") else "#333333"
            cv.create_line(4, cy, 40, cy, width=vis_w, fill=line_color, capstyle="round")
            active = (cur_w == w)
            wf.config(relief=tk.SUNKEN if active else tk.FLAT,
                      bg="#FFE8E8" if active else "SystemButtonFace")
            for widget in (wf, cv, lbl):
                widget.unbind("<Button-1>")
                widget.bind("<Button-1>", lambda e, ww=w: self._apply_preset_width(ww))

        # 도형 커서 아이템 색상 즉시 반영
        col = self._color
        for attr, cfg in (
            ("_cur_s_rect",    {"outline": col}),
            ("_cur_s_oval",    {"outline": col}),
            ("_cur_s_line",    {"fill": col}),
            ("_cur_s_arrow",   {"fill": col}),
        ):
            item = getattr(self, attr, None)
            if item is not None:
                try:
                    self.canvas.itemconfig(item, **cfg)
                except Exception:
                    pass

    def _build_canvas(self, parent: tk.Widget) -> None:
        """스크롤 가능한 메인 캔버스를 구성합니다."""
        frame = tk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True)

        h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            frame, cursor="",
            xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set,
            highlightthickness=0, bg="#C8C8C8",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        self._bg_item = self.canvas.create_image(0, 0, anchor=tk.NW)
        self._bg_tk: Optional[ImageTk.PhotoImage] = None

        # 19회차 item 7: 브러시 크기 원 인디케이터 (펜/지우개 공용)
        self._tool_cursor_item = self.canvas.create_oval(
            0, 0, 0, 0, outline=self._color, width=2, state=tk.HIDDEN)

        # 커스텀 커서 아이템 (cursor="none" 시 OS 커서 대체)
        c = self.canvas
        col = self._color
        # 펜: 대각선 몸체 + 끝점 원
        self._cur_pen_body = c.create_line(0, 0, 0, 0, fill=col, width=2,
                                           capstyle=tk.ROUND, state=tk.HIDDEN)
        self._cur_pen_tip  = c.create_oval(0, 0, 0, 0, fill=col, outline="white",
                                           width=1, state=tk.HIDDEN)
        # 형광펜: 납작한 사각형 (stipple로 반투명)
        self._cur_hl_body  = c.create_rectangle(0, 0, 0, 0, fill=col, outline=col,
                                                stipple="gray50", state=tk.HIDDEN)
        # 도형: 모양별 미니 아이템
        self._cur_s_rect  = c.create_rectangle(0, 0, 0, 0, fill="", outline=col,
                                               width=2, state=tk.HIDDEN)
        self._cur_s_oval  = c.create_oval(0, 0, 0, 0, fill="", outline=col,
                                          width=2, state=tk.HIDDEN)
        self._cur_s_line  = c.create_line(0, 0, 0, 0, fill=col, width=2,
                                          state=tk.HIDDEN)
        self._cur_s_arrow = c.create_line(0, 0, 0, 0, fill=col, width=2,
                                          arrow=tk.LAST, arrowshape=(10, 12, 4),
                                          state=tk.HIDDEN)
        # 지우개: 흰 사각형
        self._cur_eraser  = c.create_rectangle(0, 0, 0, 0, fill="white",
                                               outline="#888888", width=1,
                                               state=tk.HIDDEN)
        # 일괄 관리용 목록 (도형 커서 아이템)
        self._custom_cur_items: list = [
            self._cur_pen_body, self._cur_pen_tip,
            self._cur_hl_body,
            self._cur_s_rect, self._cur_s_oval, self._cur_s_line, self._cur_s_arrow,
            self._cur_eraser,
        ]

        # 19회차 item 3: 자르기 패널 빌드
        self._build_crop_panel()

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<MouseWheel>", self._on_canvas_scroll)
        self.canvas.bind("<Configure>", lambda e: self._on_canvas_resize())
        self.canvas.bind("<ButtonPress-3>", self._on_pan_start)
        self.canvas.bind("<B3-Motion>", self._on_pan_motion)
        self.canvas.bind("<ButtonRelease-3>", self._on_pan_end)  # 19회차 item 9
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<Leave>", self._on_canvas_leave)

    def _build_statusbar(self, parent: tk.Widget) -> None:
        """하단 상태바를 구성합니다."""
        bar = tk.Frame(parent, bd=1, relief=tk.SUNKEN)
        bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._status_zoom = tk.Label(
            bar, text="100%", font=("맑은 고딕", 11)
        )
        self._status_zoom.pack(side=tk.LEFT, padx=8)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, pady=2)

        tk.Button(bar, text="+", font=("맑은 고딕", 11),
                  relief=tk.FLAT, command=self._zoom_in,
                  width=2).pack(side=tk.LEFT, padx=2)
        tk.Button(bar, text="-", font=("맑은 고딕", 11),
                  relief=tk.FLAT, command=self._zoom_out,
                  width=2).pack(side=tk.LEFT, padx=2)
        tk.Button(bar, text="1:1", font=("맑은 고딕", 11),
                  relief=tk.FLAT, command=self._zoom_reset,
                  width=3).pack(side=tk.LEFT, padx=2)

        # 이미지 크기 — 우측 정렬
        self._status_size = tk.Label(
            bar, text="크기: -", font=("맑은 고딕", 11), anchor=tk.E
        )
        self._status_size.pack(side=tk.RIGHT, padx=8)

    def _bind_keys(self) -> None:
        """키보드 단축키를 등록합니다."""
        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Control-y>", lambda e: self._redo())
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Control-c>", lambda e: self._copy())
        self.root.bind("<Up>", lambda e: self._next_image())
        self.root.bind("<Down>", lambda e: self._prev_image())
        self.root.bind("<Escape>", lambda e: self._on_escape())
        self.root.bind("<Return>", lambda e: self._confirm_crop())
        self.root.bind("<Delete>", self._on_delete_key)
        # 캔버스 포커스 시에도 위아래 이미지 탐색이 작동하도록 직접 바인딩
        self.canvas.bind("<Up>",   lambda e: self._next_image() or "break")
        self.canvas.bind("<Down>", lambda e: self._prev_image() or "break")

    # ──────────────────────────────────────────────
    # 이미지 로드 / 렌더링
    # ──────────────────────────────────────────────

    def load_image(self, idx: int) -> None:
        """history[idx] 이미지를 캔버스에 로드합니다. idx=-1이면 빈 상태로 표시합니다."""
        # 현재 이미지의 편집 상태를 저장 (base_image 포함 — 자르기 영속 유지)
        if self._base_image is not None and self._current_idx >= 0:
            self._ops_store[self._current_idx] = (
                self._ops.copy(),
                self._redo_stack.copy(),
                [(list(a), list(b)) for a, b in self._reset_stack],
                [(list(a), list(b)) for a, b in self._reset_redo_stack],
                self._base_image.copy(),            # idx 4: 크롭된 base 이미지
                list(self._base_image_stack),       # idx 5: 자르기 undo 스택
                list(self._base_image_redo_stack),  # idx 6: 자르기 redo 스택
            )

        # 자르기 오버레이 초기화
        self._clear_crop_overlay()
        self._crop_rect = None
        self._crop_handle = None

        # 빈 상태 처리
        if idx < 0 or len(self._history) == 0:
            self._current_idx = -1
            self._base_image = None
            self._ops = []
            self._redo_stack = []
            self._reset_stack = []
            self._reset_redo_stack = []
            self._base_image_stack = []
            self._base_image_redo_stack = []
            if hasattr(self, "_history_panel"):
                try:
                    self._history_panel.set_selected(-1)
                except Exception:
                    pass
            self._refresh_canvas()
            self._update_status()
            return

        self._current_idx = idx
        img = self._history[idx]
        self._base_image = img.convert("RGBA")

        # 이 이미지의 저장된 편집 상태 복원 (base_image 포함)
        saved = self._ops_store.get(idx)
        if saved:
            self._ops = list(saved[0])
            self._redo_stack = list(saved[1])
            self._reset_stack = [(list(a), list(b)) for a, b in (saved[2] if len(saved) > 2 else [])]
            self._reset_redo_stack = [(list(a), list(b)) for a, b in (saved[3] if len(saved) > 3 else [])]
            # 자르기 적용된 base 이미지 복원 (이미지 전환 후에도 자르기 유지)
            if len(saved) > 4 and saved[4] is not None:
                self._base_image = saved[4].copy()
            self._base_image_stack = list(saved[5]) if len(saved) > 5 else []
            self._base_image_redo_stack = list(saved[6]) if len(saved) > 6 else []
        else:
            self._ops = []
            self._redo_stack = []
            self._reset_stack = []
            self._reset_redo_stack = []
            self._base_image_stack = []
            self._base_image_redo_stack = []

        # 줌 초기화
        self._zoom = 1.0
        self._zoom_idx = ZOOM_STEPS.index(1.0)

        # 자르기 도구 활성 중이면 새 이미지에 맞게 crop_rect 초기화
        if self._tool == "crop":
            iw, ih = self._base_image.size
            self._crop_rect = (0, 0, iw, ih)

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
        """캔버스에 현재 이미지를 표시합니다 (줌 적용, 가운데 정렬)."""
        if self._base_image is None:
            self.canvas.itemconfig(self._bg_item, image="")
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
        self._center_image(new_w, new_h)
        if self._tool == "crop" and self._crop_rect is not None:
            self._draw_crop_overlay()

    def _center_image(self, iw: int, ih: int) -> None:
        """이미지를 캔버스 가운데에 배치하고 scrollregion을 갱신합니다."""
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1:
            cw = iw + 40
        if ch <= 1:
            ch = ih + 40
        self._img_x = max(0, (cw - iw) // 2)
        self._img_y = max(0, (ch - ih) // 2)
        self.canvas.coords(self._bg_item, self._img_x, self._img_y)
        total_w = max(iw + 2 * self._img_x, cw)
        total_h = max(ih + 2 * self._img_y, ch)
        # 이미지 밖으로도 팬 가능하도록 scrollregion을 넉넉하게 확장
        PAD = 500
        self.canvas.config(scrollregion=(-PAD, -PAD, total_w + PAD, total_h + PAD))

    def _on_canvas_resize(self) -> None:
        """창 크기 변경 시 이미지 가운데 정렬 재계산."""
        if self._base_image is None:
            return
        iw = max(1, int(self._base_image.width * self._zoom))
        ih = max(1, int(self._base_image.height * self._zoom))
        self._center_image(iw, ih)
        if self._tool == "crop" and self._crop_rect is not None:
            self._draw_crop_overlay()

    def _update_status(self) -> None:
        """하단 상태바를 갱신합니다."""
        if self._base_image:
            iw, ih = self._base_image.size
            self._status_size.config(text=f"크기: {iw} × {ih}")
        else:
            self._status_size.config(text="크기: -")
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
        """Ctrl+휠로 줌 조절 (18회차: 휠 세로스크롤 제거 — 우클릭 패닝으로 대체)."""
        if event.state & 0x4:  # Ctrl 키
            if event.delta > 0:
                self._zoom_in()
            else:
                self._zoom_out()
        # 그 외 휠: 무시 (우클릭 드래그로 패닝)

    # ──────────────────────────────────────────────
    # 도구 관련
    # ──────────────────────────────────────────────

    def _set_tool(self, tool: str) -> None:
        """도구를 전환합니다. 이전 도구의 굵기/색상을 저장하고 새 도구의 설정을 복원합니다."""
        # 자르기 도구에서 다른 도구로 전환: 오버레이 제거, 커서·패널 초기화
        if self._tool == "crop" and tool != "crop":
            self._clear_crop_overlay()
            self._crop_rect = None
            self.canvas.config(cursor=self._tool_cursor())

        if self._text_widget is not None:
            self._finish_text_input()

        save_key = self._tool if self._tool != "shape" else "shape"
        # 현재 도구 굵기/색상 저장
        self._tool_sizes[save_key] = self._width_var.get()
        self._tool_colors[save_key] = self._color
        try:
            from config import get as cfg_get, save as cfg_save
            cfg = cfg_get()
            cfg.setdefault("tool_sizes", {})[save_key] = self._tool_sizes[save_key]
            cfg_save(cfg)
        except Exception:
            pass

        self._tool = tool
        self._highlight_tool(tool)

        # 새 도구 굵기/색상 복원
        restore_key = tool if tool != "shape" else "shape"
        self._width_var.set(self._tool_sizes.get(restore_key, 3))
        self._color = self._tool_colors.get(restore_key, self._color)
        self._update_prop_bar()

        # 자르기 도구로 전환: 오버레이 초기화
        if tool == "crop" and self._base_image is not None:
            iw, ih = self._base_image.size
            self._crop_rect = (0, 0, iw, ih)
            self._draw_crop_overlay()

        # 도구 전환 즉시 커서 갱신 (다음 motion 이벤트를 기다리지 않음)
        self.canvas.config(cursor=self._tool_cursor())

    def _shape_label(self) -> str:
        labels = {"rect": "사각형", "ellipse": "원", "arrow": "화살표", "line": "직선"}
        return labels.get(self._sub_tool, "사각형")

    def _highlight_tool(self, tool: str) -> None:
        """현재 선택된 도구 버튼을 강조합니다.
        드롭다운(shape_dd_btn)은 독립적이므로 강조에서 제외합니다."""
        for t, btn in self._tool_btns.items():
            active = (t == tool)
            btn.config(relief=tk.SUNKEN if active else tk.FLAT,
                       bg=ACTIVE_BG if active else NORMAL_BG)

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
            label = self._shape_label()
            shape_ic = self._editor_icons.get(label)
            if shape_ic is not None:
                self._shape_main_btn.config(
                    image=shape_ic, text=label, compound=tk.TOP
                )
            else:
                self._shape_main_btn.config(text=label)
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

        # 위치: + 버튼 아래
        self.root.update_idletasks()
        ref = getattr(self, '_custom_color_btn', self.root)
        bx = ref.winfo_rootx()
        by = ref.winfo_rooty() + ref.winfo_height() + 2
        popup.geometry(f"+{bx}+{by}")
        popup.focus_force()

    def _apply_color(self, color: str, close_fn) -> None:
        self._color = color
        key = self._tool if self._tool != "shape" else "shape"
        self._tool_colors[key] = color
        close_fn()
        self._update_prop_bar()
        try:
            from config import get as cfg_get, save as cfg_save
            c = cfg_get()
            c["last_color"] = color
            c.setdefault("tool_colors", {})[key] = color
            cfg_save(c)
        except Exception:
            pass

    # ──────────────────────────────────────────────
    # 마우스 이벤트
    # ──────────────────────────────────────────────

    def _canvas_coords(self, event) -> tuple:
        """캔버스 픽셀 좌표 → 이미지 실제 좌표 (줌 + 가운데 오프셋 보정)."""
        cx = int((self.canvas.canvasx(event.x) - self._img_x) / self._zoom)
        cy = int((self.canvas.canvasy(event.y) - self._img_y) / self._zoom)
        return cx, cy

    def _next_tag(self) -> str:
        self._tag_counter += 1
        return f"op_{self._tag_counter}"

    _CROP_HANDLE_SIZE = 8  # 핸들 크기 (캔버스 픽셀)

    def _get_crop_handle(self, ix: float, iy: float) -> Optional[str]:
        """이미지 좌표 (ix, iy)가 어느 핸들 위에 있는지 반환합니다."""
        if self._crop_rect is None:
            return None
        x0, y0, x1, y1 = self._crop_rect
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        H = self._CROP_HANDLE_SIZE / self._zoom  # 이미지 좌표 단위 허용 반경
        handles = {
            "nw": (x0, y0), "n": (mx, y0), "ne": (x1, y0),
            "w":  (x0, my),               "e":  (x1, my),
            "sw": (x0, y1), "s": (mx, y1), "se": (x1, y1),
        }
        for name, (hx, hy) in handles.items():
            if abs(ix - hx) <= H and abs(iy - hy) <= H:
                return name
        return None

    def _draw_crop_overlay(self) -> None:
        """자르기 액자 오버레이(어두운 마스크 + 테두리 + 핸들)를 캔버스에 그립니다."""
        self._clear_crop_overlay()
        if self._crop_rect is None or self._base_image is None:
            return
        x0, y0, x1, y1 = self._crop_rect
        iw, ih = self._base_image.size
        zoom = self._zoom
        ox, oy = self._img_x, self._img_y

        def cx(v): return int(v * zoom) + ox
        def cy(v): return int(v * zoom) + oy

        ccx0, ccy0, ccx1, ccy1 = cx(x0), cy(y0), cx(x1), cy(y1)
        cix0, ciy0, cix1, ciy1 = cx(0), cy(0), cx(iw), cy(ih)

        items = self._crop_overlay_items

        # 4방향 반투명 음영 마스크 (stipple gray50 = ~50% 투명도)
        # 자르기 버튼 누르기 전까지 원본 이미지가 어둡게 비쳐 보임
        if ccy0 > ciy0:
            items.append(self.canvas.create_rectangle(
                cix0, ciy0, cix1, ccy0, fill="#000000", outline="", stipple="gray50"))
        if ccy1 < ciy1:
            items.append(self.canvas.create_rectangle(
                cix0, ccy1, cix1, ciy1, fill="#000000", outline="", stipple="gray50"))
        if ccx0 > cix0:
            items.append(self.canvas.create_rectangle(
                cix0, ccy0, ccx0, ccy1, fill="#000000", outline="", stipple="gray50"))
        if ccx1 < cix1:
            items.append(self.canvas.create_rectangle(
                ccx1, ccy0, cix1, ccy1, fill="#000000", outline="", stipple="gray50"))

        # 테두리 (흰 점선 + 파란 실선)
        items.append(self.canvas.create_rectangle(
            ccx0, ccy0, ccx1, ccy1, outline="#FFFFFF", width=1, dash=(4, 4)))
        items.append(self.canvas.create_rectangle(
            ccx0, ccy0, ccx1, ccy1, outline="#0078D4", width=1))

        # 8개 핸들
        H = self._CROP_HANDLE_SIZE
        mx_c, my_c = (ccx0 + ccx1) // 2, (ccy0 + ccy1) // 2
        hpos = {
            "nw": (ccx0, ccy0), "n": (mx_c, ccy0), "ne": (ccx1, ccy0),
            "w":  (ccx0, my_c),                     "e":  (ccx1, my_c),
            "sw": (ccx0, ccy1), "s": (mx_c, ccy1),  "se": (ccx1, ccy1),
        }
        for _, (hx, hy) in hpos.items():
            items.append(self.canvas.create_rectangle(
                hx - H, hy - H, hx + H, hy + H,
                fill="white", outline="#0078D4", width=1))

        # 19회차 item 3: 자르기 패널 위치/값 갱신
        self._update_crop_panel()

    def _clear_crop_overlay(self) -> None:
        """캔버스에서 자르기 오버레이를 모두 제거합니다."""
        for item in self._crop_overlay_items:
            self.canvas.delete(item)
        self._crop_overlay_items.clear()
        # 19회차 item 3: 패널 숨김
        if self._crop_panel_id is not None:
            self.canvas.itemconfig(self._crop_panel_id, state=tk.HIDDEN)

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
            pass  # drawing=True → _drag에서 preview 사각형, _release에서 위젯 생성

        elif self._tool == "crop":
            # crop_rect가 없으면 전체 이미지 크기로 초기화
            if self._base_image is not None and self._crop_rect is None:
                iw, ih = self._base_image.size
                self._crop_rect = (0, 0, iw, ih)
                self._draw_crop_overlay()
            handle = self._get_crop_handle(x, y)
            self._crop_handle = handle
            if handle is None:
                self._drawing = False  # 핸들 밖 클릭 → 드래그 무시

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
        ox, oy = self._img_x, self._img_y

        def csx(v: float) -> int:
            return int(v * zoom) + ox

        def csy(v: float) -> int:
            return int(v * zoom) + oy

        if self._tool == "pen":
            # 단일 폴리라인 업데이트 → 반응성 향상
            self._pen_points.append((x, y))
            pts = self._pen_points
            if len(pts) >= 2:
                flat = []
                for pt in pts:
                    flat.extend([csx(pt[0]), csy(pt[1])])
                lw = max(1, int(w * zoom))
                if self._pen_preview_items:
                    self.canvas.coords(self._pen_preview_items[0], flat)
                else:
                    item = self.canvas.create_line(
                        flat, fill=color, width=lw,
                        smooth=False, capstyle=tk.ROUND, joinstyle=tk.ROUND,
                    )
                    self._pen_preview_items.append(item)

        elif self._tool == "highlighter":
            # 형광펜도 단일 폴리라인
            self._pen_points.append((x, y))
            pts = self._pen_points
            if len(pts) >= 2:
                flat = []
                for pt in pts:
                    flat.extend([csx(pt[0]), csy(pt[1])])
                lw = max(1, int(w * zoom))
                if self._pen_preview_items:
                    self.canvas.coords(self._pen_preview_items[0], flat)
                else:
                    item = self.canvas.create_line(
                        flat, fill=color, width=lw,
                        smooth=False, capstyle=tk.ROUND, joinstyle=tk.ROUND,
                        stipple="gray50",
                    )
                    self._pen_preview_items.append(item)

        elif self._tool == "shape":
            self._remove_preview()
            sub = self._sub_tool
            sx0, sy0, sx1, sy1 = csx(x0), csy(y0), csx(x), csy(y)
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

        elif self._tool == "mosaic":
            # 실시간 모자이크 미리보기
            self._remove_preview()
            x_min, x_max = sorted([int(x0), int(x)])
            y_min, y_max = sorted([int(y0), int(y)])
            shown = False
            if x_max > x_min and y_max > y_min and self._base_image:
                try:
                    region = self._base_image.crop((x_min, y_min, x_max, y_max))
                    block = max(2, w)
                    small = region.resize(
                        (max(1, region.width // block), max(1, region.height // block)),
                        Image.NEAREST,
                    )
                    mosaic = small.resize(region.size, Image.NEAREST)
                    cw = max(1, int((x_max - x_min) * zoom))
                    ch = max(1, int((y_max - y_min) * zoom))
                    self._mosaic_preview_tk = ImageTk.PhotoImage(
                        mosaic.resize((cw, ch), Image.NEAREST)
                    )
                    self._preview_item = self.canvas.create_image(
                        csx(x_min), csy(y_min), anchor=tk.NW,
                        image=self._mosaic_preview_tk,
                    )
                    shown = True
                except Exception:
                    pass
            if not shown:
                sx0, sy0, sx1, sy1 = csx(x0), csy(y0), csx(x), csy(y)
                self._preview_item = self.canvas.create_rectangle(
                    sx0, sy0, sx1, sy1, outline=color, width=2, dash=(4, 4),
                )

        elif self._tool == "crop":
            if self._crop_handle is None or self._crop_rect is None or self._base_image is None:
                return
            rx0, ry0, rx1, ry1 = self._crop_rect
            iw, ih = self._base_image.size
            MIN = 10
            h = self._crop_handle
            if 'n' in h:
                ry0 = float(max(0, min(y, ry1 - MIN)))
            if 's' in h:
                ry1 = float(min(ih, max(y, ry0 + MIN)))
            if 'w' in h:
                rx0 = float(max(0, min(x, rx1 - MIN)))
            if 'e' in h:
                rx1 = float(min(iw, max(x, rx0 + MIN)))
            self._crop_rect = (rx0, ry0, rx1, ry1)
            self._draw_crop_overlay()

        elif self._tool == "text":
            self._remove_preview()
            sx0, sy0, sx1, sy1 = csx(x0), csy(y0), csx(x), csy(y)
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
                "block_size": max(2, w),
            }, tag))

        elif self._tool == "crop":
            # 핸들 드래그 완료 — 오버레이 유지, Enter로 확정
            self._crop_handle = None
            return

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
        cx0 = int(min(x0, x1) * zoom) + self._img_x
        cy0 = int(min(y0, y1) * zoom) + self._img_y
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
        # 19회차 item 4: Ctrl+Enter로 확정, 일반 Enter는 줄바꿈 유지
        text_widget.bind("<Control-Return>", lambda e: self._finish_text_input())
        # FocusOut: 자동 확정
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
        self._reset_redo_stack.clear()

    def _undo(self) -> None:
        if self._ops:
            op = self._ops.pop()
            self._redo_stack.append(op)
            self._reset_redo_stack.clear()
            self._refresh_canvas()
        elif self._reset_stack:
            # 초기화 롤백 — 이전 상태 복원
            self._reset_redo_stack.append((self._ops.copy(), self._redo_stack.copy()))
            self._ops, self._redo_stack = self._reset_stack.pop()
            self._refresh_canvas()
        elif self._base_image_stack:
            # 자르기 롤백 — redo를 위해 현재 base 저장
            self._base_image_redo_stack.append(self._base_image.copy())
            self._base_image = self._base_image_stack.pop()
            self._ops = []
            self._redo_stack = []
            self._refresh_canvas()
            self._update_status()
        elif self._del_undo_stack:
            # 이미지 삭제 롤백 — 원본 이미지를 원래 위치에 복원
            try:
                del_idx, del_img, ops_entry = self._del_undo_stack.pop()
                import history as hist_module
                hist = hist_module.get_history()
                hist.insert(del_idx, del_img)
                # ops_store 키 재조정 (del_idx 이상은 +1)
                new_store: dict = {}
                for k, v in self._ops_store.items():
                    new_store[k + 1 if k >= del_idx else k] = v
                if ops_entry is not None:
                    new_store[del_idx] = ops_entry
                self._ops_store = new_store
                self._history = _HistoryAdapter(hist)
                if hasattr(self, "_history_panel"):
                    self._history_panel._history = self._history
                    self._history_panel.refresh()
                self._base_image = None
                self.load_image(del_idx)
                self._flash(f"삭제 취소: 이미지 #{del_idx + 1} 복원")
            except Exception as e:
                print(f"삭제 undo 오류: {e}")

    def _redo(self) -> None:
        if self._redo_stack:
            op = self._redo_stack.pop()
            self._ops.append(op)
            self._reset_redo_stack.clear()
            self._refresh_canvas()
        elif self._reset_redo_stack:
            # 초기화 다시실행
            self._reset_stack.append((self._ops.copy(), self._redo_stack.copy()))
            self._ops, self._redo_stack = self._reset_redo_stack.pop()
            self._refresh_canvas()
        elif self._base_image_redo_stack:
            # 자르기 다시실행
            self._base_image_stack.append(self._base_image.copy())
            self._base_image = self._base_image_redo_stack.pop()
            self._ops = []
            self._redo_stack = []
            self._refresh_canvas()
            self._update_status()

    def _reset(self) -> None:
        """편집(드로잉) + 자르기를 포함해 최초 원본 이미지로 완전 초기화합니다."""
        has_changes = bool(self._ops) or bool(self._base_image_stack)
        if has_changes:
            self._reset_stack.append((self._ops.copy(), self._redo_stack.copy()))
            self._reset_redo_stack.clear()
            self._ops = []
            self._redo_stack = []
            # 최초 원본으로 복귀 (자르기 포함)
            if self._current_idx >= 0:
                try:
                    original = self._history[self._current_idx]
                    self._base_image = original.convert("RGBA")
                except Exception:
                    pass
            self._base_image_stack = []
            self._base_image_redo_stack = []
            self._refresh_canvas()
            self._update_status()
        self._reset_pan()

    def _reset_pan(self) -> None:
        """캔버스 팬 위치를 이미지 중앙으로 되돌립니다."""
        if self._base_image is None:
            return
        PAD = 500
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw = max(1, int(self._base_image.width * self._zoom))
        ih = max(1, int(self._base_image.height * self._zoom))
        total_w = max(iw + 2 * self._img_x, cw)
        total_h = max(ih + 2 * self._img_y, ch)
        sr_w = total_w + 2 * PAD
        sr_h = total_h + 2 * PAD
        if sr_w > 0:
            self.canvas.xview_moveto(PAD / sr_w)
        if sr_h > 0:
            self.canvas.yview_moveto(PAD / sr_h)

    # ──────────────────────────────────────────────
    # 저장 / 복사
    # ──────────────────────────────────────────────

    def _get_final_image(self) -> Image.Image:
        """최종 이미지를 반환합니다 (항상 원본 품질 PNG)."""
        return self._get_rendered()

    def _save(self) -> None:
        img = self._get_final_image()
        ftypes = [("PNG 이미지", "*.png"), ("JPEG 이미지", "*.jpg"), ("모든 파일", "*.*")]
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=ftypes, title="이미지 저장"
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

    def _prev_image(self) -> None:
        if self._current_idx > 0:
            self.load_image(self._current_idx - 1)

    def _next_image(self) -> None:
        if self._current_idx < len(self._history) - 1:
            self.load_image(self._current_idx + 1)

    def _on_history_select(self, idx: int) -> None:
        """패널에서 썸네일을 클릭했을 때."""
        self.load_image(idx)

    # ──────────────────────────────────────────────
    # 새 메서드: ESC / 패닝 / 자르기 2단계 / 삭제
    # ──────────────────────────────────────────────

    def _on_escape(self) -> None:
        """ESC: 자르기 선택 초기화 / 텍스트 취소 / 창 닫기."""
        if self._tool == "crop" and self._crop_rect is not None and self._base_image is not None:
            # 자르기 영역을 전체 이미지로 초기화
            iw, ih = self._base_image.size
            self._crop_rect = (0, 0, iw, ih)
            self._draw_crop_overlay()
        elif self._text_widget is not None:
            self._cancel_text_input()
        else:
            self.root.destroy()

    # ──────────────────────────────────────────────
    # 커서 아이콘 (펜/형광펜/지우개 PNG + 틴팅)
    # ──────────────────────────────────────────────

    def _hide_all_cursor_items(self) -> None:
        """모든 커스텀 커서 캔버스 아이템을 숨깁니다."""
        try:
            self.canvas.itemconfig(self._tool_cursor_item, state=tk.HIDDEN)
        except Exception:
            pass
        for item in getattr(self, '_custom_cur_items', []):
            try:
                self.canvas.itemconfig(item, state=tk.HIDDEN)
            except Exception:
                pass

    def _on_pan_start(self, event) -> None:
        """우클릭 드래그 시작: 캔버스 패닝 시작점 기록."""
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.config(cursor="fleur")
        self._hide_all_cursor_items()

    def _on_pan_motion(self, event) -> None:
        """우클릭 드래그: 캔버스 X/Y 패닝."""
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_pan_end(self, event) -> None:
        """우클릭 드래그 종료: 커서 복원."""
        self.canvas.config(cursor=self._tool_cursor())

    def _on_canvas_leave(self, event) -> None:
        """마우스가 캔버스를 벗어날 때 커스텀 커서 아이템 숨김."""
        self._hide_all_cursor_items()

    def _tool_cursor(self) -> str:
        """현재 도구에 맞는 OS 커서를 반환합니다.
        text·mosaic·shape → 십자가, pen·hl·eraser·crop → 기본 화살표."""
        if self._tool in ("text", "mosaic", "shape"):
            return "crosshair"
        return ""  # pen·hl·eraser·crop·기타 → 기본 화살표

    # ──────────────────────────────────────────────
    # 19회차 item 3: 자르기 패널 (W/H 입력)
    # ──────────────────────────────────────────────

    def _build_crop_panel(self) -> None:
        """캔버스 위에 자르기 W/H 패널을 미리 생성합니다 (초기 숨김)."""
        panel = tk.Frame(self.canvas, bg="#2b2b2b", padx=4, pady=3,
                         relief=tk.RAISED, bd=1)
        self._crop_panel = panel
        self._crop_var_w = tk.IntVar(value=0)
        self._crop_var_h = tk.IntVar(value=0)

        inner = tk.Frame(panel, bg="#2b2b2b")
        inner.pack()

        label_s = {"bg": "#2b2b2b", "fg": "#cccccc", "font": ("맑은 고딕", 9)}
        entry_s = {"width": 5, "font": ("맑은 고딕", 9),
                   "bg": "#3a3a3a", "fg": "white",
                   "insertbackground": "white", "relief": tk.FLAT}

        tk.Label(inner, text="W:", **label_s).pack(side=tk.LEFT)
        tk.Entry(inner, textvariable=self._crop_var_w, **entry_s).pack(
            side=tk.LEFT, padx=(2, 6))
        tk.Label(inner, text="H:", **label_s).pack(side=tk.LEFT)
        tk.Entry(inner, textvariable=self._crop_var_h, **entry_s).pack(
            side=tk.LEFT, padx=(2, 6))
        tk.Button(inner, text="자르기", bg="#0078D4", fg="white",
                  font=("맑은 고딕", 9, "bold"), relief=tk.FLAT, padx=6,
                  command=self._confirm_crop).pack(side=tk.LEFT)

        self._crop_var_w.trace_add("write", self._on_crop_panel_change)
        self._crop_var_h.trace_add("write", self._on_crop_panel_change)

        self._crop_panel_id = self.canvas.create_window(
            0, 0, window=panel, anchor=tk.NW, state=tk.HIDDEN)

    def _on_crop_panel_change(self, *args) -> None:
        """패널 W/H 입력 시 crop_rect 갱신."""
        if self._crop_panel_syncing or self._crop_rect is None or self._base_image is None:
            return
        try:
            w = self._crop_var_w.get()
            h = self._crop_var_h.get()
        except (ValueError, tk.TclError):
            return
        w = max(10, w)
        h = max(10, h)
        iw, ih = self._base_image.size
        x0, y0, _, _ = self._crop_rect
        x1 = min(x0 + w, iw)
        y1 = min(y0 + h, ih)
        self._crop_rect = (x0, y0, x1, y1)
        self._draw_crop_overlay()

    def _update_crop_panel(self) -> None:
        """crop_rect 변경 시 패널 값과 위치를 갱신합니다."""
        if self._crop_panel_id is None:
            return
        if self._crop_rect is None or self._base_image is None:
            self.canvas.itemconfig(self._crop_panel_id, state=tk.HIDDEN)
            return
        x0, y0, x1, y1 = self._crop_rect
        w = max(1, int(round(x1 - x0)))
        h = max(1, int(round(y1 - y0)))

        self._crop_panel_syncing = True
        try:
            self._crop_var_w.set(w)
            self._crop_var_h.set(h)
        finally:
            self._crop_panel_syncing = False

        # 패널 위치: 자르기 영역 우측 하단
        zoom = self._zoom
        ox, oy = self._img_x, self._img_y
        px = int(x1 * zoom) + ox
        py = int(y1 * zoom) + oy + 4

        self._crop_panel.update_idletasks()
        pw = self._crop_panel.winfo_reqwidth() or 200
        self.canvas.coords(self._crop_panel_id, px - pw, py)
        self.canvas.itemconfig(self._crop_panel_id, state=tk.NORMAL)
        self.canvas.tag_raise(self._crop_panel_id)

    # ──────────────────────────────────────────────
    # 19회차 item 7: 도구 크기/색상 인디케이터
    # ──────────────────────────────────────────────

    def _update_tool_cursor(self, x: int, y: int) -> None:
        """모든 도구가 OS 커서를 사용하므로 캔버스 커서 아이템만 숨깁니다."""
        self._hide_all_cursor_items()

    # 자르기 커서 매핑 (16회차 item 1)
    _CROP_CURSOR_MAP = {
        "nw": "size_nw_se", "se": "size_nw_se",
        "ne": "size_ne_sw", "sw": "size_ne_sw",
        "n":  "sb_v_double_arrow", "s": "sb_v_double_arrow",
        "e":  "sb_h_double_arrow", "w": "sb_h_double_arrow",
    }

    def _on_canvas_motion(self, event) -> None:
        """마우스 이동 시 커서 및 도구 인디케이터 갱신."""
        # 19회차 item 9: 우클릭 패닝 중이면 커서/인디케이터 건드리지 않음
        if event.state & 0x400:  # Button-3 held
            return

        # 자르기 도구 핸들 커서
        if self._tool == "crop" and self._crop_rect is not None and self._base_image is not None:
            cx = self.canvas.canvasx(event.x)
            cy = self.canvas.canvasy(event.y)
            ix = (cx - self._img_x) / self._zoom
            iy = (cy - self._img_y) / self._zoom
            handle = self._get_crop_handle(ix, iy)
            # 핸들 위: resize 커서 / 핸들 없음: 기본 화살표
            cursor = self._CROP_CURSOR_MAP.get(handle, "crosshair") if handle else ""
            self.canvas.config(cursor=cursor)
        else:
            self.canvas.config(cursor=self._tool_cursor())

        # 19회차 item 7: 도구 크기/색상 인디케이터
        self._update_tool_cursor(event.x, event.y)

    def _confirm_crop(self) -> None:
        """Enter: 자르기 액자 영역으로 이미지를 자릅니다 (Ctrl+Z로 롤백 가능)."""
        if self._tool != "crop" or self._crop_rect is None or self._base_image is None:
            return
        x0, y0, x1, y1 = (int(v) for v in self._crop_rect)
        if x1 <= x0 or y1 <= y0:
            return
        rendered = self._get_rendered()
        self._base_image_stack.append(self._base_image.copy())
        self._base_image_redo_stack.clear()  # 새 자르기 → redo 스택 초기화
        self._base_image = rendered.crop((x0, y0, x1, y1)).convert("RGBA")
        self._ops = []
        self._redo_stack = []
        self._reset_stack = []
        self._reset_redo_stack = []
        # 자른 이미지 크기로 crop_rect 재초기화
        iw, ih = self._base_image.size
        self._crop_rect = (0, 0, iw, ih)
        self._clear_crop_overlay()
        self._refresh_canvas()
        self._update_status()

    def _on_delete_key(self, event) -> None:
        """Delete 키 핸들러: 텍스트 입력 위젯에 포커스가 없을 때만 이미지 삭제."""
        focus = self.root.focus_get()
        if isinstance(focus, (tk.Entry, tk.Text)):
            return  # 텍스트 입력 중 → 기본 동작 유지
        self._delete()

    def _delete(self, idx: Optional[int] = None) -> None:
        """현재(또는 지정) 이미지를 히스토리에서 삭제합니다. Ctrl+Z로 복원 가능합니다."""
        if idx is None:
            idx = self._current_idx
        if idx < 0:
            return
        try:
            import history as hist_module
            hist = hist_module.get_history()
            if hist.count() == 0:
                return
            # 삭제 전 undo 스택에 저장
            img_backup = self._history[idx]
            ops_entry  = self._ops_store.get(idx)
            self._del_undo_stack.append((idx, img_backup, ops_entry))
            hist.remove(idx)
            # ops_store 키 재조정
            new_store = {}
            for k, v in self._ops_store.items():
                if k < idx:
                    new_store[k] = v
                elif k > idx:
                    new_store[k - 1] = v
            self._ops_store = new_store
            self._history = _HistoryAdapter(hist)
            # 히스토리 패널 갱신
            if hasattr(self, "_history_panel"):
                self._history_panel._history = self._history
                self._history_panel.refresh()
            self._base_image = None  # 전환 전 저장 방지
            if hist.count() == 0:
                # 모든 이미지 삭제 → 빈 상태
                self.load_image(-1)
            else:
                self.load_image(min(idx, hist.count() - 1))
        except Exception as e:
            messagebox.showerror("삭제 오류", str(e))

    def _copy_image_at(self, idx: int) -> None:
        """히스토리 패널 우클릭 - 복사."""
        try:
            img = self._history[idx]
            if copy_to_clipboard(img):
                self._flash("클립보드에 복사됨!")
            else:
                messagebox.showwarning("복사 실패", "클립보드 복사에 실패했습니다.")
        except Exception as e:
            messagebox.showerror("복사 오류", str(e))

    def _save_image_at(self, idx: int) -> None:
        """히스토리 패널 우클릭 - 저장."""
        try:
            img = self._history[idx]
            ftypes = [("PNG 이미지", "*.png"), ("JPEG 이미지", "*.jpg"), ("모든 파일", "*.*")]
            path = filedialog.asksaveasfilename(
                defaultextension=".png", filetypes=ftypes, title="이미지 저장"
            )
            if path:
                img.save(path)
                self._flash("저장 완료: " + path)
        except Exception as e:
            messagebox.showerror("저장 오류", str(e))

    def _delete_image_at(self, idx: int) -> None:
        """히스토리 패널 우클릭 - 삭제."""
        self._delete(idx)

    # ──────────────────────────────────────────────
    # 퍼블릭 인터페이스
    # ──────────────────────────────────────────────

    def show(self) -> None:
        """창을 표시합니다. master가 없으면 mainloop를 실행합니다."""
        w, h = 1440, 810
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.root.geometry(f"{w}x{h}+{x}+{y}")

        if not isinstance(self.root, tk.Toplevel):
            self.root.mainloop()
        else:
            self.root.deiconify()


# ──────────────────────────────────────────────────────────────
# 모듈 레벨 진입점 (main.py에서 호출)
# ──────────────────────────────────────────────────────────────

def open_editor(image, master: Optional[tk.Widget] = None,
                history_idx: int = 0, history=None) -> EditorWindow:
    """편집기 창을 열고 EditorWindow 인스턴스를 반환합니다.

    Parameters
    ----------
    image : PIL.Image | None
        표시할 이미지. None이면 빈 상태로 엽니다.
    master : tk.Widget, optional
        부모 tkinter 위젯.
    history_idx : int
        history에서 초기 선택할 인덱스. -1이면 빈 상태.
    history : CaptureHistory | list, optional
        캡처 히스토리 저장소. None이면 전역 히스토리를 사용합니다.
    """
    if history is None:
        try:
            import history as hist_module
            history = hist_module.get_history()
        except Exception:
            history = [image] if image is not None else []
            history_idx = 0 if image is not None else -1

    # 빈 히스토리면 idx=-1로 빈 상태 표시
    hlen = history.count() if hasattr(history, 'count') else len(history)
    if hlen == 0:
        history_idx = -1

    editor = EditorWindow(history=history, initial_idx=history_idx, master=master)
    editor.show()
    return editor
