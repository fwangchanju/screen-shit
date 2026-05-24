"""
좌측 캡처 목록 패널 (PPT 슬라이드 패널 스타일).
썸네일 목록을 최신 순으로 표시. 클릭 시 on_select_callback(idx) 호출.
Ctrl+휠로 썸네일 크기 조절 가능.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional

from PIL import Image, ImageTk


PANEL_W     = 180
THUMB_W     = 156
THUMB_H     = 117   # 4:3 비율
BG_COLOR    = "#2D2D2D"
ITEM_BG     = "#3C3C3C"
SEL_BG      = "#0078D4"
HOVER_BG    = "#4A4A4A"
TEXT_COLOR  = "#CCCCCC"
SEL_TEXT    = "#FFFFFF"

_MIN_THUMB = 80
_MAX_THUMB = 220


class HistoryPanel:
    """좌측 캡처 목록 패널.

    Parameters
    ----------
    parent_frame : tk.Widget
        이 패널을 붙일 부모 위젯
    history : list
        캡처 이미지 목록
    on_select_callback : Callable[[int], None]
        썸네일 클릭 시 호출. 인자는 원본 history 인덱스.
    on_copy_callback : Callable[[int], None], optional
        우클릭 메뉴 '복사' 선택 시 호출.
    on_save_callback : Callable[[int], None], optional
        우클릭 메뉴 '저장' 선택 시 호출.
    on_delete_callback : Callable[[int], None], optional
        우클릭 메뉴 '삭제' 선택 시 호출.
    """

    def __init__(self, parent_frame: tk.Widget,
                 history: list,
                 on_select_callback: Callable[[int], None],
                 on_copy_callback: Optional[Callable[[int], None]] = None,
                 on_save_callback: Optional[Callable[[int], None]] = None,
                 on_delete_callback: Optional[Callable[[int], None]] = None) -> None:
        self._history = history
        self._on_select = on_select_callback
        self._on_copy = on_copy_callback
        self._on_save = on_save_callback
        self._on_delete = on_delete_callback
        self._selected_idx: Optional[int] = None
        self._thumb_w = THUMB_W
        self._thumb_h = THUMB_H

        self._thumb_refs: List[Optional[ImageTk.PhotoImage]] = []
        self._build(parent_frame)

    # ──────────────────────────────────────────────
    # 내부 구성
    # ──────────────────────────────────────────────

    def _build(self, parent: tk.Widget) -> None:
        # 외부 프레임 — 부모(PanedWindow 호스트)를 꽉 채움
        outer = tk.Frame(parent, bg=BG_COLOR)
        outer.pack(fill=tk.BOTH, expand=True)
        self._outer = outer

        # 헤더
        hdr = tk.Frame(outer, bg=BG_COLOR)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="캡처 목록", bg=BG_COLOR, fg="#AAAAAA",
                 font=("맑은 고딕", 9, "bold")).pack(side=tk.LEFT, padx=8, pady=6)

        ttk.Separator(outer, orient=tk.HORIZONTAL).pack(fill=tk.X)

        # 스크롤 가능한 영역
        scroll_frame = tk.Frame(outer, bg=BG_COLOR)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(scroll_frame, bg=BG_COLOR, highlightthickness=0)
        scrollbar = ttk.Scrollbar(scroll_frame, orient=tk.VERTICAL,
                                  command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._canvas = canvas

        inner = tk.Frame(canvas, bg=BG_COLOR)
        self._inner_frame = inner
        self._canvas_window = canvas.create_window((0, 0), window=inner, anchor=tk.NW)

        inner.bind("<Configure>", self._on_frame_configure)
        canvas.bind("<Configure>", self._on_canvas_configure)
        canvas.bind("<MouseWheel>", self._on_mousewheel)
        inner.bind("<MouseWheel>", self._on_mousewheel)

        self._item_frames: List[tk.Frame] = []
        self._populate()

    def _on_frame_configure(self, event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event=None) -> None:
        self._canvas.itemconfig(self._canvas_window,
                                width=self._canvas.winfo_width())

    def _on_mousewheel(self, event) -> None:
        if event.state & 0x4:  # Ctrl+휠: 썸네일 크기 조절
            delta = 20 if event.delta > 0 else -20
            self._thumb_w = max(_MIN_THUMB, min(_MAX_THUMB, self._thumb_w + delta))
            self._thumb_h = int(self._thumb_w * 0.75)
            self._populate()
        else:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ──────────────────────────────────────────────
    # 썸네일 생성
    # ──────────────────────────────────────────────

    def _make_thumb(self, image: Image.Image) -> ImageTk.PhotoImage:
        thumb = image.copy()
        thumb.thumbnail((self._thumb_w, self._thumb_h), Image.LANCZOS)
        bg = Image.new("RGB", (self._thumb_w, self._thumb_h), (44, 44, 44))
        ox = (self._thumb_w - thumb.width) // 2
        oy = (self._thumb_h - thumb.height) // 2
        if thumb.mode == "RGBA":
            bg.paste(thumb, (ox, oy), thumb)
        else:
            bg.paste(thumb.convert("RGB"), (ox, oy))
        return ImageTk.PhotoImage(bg)

    def _get_image(self, raw) -> Image.Image:
        if isinstance(raw, Image.Image):
            return raw
        if hasattr(raw, "image"):
            return raw.image
        if hasattr(raw, "get_image"):
            return raw.get_image()
        raise TypeError(f"알 수 없는 history 항목 타입: {type(raw)}")

    def _populate(self) -> None:
        for f in self._item_frames:
            f.destroy()
        self._item_frames.clear()
        self._thumb_refs.clear()

        n = len(self._history)
        for orig_idx in range(n - 1, -1, -1):
            raw = self._history[orig_idx]
            try:
                img = self._get_image(raw)
                photo = self._make_thumb(img)
                iw, ih = img.size
                size_text = f"{iw}×{ih}"
            except Exception:
                photo = None
                size_text = ""

            self._thumb_refs.append(photo)
            item_frame = self._create_item_frame(orig_idx, photo, size_text)
            item_frame.pack(fill=tk.X, padx=4, pady=3)
            self._item_frames.append(item_frame)

    def _create_item_frame(self, orig_idx: int,
                           photo: Optional[ImageTk.PhotoImage],
                           size_text: str) -> tk.Frame:
        is_selected = (orig_idx == self._selected_idx)
        item_bg = SEL_BG if is_selected else ITEM_BG

        outer = tk.Frame(self._inner_frame, bg=item_bg, cursor="hand2")

        # 썸네일
        if photo:
            lbl_img = tk.Label(outer, image=photo, bg=item_bg, cursor="hand2")
            lbl_img.pack(padx=4, pady=(6, 0))
        else:
            lbl_img = tk.Label(outer, text="?", bg=item_bg, width=10, height=5,
                               cursor="hand2")
            lbl_img.pack(padx=4, pady=(6, 0))

        # 하단 행: 번호(좌) + 크기(우)
        row = tk.Frame(outer, bg=item_bg)
        row.pack(fill=tk.X, padx=4, pady=(2, 5))
        tk.Label(row, text=f"#{orig_idx + 1}", bg=item_bg,
                 fg=SEL_TEXT if is_selected else TEXT_COLOR,
                 font=("맑은 고딕", 8)).pack(side=tk.LEFT)
        if size_text:
            tk.Label(row, text=size_text, bg=item_bg,
                     fg=SEL_TEXT if is_selected else "#888888",
                     font=("맑은 고딕", 7)).pack(side=tk.RIGHT)

        def _set_bg(w, color):
            try:
                w.config(bg=color)
                for child in w.winfo_children():
                    _set_bg(child, color)
            except Exception:
                pass

        def on_enter(e):
            if orig_idx != self._selected_idx:
                _set_bg(outer, HOVER_BG)

        def on_leave(e):
            if orig_idx != self._selected_idx:
                _set_bg(outer, ITEM_BG)

        for widget in outer.winfo_children() + [outer]:
            widget.bind("<Button-1>", lambda e, idx=orig_idx: self._on_click(idx))
            widget.bind("<Button-3>", lambda e, idx=orig_idx: self._on_right_click(e, idx))
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.bind("<MouseWheel>", self._on_mousewheel)

        return outer

    # ──────────────────────────────────────────────
    # 퍼블릭 인터페이스
    # ──────────────────────────────────────────────

    def _on_click(self, orig_idx: int) -> None:
        self._selected_idx = orig_idx
        self._refresh_selection()
        self._on_select(orig_idx)

    def _on_right_click(self, event, orig_idx: int) -> None:
        menu = tk.Menu(self._outer, tearoff=0)
        if self._on_copy:
            menu.add_command(label="복사", command=lambda: self._on_copy(orig_idx))
        if self._on_save:
            menu.add_command(label="저장", command=lambda: self._on_save(orig_idx))
        if self._on_delete:
            menu.add_command(label="삭제", command=lambda: self._on_delete(orig_idx))
        if menu.index(tk.END) is not None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

    def _refresh_selection(self) -> None:
        self._populate()

    def set_selected(self, idx: int) -> None:
        self._selected_idx = idx
        self._refresh_selection()
        # 18회차 item 10: 선택 항목으로 자동 스크롤
        self._canvas.after(10, self._scroll_to_selected)

    def _scroll_to_selected(self) -> None:
        """선택된 항목이 뷰포트에 보이도록 스크롤합니다."""
        if self._selected_idx is None or self._selected_idx < 0:
            return
        n = len(self._history)
        if n == 0 or not self._item_frames:
            return
        # _item_frames[0] = 최신 (orig_idx = n-1), 역순 배치
        display_idx = n - 1 - self._selected_idx
        if display_idx < 0 or display_idx >= len(self._item_frames):
            return
        self._canvas.update_idletasks()
        frame = self._item_frames[display_idx]
        try:
            fy = frame.winfo_y()
            fh = frame.winfo_height()
            bbox = self._canvas.bbox("all")
            if not bbox:
                return
            total_h = bbox[3] - bbox[1]
            ch = self._canvas.winfo_height()
            if total_h <= ch:
                return  # 스크롤 불필요
            # 항목이 뷰포트 중앙에 오도록 스크롤 위치 계산
            target_y = fy - max(0, (ch - fh) // 2)
            frac = max(0.0, min(1.0, target_y / total_h))
            self._canvas.yview_moveto(frac)
        except Exception:
            pass

    def refresh(self) -> None:
        self._populate()
        if self._history:
            self._selected_idx = len(self._history) - 1
            self._refresh_selection()
        self._canvas.yview_moveto(0.0)
