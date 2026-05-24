"""
설정 로드/저장 모듈
settings.json을 읽고 씁니다.
실행 파일(exe) 옆 또는 스크립트 디렉터리에 저장합니다.
"""
import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller 빌드: exe 옆에 저장
    CONFIG_PATH = Path(sys.executable).parent / "settings.json"
else:
    CONFIG_PATH = Path(__file__).parent / "settings.json"

DEFAULT_CONFIG = {
    "hotkey": "f8",
    "compress": False,
    "compress_quality": 85,
    "fixed_capture": {
        "x": 100,
        "y": 100,
        "width": 400,
        "height": 300,
        "locked": False,
    },
    "tool_sizes": {
        "pen": 3,
        "highlighter": 9,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """base 딕셔너리에 override를 재귀적으로 덮어씁니다."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load() -> dict:
    """settings.json을 로드합니다. 파일이 없으면 기본값을 반환합니다."""
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return _deep_merge(DEFAULT_CONFIG, raw)
        except Exception:
            pass
    return _deep_merge({}, DEFAULT_CONFIG)


def save(cfg: dict) -> None:
    """설정 딕셔너리를 settings.json에 저장합니다."""
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# 모듈 레벨 싱글턴 – 런타임에 공유
_config: dict = {}


def get() -> dict:
    """현재 설정을 반환합니다. 처음 호출 시 파일에서 로드합니다."""
    global _config
    if not _config:
        _config = load()
    return _config


def reload() -> dict:
    """파일에서 설정을 다시 로드합니다."""
    global _config
    _config = load()
    return _config
