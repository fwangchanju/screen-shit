"""
캡쳐 이미지 편집기
펜, 사각형, 원, 화살표, 텍스트 도구로 주석을 달 수 있습니다.
Ctrl+Z 실행취소 / Ctrl+Y 다시실행 / Ctrl+C 클립보드 복사 / Ctrl+S 저장
"""
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk, ImageDraw
from io import BytesIO
import math


# ──────────────────────────────────────────────
# 클립보드 유틸
# ──────────────────────────────────────────────
def copy_image_to_clipboard(image: Image.Image):
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


# ──────────────────────────────────────────────
# 드로잉 연산 (replay-on-PIL 방식)
# ──────────────────────────────────────────────
class Operation:
    """단일 드로잉 연산. PIL 렌더링과 캔버스 아이템 태그를 같이 보관."""
    def __init__(self, kind, data, canvas_tag):
        self.kind = kind      # 'pen' | 'rect' | 'ellipse' | 'line' | 'arrow' | 'text'
        self.data = data      # 도구별 파라미터 dict
        self.canvas_tag = canvas_tag


def render_operation(draw: ImageDraw.ImageDraw, op: Operation):
    d = op.data
    color = d["color"]
    width = d.get("width", 2)

    if op.kind == "pen":
        pts = d["points"]
        if len(pts) >= 2:
            draw.line(pts, fill=color, width=width, joint="curve")

    elif op.kind == "rect":
        x0, y0, x1, y1 = d["x0"], d["y0"], d["x1"], d["y1"]
        draw.rectangle([x0, y0, x1, y1], outline=color, width=width)

    elif op.kind == "ellipse":
        x0, y0, x1, y1 = d["x0"], d["y0"], d["x1"], d["y1"]
        draw.ellipse([x0, y0, x1, y1], outline=color, width=width)

    elif op.kind == "line":
        draw.line([d["x0"], d["y0"], d["x1"], d["y1"]], fill=color, width=width)

    elif op.kind == "arrow":
        x0, y0, x1, y1 = d["x0"], d["y0"], d["x1"], d["y1"]
        draw.line([x0, y0, x1, y1], fill=color, width=width)
        _draw_arrowhead(draw, x0, y0, x1, y1, color, width)

    elif op.kind == "text":
        draw.text((d["x"], d["y"]), d["text"], fill=color)


def _draw_arrowhead(draw, x0, y0, x1, y1, color, width):
    arrow_len = max(10, width * 4)
    angle = math.atan2(y1 - y0, x1 - x0)
    spread = math.radians(25)
    for side in (spread, -spread):
        ax = x1 - arrow_len * math.cos(angle - side)
        ay = y1 - arrow_len * math.sin(angle - side)
        draw.line([x1, y1, int(ax), int(ay)], fill=color, width=width)


# ──────────────────────────────────────────────
# 편집기 창
# ──────────────────────────────────────────────
class ImageEditor:
    TOOLS = [
        ("✏", "pen",     "펜 (자유 드로잉)"),
        ("▭", "rect",    "사각형"),
        ("○", "ellipse", "원"),
        ("→", "arrow",   "화살표"),
        ("—", "line",    "직선"),
        ("T", "text",    "텍스트"),
    ]

    def __init__(self, image: Image.Image, master=None):
        self.base_image = image.convert("RGBA")
        self.ops: list[Operation] = []
        self.undo_stack: list[Operation] = []  # redo용
        self._tag_counter = 0

        self.tool = "pen"
        self.color = "#E74C3C"
        self.line_width = 3

        self._drawing = False
        self._start = (0, 0)
        self._pen_points = []
        self._preview_item = None

        self._build_window(master)

    # ── 창 구성 ──────────────────────────────────
    def _build_window(self, master):
        if master:
            self.root = tk.Toplevel(master)
        else:
            self.root = tk.Tk()

        self.root.title("캡쳐 편집기")
        self.root.resizable(True, True)

        self._build_toolbar()
        self._build_canvas()
        self._bind_keys()

        # 창 크기를 이미지에 맞게 조정
        iw, ih = self.base_image.size
        max_w = min(iw + 20, self.root.winfo_screenwidth() - 100)
        max_h = min(ih + 80, self.root.winfo_screenheight() - 100)
        self.root.geometry(f"{max_w}x{max_h}")

        self._refresh_canvas()

    def _build_toolbar(self):
        bar = ttk.Frame(self.root, padding=(4, 4))
        bar.pack(fill=tk.X)

        self._tool_btns = {}
        for icon, tool, tip in self.TOOLS:
            btn = tk.Button(
                bar, text=icon, width=3, relief=tk.FLAT,
                font=("맑은 고딕", 11),
                command=lambda t=tool: self._set_tool(t),
            )
            btn.pack(side=tk.LEFT, padx=1)
            self._tool_btns[tool] = btn

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        # 색상 버튼
        self._color_btn = tk.Button(
            bar, bg=self.color, width=3, height=1,
            relief=tk.GROOVE, command=self._pick_color,
        )
        self._color_btn.pack(side=tk.LEFT, padx=2)

        ttk.Label(bar, text="굵기").pack(side=tk.LEFT, padx=(8, 2))
        self._width_var = tk.IntVar(value=self.line_width)
        ttk.Spinbox(bar, from_=1, to=30, textvariable=self._width_var,
                    width=4, command=self._update_width).pack(side=tk.LEFT)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(bar, text="↩ 취소", command=self._undo).pack(side=tk.LEFT, padx=1)
        ttk.Button(bar, text="↪ 복원", command=self._redo).pack(side=tk.LEFT, padx=1)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)

        ttk.Button(bar, text="클립보드 복사", command=self._copy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bar, text="💾 저장",        command=self._save).pack(side=tk.RIGHT, padx=2)

        self._set_tool("pen")

    def _build_canvas(self):
        frame = ttk.Frame(self.root)
        frame.pack(fill=tk.BOTH, expand=True)

        h_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)
        v_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas = tk.Canvas(
            frame, cursor="crosshair",
            xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set,
            highlightthickness=0, bg="#E8E8E8",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        h_scroll.config(command=self.canvas.xview)
        v_scroll.config(command=self.canvas.yview)

        iw, ih = self.base_image.size
        self.canvas.config(scrollregion=(0, 0, iw, ih))

        self._bg_item = self.canvas.create_image(0, 0, anchor=tk.NW)
        self._bg_tk = None

        self.canvas.bind("<ButtonPress-1>",   self._press)
        self.canvas.bind("<B1-Motion>",        self._drag)
        self.canvas.bind("<ButtonRelease-1>",  self._release)

    def _bind_keys(self):
        self.root.bind("<Control-z>", lambda e: self._undo())
        self.root.bind("<Control-y>", lambda e: self._redo())
        self.root.bind("<Control-c>", lambda e: self._copy())
        self.root.bind("<Control-s>", lambda e: self._save())

    # ── 도구 / 색상 ─────────────────────────────
    def _set_tool(self, tool):
        self.tool = tool
        for t, btn in self._tool_btns.items():
            btn.config(
                relief=tk.SUNKEN if t == tool else tk.FLAT,
                bg="#D0E8FF" if t == tool else "SystemButtonFace",
            )

    def _pick_color(self):
        result = colorchooser.askcolor(color=self.color, title="색상 선택")
        if result and result[1]:
            self.color = result[1]
            self._color_btn.config(bg=self.color)

    def _update_width(self):
        self.line_width = self._width_var.get()

    # ── 마우스 이벤트 ────────────────────────────
    def _cv(self, event):
        """캔버스 좌표로 변환 (스크롤 반영)."""
        return (
            int(self.canvas.canvasx(event.x)),
            int(self.canvas.canvasy(event.y)),
        )

    def _press(self, event):
        x, y = self._cv(event)
        self._start = (x, y)
        self._drawing = True
        self._pen_points = [(x, y)]
        self._remove_preview()

        if self.tool == "text":
            self._drawing = False
            text = simpledialog.askstring("텍스트", "입력할 텍스트:", parent=self.root)
            if text:
                tag = self._next_tag()
                self.canvas.create_text(
                    x, y, text=text, fill=self.color,
                    font=("맑은 고딕", max(10, self.line_width * 4)),
                    anchor=tk.NW, tags=tag,
                )
                self._commit(Operation("text", {
                    "x": x, "y": y, "text": text, "color": self.color,
                }, tag))

    def _drag(self, event):
        if not self._drawing:
            return
        x, y = self._cv(event)
        x0, y0 = self._start
        self._remove_preview()
        color = self.color
        w = self.line_width

        if self.tool == "pen":
            self._pen_points.append((x, y))
            pts = self._pen_points
            if len(pts) >= 2:
                self._preview_item = self.canvas.create_line(
                    *pts[-2], *pts[-1], fill=color, width=w,
                    smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND,
                )
        elif self.tool == "rect":
            self._preview_item = self.canvas.create_rectangle(
                x0, y0, x, y, outline=color, width=w)
        elif self.tool == "ellipse":
            self._preview_item = self.canvas.create_oval(
                x0, y0, x, y, outline=color, width=w)
        elif self.tool == "line":
            self._preview_item = self.canvas.create_line(
                x0, y0, x, y, fill=color, width=w)
        elif self.tool == "arrow":
            self._preview_item = self.canvas.create_line(
                x0, y0, x, y, fill=color, width=w,
                arrow=tk.LAST, arrowshape=(max(8, w*3), max(10, w*4), max(3, w)))

    def _release(self, event):
        if not self._drawing:
            return
        self._drawing = False
        x, y = self._cv(event)
        x0, y0 = self._start
        self._remove_preview()
        color = self.color
        w = self.line_width
        tag = self._next_tag()

        if self.tool == "pen":
            pts = self._pen_points + [(x, y)]
            if len(pts) < 2:
                return
            flat = [c for pt in pts for c in pt]
            self.canvas.create_line(
                *flat, fill=color, width=w,
                smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=tag,
            )
            self._commit(Operation("pen", {"points": pts, "color": color, "width": w}, tag))

        elif self.tool == "rect":
            if abs(x - x0) < 3 and abs(y - y0) < 3:
                return
            self.canvas.create_rectangle(x0, y0, x, y, outline=color, width=w, tags=tag)
            self._commit(Operation("rect", {"x0": x0, "y0": y0, "x1": x, "y1": y,
                                            "color": color, "width": w}, tag))

        elif self.tool == "ellipse":
            if abs(x - x0) < 3 and abs(y - y0) < 3:
                return
            self.canvas.create_oval(x0, y0, x, y, outline=color, width=w, tags=tag)
            self._commit(Operation("ellipse", {"x0": x0, "y0": y0, "x1": x, "y1": y,
                                               "color": color, "width": w}, tag))

        elif self.tool == "line":
            if abs(x - x0) < 3 and abs(y - y0) < 3:
                return
            self.canvas.create_line(x0, y0, x, y, fill=color, width=w, tags=tag)
            self._commit(Operation("line", {"x0": x0, "y0": y0, "x1": x, "y1": y,
                                            "color": color, "width": w}, tag))

        elif self.tool == "arrow":
            if abs(x - x0) < 3 and abs(y - y0) < 3:
                return
            self.canvas.create_line(
                x0, y0, x, y, fill=color, width=w,
                arrow=tk.LAST, arrowshape=(max(8, w*3), max(10, w*4), max(3, w)), tags=tag,
            )
            self._commit(Operation("arrow", {"x0": x0, "y0": y0, "x1": x, "y1": y,
                                             "color": color, "width": w}, tag))

    # ── 연산 관리 ────────────────────────────────
    def _next_tag(self):
        self._tag_counter += 1
        return f"op_{self._tag_counter}"

    def _commit(self, op: Operation):
        self.ops.append(op)
        self.undo_stack.clear()  # 새 연산이 생기면 redo 스택 비우기

    def _undo(self):
        if not self.ops:
            return
        op = self.ops.pop()
        self.undo_stack.append(op)
        self.canvas.delete(op.canvas_tag)

    def _redo(self):
        if not self.undo_stack:
            return
        op = self.undo_stack.pop()
        self.ops.append(op)
        # 캔버스 아이템 재생성은 복잡하므로 전체 새로고침
        self._rebuild_canvas_items()

    def _remove_preview(self):
        if self._preview_item is not None:
            self.canvas.delete(self._preview_item)
            self._preview_item = None

    def _rebuild_canvas_items(self):
        """redo 후 캔버스 아이템을 ops 목록으로 재구성."""
        for op in self.ops:
            self.canvas.delete(op.canvas_tag)

        for op in self.ops:
            d = op.data
            color, w = d["color"], d.get("width", 2)
            tag = op.canvas_tag

            if op.kind == "pen":
                flat = [c for pt in d["points"] for c in pt]
                self.canvas.create_line(
                    *flat, fill=color, width=w,
                    smooth=True, capstyle=tk.ROUND, joinstyle=tk.ROUND, tags=tag,
                )
            elif op.kind == "rect":
                self.canvas.create_rectangle(
                    d["x0"], d["y0"], d["x1"], d["y1"],
                    outline=color, width=w, tags=tag,
                )
            elif op.kind == "ellipse":
                self.canvas.create_oval(
                    d["x0"], d["y0"], d["x1"], d["y1"],
                    outline=color, width=w, tags=tag,
                )
            elif op.kind in ("line", "arrow"):
                kwargs = dict(fill=color, width=w, tags=tag)
                if op.kind == "arrow":
                    kwargs["arrow"] = tk.LAST
                    kwargs["arrowshape"] = (max(8, w*3), max(10, w*4), max(3, w))
                self.canvas.create_line(d["x0"], d["y0"], d["x1"], d["y1"], **kwargs)
            elif op.kind == "text":
                self.canvas.create_text(
                    d["x"], d["y"], text=d["text"], fill=color,
                    font=("맑은 고딕", max(10, w * 4)), anchor=tk.NW, tags=tag,
                )

    # ── 이미지 렌더링 ────────────────────────────
    def _refresh_canvas(self):
        """배경 이미지(base + 그리기 연산)를 캔버스에 표시."""
        rendered = self._render_final()
        self._bg_tk = ImageTk.PhotoImage(rendered)
        self.canvas.itemconfig(self._bg_item, image=self._bg_tk)

    def _render_final(self) -> Image.Image:
        """base_image 위에 모든 ops를 렌더링한 PIL 이미지 반환."""
        result = self.base_image.copy().convert("RGB")
        draw = ImageDraw.Draw(result)
        for op in self.ops:
            render_operation(draw, op)
        return result

    # ── 클립보드 / 저장 ──────────────────────────
    def _copy(self):
        img = self._render_final()
        if copy_image_to_clipboard(img):
            self._flash_title("클립보드에 복사됨!")

    def _save(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG 이미지", "*.png"), ("JPEG 이미지", "*.jpg"), ("모든 파일", "*.*")],
            title="이미지 저장",
        )
        if path:
            self._render_final().save(path)
            self._flash_title(f"저장됨: {path}")

    def _flash_title(self, msg: str):
        original = self.root.title()
        self.root.title(msg)
        self.root.after(2000, lambda: self.root.title(original))

    # ── 진입점 ───────────────────────────────────
    def show(self):
        """편집기 창을 표시합니다."""
        self.root.mainloop() if not isinstance(self.root, tk.Toplevel) else None


def open_editor(image: Image.Image, master=None):
    editor = ImageEditor(image, master=master)
    if master is None:
        editor.root.mainloop()
