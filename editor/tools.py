"""
그리기 도구 모음.
Operation dataclass + PIL 렌더링 함수들.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFilter


# ──────────────────────────────────────────────────────────────
# Operation dataclass
# ──────────────────────────────────────────────────────────────

@dataclass
class Operation:
    """단일 드로잉 연산을 나타냅니다."""
    kind: str        # 'pen' | 'highlighter' | 'shape' | 'text' | 'eraser' | 'mosaic' | 'crop'
    data: dict       # 도구별 파라미터 dict
    canvas_tag: str  # tkinter 캔버스 아이템 태그


# ──────────────────────────────────────────────────────────────
# 내부 렌더링 헬퍼
# ──────────────────────────────────────────────────────────────

def _draw_arrowhead(draw: ImageDraw.ImageDraw, x0: int, y0: int,
                    x1: int, y1: int, color, width: int) -> None:
    """화살표 머리를 그립니다."""
    arrow_len = max(12, width * 4)
    angle = math.atan2(y1 - y0, x1 - x0)
    spread = math.radians(25)
    for side in (spread, -spread):
        ax = x1 - arrow_len * math.cos(angle - side)
        ay = y1 - arrow_len * math.sin(angle - side)
        draw.line([x1, y1, int(ax), int(ay)], fill=color, width=width)


def _render_pen(image: Image.Image, data: dict) -> Image.Image:
    """펜 도구: 불투명 자유 드로잉."""
    result = image.copy()
    draw = ImageDraw.Draw(result)
    pts = data["points"]
    color = data["color"]
    width = data.get("width", 3)
    if len(pts) >= 2:
        draw.line(pts, fill=color, width=width)
    elif len(pts) == 1:
        x, y = pts[0]
        r = max(1, width // 2)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
    return result


def _render_highlighter(image: Image.Image, data: dict) -> Image.Image:
    """형광펜 도구: alpha=128 반투명 드로잉."""
    pts = data["points"]
    color_hex = data.get("color", "#FFFF00")
    width = data.get("width", 12)
    alpha = data.get("alpha", 128)

    # hex -> RGB
    h = color_hex.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    rgba_color = (r, g, b, alpha)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if len(pts) >= 2:
        draw.line(pts, fill=rgba_color, width=width)
    elif len(pts) == 1:
        x, y = pts[0]
        rad = max(1, width // 2)
        draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=rgba_color)

    base = image.convert("RGBA")
    combined = Image.alpha_composite(base, overlay)
    return combined.convert("RGBA")


def _render_shape(image: Image.Image, data: dict) -> Image.Image:
    """도형 도구: 사각형 / 원 / 화살표 / 직선."""
    result = image.copy()
    draw = ImageDraw.Draw(result)
    sub = data.get("sub_tool", "rect")
    color = data["color"]
    width = data.get("width", 2)
    x0, y0, x1, y1 = data["x0"], data["y0"], data["x1"], data["y1"]
    # 좌표 정규화 (드래그 방향 무관하게 동작)
    lx, rx = min(x0, x1), max(x0, x1)
    ty, by = min(y0, y1), max(y0, y1)

    if sub == "rect":
        draw.rectangle([lx, ty, rx, by], outline=color, width=width)
    elif sub == "ellipse":
        if rx > lx and by > ty:
            draw.ellipse([lx, ty, rx, by], outline=color, width=width)
    elif sub == "line":
        draw.line([x0, y0, x1, y1], fill=color, width=width)
    elif sub == "arrow":
        draw.line([x0, y0, x1, y1], fill=color, width=width)
        _draw_arrowhead(draw, x0, y0, x1, y1, color, width)
    return result


def _render_text(image: Image.Image, data: dict) -> Image.Image:
    """텍스트 도구: 지정 위치에 텍스트 렌더링. box_width가 있으면 줄바꿈 처리."""
    result = image.copy()
    draw = ImageDraw.Draw(result)
    color = data["color"]
    x, y = data["x"], data["y"]
    text = data.get("text", "")
    font_size = data.get("font_size", 16)
    box_width = data.get("box_width", 0)

    try:
        from PIL import ImageFont
        font = ImageFont.truetype("malgun.ttf", font_size)
    except Exception:
        font = None

    if box_width > 0 and font:
        # box_width 기준으로 자동 줄바꿈
        try:
            draw.text((x, y), text, fill=color, font=font,
                      stroke_width=0)
        except TypeError:
            draw.text((x, y), text, fill=color, font=font)
    elif font:
        draw.text((x, y), text, fill=color, font=font)
    else:
        draw.text((x, y), text, fill=color)
    return result


def _render_mosaic(image: Image.Image, data: dict) -> Image.Image:
    """모자이크 도구: 드래그 영역에 픽셀화 효과 (블록 크기 15px)."""
    x0 = min(data["x0"], data["x1"])
    y0 = min(data["y0"], data["y1"])
    x1 = max(data["x0"], data["x1"])
    y1 = max(data["y0"], data["y1"])
    block = data.get("block_size", 15)

    if x1 <= x0 or y1 <= y0:
        return image.copy()

    result = image.copy()
    region = result.crop((x0, y0, x1, y1))
    rw, rh = region.size
    if rw < 1 or rh < 1:
        return result

    # 작게 줄였다가 다시 키우면 픽셀화 효과
    small_w = max(1, rw // block)
    small_h = max(1, rh // block)
    small = region.resize((small_w, small_h), Image.NEAREST)
    pixelated = small.resize((rw, rh), Image.NEAREST)
    result.paste(pixelated, (x0, y0))
    return result


def _render_crop(image: Image.Image, data: dict) -> Image.Image:
    """자르기 도구: 해당 영역만 크롭. 이미지 자체가 변경됨."""
    x0 = min(data["x0"], data["x1"])
    y0 = min(data["y0"], data["y1"])
    x1 = max(data["x0"], data["x1"])
    y1 = max(data["y0"], data["y1"])
    iw, ih = image.size
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(iw, x1)
    y1 = min(ih, y1)
    if x1 > x0 and y1 > y0:
        return image.crop((x0, y0, x1, y1))
    return image.copy()


# ──────────────────────────────────────────────────────────────
# 단일 Operation 렌더링
# ──────────────────────────────────────────────────────────────

def render_operation(image: Image.Image, op: Operation) -> Image.Image:
    """image 위에 단일 Operation을 렌더링하여 새 Image를 반환합니다."""
    if op.kind == "pen":
        return _render_pen(image, op.data)
    elif op.kind == "highlighter":
        return _render_highlighter(image, op.data)
    elif op.kind == "shape":
        return _render_shape(image, op.data)
    elif op.kind == "text":
        return _render_text(image, op.data)
    elif op.kind == "eraser":
        # 지우개는 해당 op를 ops 목록에서 제거하는 방식이므로
        # 렌더링 시에는 아무것도 하지 않음
        return image.copy()
    elif op.kind == "mosaic":
        return _render_mosaic(image, op.data)
    elif op.kind == "crop":
        return _render_crop(image, op.data)
    else:
        return image.copy()


# ──────────────────────────────────────────────────────────────
# 전체 렌더링
# ──────────────────────────────────────────────────────────────

def render_all(base_image: Image.Image, ops: List[Operation]) -> Image.Image:
    """base_image 위에 모든 ops를 순서대로 렌더링하여 최종 Image를 반환합니다.

    crop 연산이 있으면 이미지 크기 자체가 바뀝니다.
    """
    result = base_image.convert("RGBA")
    for op in ops:
        if op.kind == "eraser":
            # eraser는 op 삭제 방식이므로 render_all에서는 건너뜀
            continue
        result = render_operation(result, op)
        # 각 연산 후 RGBA 유지
        if not isinstance(result, Image.Image):
            result = base_image.copy()
        if result.mode != "RGBA":
            result = result.convert("RGBA")
    return result


# ──────────────────────────────────────────────────────────────
# 지우개: 커서 위치의 op 찾기
# ──────────────────────────────────────────────────────────────

def find_op_at(ops: List[Operation], x: int, y: int, radius: int = 10) -> Optional[int]:
    """주어진 좌표 근처에 있는 Operation의 인덱스를 반환합니다.

    가장 최근에 그려진 (인덱스가 높은) op를 우선으로 반환합니다.
    없으면 None을 반환합니다.
    """
    for i in range(len(ops) - 1, -1, -1):
        op = ops[i]
        if _op_hit_test(op, x, y, radius):
            return i
    return None


def _op_hit_test(op: Operation, x: int, y: int, radius: int) -> bool:
    """op가 (x, y) 좌표에 닿는지 확인합니다."""
    d = op.data

    if op.kind in ("pen", "highlighter"):
        pts = d.get("points", [])
        for px, py in pts:
            if abs(px - x) <= radius and abs(py - y) <= radius:
                return True
        return False

    elif op.kind == "shape":
        x0, y0 = min(d["x0"], d["x1"]), min(d["y0"], d["y1"])
        x1, y1 = max(d["x0"], d["x1"]), max(d["y0"], d["y1"])
        # 경계 근처
        return (x0 - radius <= x <= x1 + radius and
                y0 - radius <= y <= y1 + radius)

    elif op.kind == "text":
        tx, ty = d["x"], d["y"]
        return abs(tx - x) <= 50 and abs(ty - y) <= 20

    elif op.kind in ("mosaic", "crop"):
        x0, y0 = min(d["x0"], d["x1"]), min(d["y0"], d["y1"])
        x1, y1 = max(d["x0"], d["x1"]), max(d["y0"], d["y1"])
        return x0 <= x <= x1 and y0 <= y <= y1

    return False
