"""
캡처 이미지 히스토리 관리 모듈
최대 20개의 캡처 이미지를 메모리에 보관합니다.
"""
from __future__ import annotations

from typing import Optional, Tuple
from PIL import Image, ImageTk

MAX_HISTORY = 20
DEFAULT_THUMB_SIZE: Tuple[int, int] = (80, 60)


class CaptureHistory:
    def __init__(self, max_count: int = MAX_HISTORY):
        self._max_count = max_count
        self._images: list[Image.Image] = []
        # 썸네일 캐시: {(idx, size): ImageTk.PhotoImage}
        self._thumb_cache: dict[tuple, ImageTk.PhotoImage] = {}

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def add(self, image: Image.Image) -> int:
        """이미지를 히스토리에 추가하고 해당 인덱스를 반환합니다."""
        if len(self._images) >= self._max_count:
            # 가장 오래된 항목 제거 및 썸네일 캐시 정리
            self._evict_oldest()

        self._images.append(image.copy())
        idx = len(self._images) - 1
        return idx

    def get(self, idx: int) -> Image.Image:
        """인덱스에 해당하는 이미지를 반환합니다."""
        if idx < 0 or idx >= len(self._images):
            raise IndexError(f"히스토리 인덱스 범위 초과: {idx}")
        return self._images[idx]

    def get_thumbnail(
        self,
        idx: int,
        size: Tuple[int, int] = DEFAULT_THUMB_SIZE,
    ) -> ImageTk.PhotoImage:
        """인덱스에 해당하는 썸네일 ImageTk.PhotoImage를 반환합니다.
        이미 생성된 썸네일은 캐시에서 반환합니다.
        """
        cache_key = (idx, size)
        if cache_key in self._thumb_cache:
            return self._thumb_cache[cache_key]

        img = self.get(idx)
        thumb = img.copy()
        thumb.thumbnail(size, Image.LANCZOS)

        # 썸네일을 정확한 크기의 빈 이미지 위에 중앙 배치
        tw, th = size
        canvas = Image.new("RGBA", (tw, th), (200, 200, 200, 255))
        offset_x = (tw - thumb.width) // 2
        offset_y = (th - thumb.height) // 2
        if thumb.mode == "RGBA":
            canvas.paste(thumb, (offset_x, offset_y), thumb)
        else:
            canvas.paste(thumb, (offset_x, offset_y))

        tk_img = ImageTk.PhotoImage(canvas)
        self._thumb_cache[cache_key] = tk_img
        return tk_img

    def count(self) -> int:
        """현재 저장된 이미지 수를 반환합니다."""
        return len(self._images)

    def insert(self, idx: int, image: Image.Image) -> None:
        """지정 인덱스에 이미지를 삽입하고 썸네일 캐시를 재조정합니다."""
        if idx < 0 or idx > len(self._images):
            raise IndexError(f"삽입 인덱스 범위 초과: {idx}")
        self._images.insert(idx, image.copy())
        new_cache: dict[tuple, ImageTk.PhotoImage] = {}
        for (old_idx, size), tk_img in self._thumb_cache.items():
            if old_idx < idx:
                new_cache[(old_idx, size)] = tk_img
            else:
                new_cache[(old_idx + 1, size)] = tk_img
        self._thumb_cache = new_cache

    def remove(self, idx: int) -> None:
        """인덱스에 해당하는 이미지를 삭제하고 캐시를 재조정합니다."""
        if idx < 0 or idx >= len(self._images):
            raise IndexError(f"히스토리 인덱스 범위 초과: {idx}")
        self._images.pop(idx)
        new_cache: dict[tuple, ImageTk.PhotoImage] = {}
        for (old_idx, size), tk_img in self._thumb_cache.items():
            if old_idx < idx:
                new_cache[(old_idx, size)] = tk_img
            elif old_idx > idx:
                new_cache[(old_idx - 1, size)] = tk_img
        self._thumb_cache = new_cache

    def clear(self) -> None:
        """모든 히스토리와 캐시를 초기화합니다."""
        self._images.clear()
        self._thumb_cache.clear()

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    def _evict_oldest(self) -> None:
        """가장 오래된 이미지를 제거하고 인덱스를 재조정합니다."""
        if not self._images:
            return
        self._images.pop(0)

        # 캐시의 모든 키를 재조정 (인덱스가 1씩 줄어듦)
        new_cache: dict[tuple, ImageTk.PhotoImage] = {}
        for (old_idx, size), tk_img in self._thumb_cache.items():
            new_idx = old_idx - 1
            if new_idx >= 0:
                new_cache[(new_idx, size)] = tk_img
        self._thumb_cache = new_cache

    def invalidate_thumbnail(self, idx: int) -> None:
        """특정 인덱스의 썸네일 캐시를 무효화합니다."""
        keys_to_delete = [k for k in self._thumb_cache if k[0] == idx]
        for key in keys_to_delete:
            del self._thumb_cache[key]


# 모듈 레벨 싱글턴
_history = CaptureHistory()


def get_history() -> CaptureHistory:
    """전역 히스토리 인스턴스를 반환합니다."""
    return _history
