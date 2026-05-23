"""
우측 캡처 목록 패널.
썸네일 목록을 최신 순으로 표시하고, 클릭 시 on_select_callback(idx)를 호출합니다.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

from PIL import Image, ImageTk


THUMB_W = 80
THUMB_H = 60
PANEL_W = 100
BORDER_COLOR = "#0078D4"
BORDER_WIDTH = 2
BG_COLOR = "#F0F0F0"
SELECTED_BG = "#D0E8FF"
NORMAL_BG = "#F0F0F0"
HOVER_BG = "#E0E0E0"


class HistoryPanel:
    """우측 캡처 목록 패널.

    Parameters
    ----------
    parent_frame : tk.Widget
        이 패널을 붙일 부모 위젯
    history : list
        캡처 이미지 목록 (PIL.Image 또는 History 객체의 images 리스트)
    on_select_callback : Callable[[int], None]
        썸네일 클릭 시 호출되는 콜백. 인자는 원본 history 인덱스.
    """

    def __init__(self, parent_frame: tk.Widget,
                 history: list,
                 on_select_callback: Callable[[int], None]) -> None:
        self._history = history
        self._on_select = on_select_callback
        self._selected_idx: Optional[int] = None

        # 썸네일 PhotoImage 참조 보관 (GC 방지)
        self._thumb_refs: List[Optional[ImageTk.PhotoImage]] = []

        self._build(parent_frame)

    # ──────────────────────────────────────────────
    # 내부 구성
    # ──────────────────────────────────────────────

    def _build(self, parent: tk.Widget) -> None:
        """패널 위젯을 생성합니다."""
        # 외부 프레임 (고정 너비)
        outer = tk.Frame(parent, width=PANEL_W, bg=BG_COLOR)
        outer.pack(side=tk.RIGHT, fill=tk.Y)
        outer.pack_propagate(False)
        self._outer = outer

        # 레이블
        tk.Label(outer, text="캡처 목록", bg=BG_COLOR,
                 font=("맑은 고딕", 8, "bold")).pack(pady=(4, 2))

        # 스크롤 가능한 영역
        scroll_frame = tk.Frame(outer, bg=BG_COLOR)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(scroll_frame, bg=BG_COLOR,
                           width=PANEL_W, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_frame, orient=tk.VERTICAL,
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._canvas = canvas

        # 썸네일을 담을 내부 프레임
        inner = tk.Frame(canvas, bg=BG_COLOR)
        self._inner_frame = inner
        self._canvas_window = canvas.create_window(
            (0, 0), window=inner, anchor=tk.NW
        )

        # 내부 프레임 크기 변경 시 scrollregion 갱신
        inner.bind("<Configure>", self._on_frame_configure)
        canvas.bind("<Configure>", self._on_canvas_configure)

        # 마우스 휠 스크롤
        canvas.bind("<MouseWheel>", self._on_mousewheel)
        inner.bind("<MouseWheel>", self._on_mousewheel)

        self._item_frames: List[tk.Frame] = []
        self._populate()

    def _on_frame_configure(self, event=None) -> None:
        self._canvas.configure(
            scrollregion=self._canvas.bbox("all")
        )

    def _on_canvas_configure(self, event=None) -> None:
        # 내부 프레임 너비를 캔버스 너비에 맞춤
        self._canvas.itemconfig(self._canvas_window,
                                width=self._canvas.winfo_width())

    def _on_mousewheel(self, event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ──────────────────────────────────────────────
    # 썸네일 생성
    # ──────────────────────────────────────────────

    def _make_thumb(self, image: Image.Image) -> ImageTk.PhotoImage:
        """PIL Image를 THUMB_W × THUMB_H 썸네일로 변환합니다."""
        thumb = image.copy()
        thumb.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
        # 배경에 맞게 패딩
        bg = Image.new("RGB", (THUMB_W, THUMB_H), (240, 240, 240))
        offset_x = (THUMB_W - thumb.width) // 2
        offset_y = (THUMB_H - thumb.height) // 2
        if thumb.mode == "RGBA":
            bg.paste(thumb, (offset_x, offset_y), thumb)
        else:
            bg.paste(thumb.convert("RGB"), (offset_x, offset_y))
        return ImageTk.PhotoImage(bg)

    def _get_image(self, raw) -> Image.Image:
        """history 항목에서 PIL.Image를 추출합니다.
        raw가 Image이면 그대로, 아니면 .image 속성을 시도합니다.
        """
        if isinstance(raw, Image.Image):
            return raw
        if hasattr(raw, "image"):
            return raw.image
        if hasattr(raw, "get_image"):
            return raw.get_image()
        raise TypeError(f"알 수 없는 history 항목 타입: {type(raw)}")

    def _populate(self) -> None:
        """현재 history 목록으로 썸네일을 생성합니다 (최신 순 = 위가 최신)."""
        # 기존 위젯 제거
        for f in self._item_frames:
            f.destroy()
        self._item_frames.clear()
        self._thumb_refs.clear()

        # 최신 순: history를 역순으로 순회
        # 원본 인덱스를 유지하기 위해 enumerate 역순
        n = len(self._history)
        for display_pos, orig_idx in enumerate(range(n - 1, -1, -1)):
            raw = self._history[orig_idx]
            try:
                img = self._get_image(raw)
                photo = self._make_thumb(img)
            except Exception:
                photo = None

            self._thumb_refs.append(photo)

            item_frame = self._create_item_frame(
                orig_idx=orig_idx,
                photo=photo,
                label_text=f"#{orig_idx + 1}",
            )
            item_frame.pack(fill=tk.X, padx=4, pady=3)
            self._item_frames.append(item_frame)

    def _create_item_frame(self, orig_idx: int,
                           photo: Optional[ImageTk.PhotoImage],
                           label_text: str) -> tk.Frame:
        """단일 썸네일 아이템 프레임을 만듭니다."""
        is_selected = (orig_idx == self._selected_idx)
        bg = SELECTED_BG if is_selected else NORMAL_BG
        bd_color = BORDER_COLOR if is_selected else BG_COLOR

        outer = tk.Frame(self._inner_frame,
                         bg=bd_color,
                         bd=BORDER_WIDTH,
                         relief=tk.FLAT if not is_selected else tk.SOLID)
        outer.configure(highlightbackground=bd_color,
                        highlightthickness=BORDER_WIDTH if is_selected else 0)

        inner = tk.Frame(outer, bg=bg)
        inner.pack(fill=tk.BOTH, expand=True)

        if photo:
            lbl_img = tk.Label(inner, image=photo, bg=bg, cursor="hand2")
            lbl_img.pack()
        else:
            lbl_img = tk.Label(inner, text="?", bg=bg, width=THUMB_W // 8,
                               height=THUMB_H // 16, cursor="hand2")
            lbl_img.pack()

        lbl_txt = tk.Label(inner, text=label_text, bg=bg,
                           font=("맑은 고딕", 7))
        lbl_txt.pack()

        # 이벤트 바인딩
        for widget in (outer, inner, lbl_img, lbl_txt):
            widget.bind("<Button-1>",
                        lambda e, idx=orig_idx: self._on_click(idx))
            widget.bind("<Enter>",
                        lambda e, fr=inner: fr.config(bg=HOVER_BG))
            widget.bind("<Leave>",
                        lambda e, fr=inner,
                               sel=(orig_idx == self._selected_idx):
                               fr.config(bg=SELECTED_BG if sel else NORMAL_BG))

        return outer

    # ──────────────────────────────────────────────
    # 퍼블릭 인터페이스
    # ──────────────────────────────────────────────

    def _on_click(self, orig_idx: int) -> None:
        """썸네일 클릭 핸들러."""
        self._selected_idx = orig_idx
        self._refresh_selection()
        self._on_select(orig_idx)

    def _refresh_selection(self) -> None:
        """선택 상태를 시각적으로 갱신합니다 (전체 재생성 없이)."""
        # 간단하게 전체 재생성
        self._populate()

    def set_selected(self, idx: int) -> None:
        """외부에서 선택 인덱스를 지정합니다."""
        self._selected_idx = idx
        self._refresh_selection()

    def refresh(self) -> None:
        """새 이미지가 추가되었을 때 목록을 갱신합니다."""
        self._populate()
        # 최신 항목을 선택 상태로
        if self._history:
            self._selected_idx = len(self._history) - 1
            self._refresh_selection()
        # 상단으로 스크롤
        self._canvas.yview_moveto(0.0)
