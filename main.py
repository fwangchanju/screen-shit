"""
스마트 캡쳐 - 진입점
전역 단축키 등록 + 툴바 실행 + 캡처 트리거를 담당합니다.

실행: python main.py
"""
import ctypes

# DPI 인식 설정 - 반드시 최상단에서 한 번만 호출
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware v2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import sys
import threading
import tkinter as tk
from tkinter import messagebox

import config as cfg_module
import history as hist_module


def _log_warn(msg: str) -> None:
    """경고 메시지를 파일에만 기록합니다 (콘솔 출력 없음)."""
    try:
        import os
        from pathlib import Path
        log_dir = Path(os.environ.get("APPDATA", "")) / "ScreenShit"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "warn.log", "a", encoding="utf-8") as f:
            import datetime
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception:
        pass


# 캡처 진행 중 중복 실행 방지
_capture_in_progress = False

# 트레이 아이콘 전역 참조
_tray_icon = None

# 편집기 창 참조 (캡처목록 버튼용)
_editor_ref: list = []

# 툴바 창 참조
_toolbar_win_ref: list = []

# 툴바 객체 참조 (set_interactive 호출용)
_toolbar_obj_ref: list = []

# 트레이 메뉴 동적 텍스트용 가시성 상태 (18회차: 기본 True — 툴바 기본 표시)
_toolbar_visible: bool = True


def _set_toolbar_visible(visible: bool) -> None:
    global _toolbar_visible
    _toolbar_visible = visible


def _lift_toolbar_above_overlay(root: tk.Tk) -> None:
    """캡처 오버레이 위에 툴바를 표시합니다.
    원래 상태와 무관하게 항상 deiconify 후 lift (비주얼 전용).
    캡처가 이미 종료됐으면 아무것도 하지 않음."""
    if not _capture_in_progress:
        return
    try:
        win = _toolbar_win_ref[0] if _toolbar_win_ref else None
        if win:
            # 원래 상태와 무관하게 항상 오버레이 위로 표시
            win.deiconify()
            win.lift()
            win.attributes("-topmost", True)
    except Exception:
        pass


def _set_toolbar_interactive(enabled: bool) -> None:
    """캡처 중 툴바 버튼 인터랙션을 켜거나 끕니다."""
    try:
        tb_obj = _toolbar_obj_ref[0] if _toolbar_obj_ref else None
        if tb_obj:
            tb_obj.set_interactive(enabled)
    except Exception:
        pass


def trigger_capture(root: tk.Tk, mode_var: tk.StringVar) -> None:
    """단축키 또는 버튼에 의해 호출되는 캡처 트리거."""
    root.after(0, lambda: _do_capture(root, mode_var))


def _do_capture(root: tk.Tk, mode_var: tk.StringVar) -> None:
    global _capture_in_progress, _editor_hidden_for_capture, _toolbar_was_visible
    global _editor_prev_state
    if _capture_in_progress:
        return
    _capture_in_progress = True

    # 편집기 창이 열려있으면 즉시 숨김
    # alpha=0으로 먼저 투명화 → DWM 페이드 애니메이션 중에도 화면에 안 보임
    try:
        ew = _editor_ref[0] if _editor_ref else None
        if ew is not None and ew.root.winfo_exists() and ew.root.winfo_viewable():
            # 3-6 item 1: 최대화 등 창 상태를 저장 (나중에 복원)
            _editor_prev_state = ew.root.wm_state()
            ew.root.attributes('-alpha', 0)  # 즉시 투명 (애니메이션 잔상 방지)
            ew.root.withdraw()
            root.update_idletasks()
            _editor_hidden_for_capture = True
    except Exception:
        pass

    # 스크린샷 전에 툴바를 숨김 (모든 캡처 모드 공통)
    # → 캡처 직전 표시 여부 기록 후 항상 숨김 (배경 이미지에 툴바 미포함)
    # → 오버레이 뜬 후 on_overlay_ready 콜백에서 오버레이 위로 다시 표시 (비주얼 전용)
    # → 캡처 완료 후 원래 상태로 복원 (표시 → 표시, 숨김 → 숨김)
    _set_toolbar_interactive(False)  # 오버레이 위에 뜰 때 비주얼 전용
    try:
        tb = _toolbar_win_ref[0] if _toolbar_win_ref else None
        if tb:
            _toolbar_was_visible = bool(tb.winfo_viewable())
            if _toolbar_was_visible:
                tb.withdraw()
                root.update_idletasks()
    except Exception:
        pass

    root.after(150, lambda: _run_capture(root, mode_var))


def _run_capture(root: tk.Tk, mode_var: tk.StringVar) -> None:
    global _capture_in_progress
    try:
        mode = mode_var.get() if mode_var else "smart"
        if not mode:
            mode = "smart"  # fallback

        captured = _capture_by_mode(root, mode)

        if captured is not None:
            hist = hist_module.get_history()
            idx = hist.add(captured)
            _open_editor(root, captured, idx)

    except Exception as exc:
        import traceback
        messagebox.showerror("캡처 오류", str(exc), parent=root)
        traceback.print_exc()
    finally:
        _capture_in_progress = False
        # 캡처 완료 → 툴바 인터랙션 즉시 복원 (숨김/표시 복원은 이후 after()에서)
        _set_toolbar_interactive(True)
        # 17회차: 캡처 완료 후 모드 선택 초기화
        try:
            if mode_var:
                mode_var.set("")
        except Exception:
            pass
        # 19회차 item 2: 대기 중인 모드 전환 처리
        global _pending_mode
        _has_pending = bool(_pending_mode)
        if _pending_mode:
            pm = _pending_mode
            _pending_mode = ""
            try:
                mode_var.set(pm)
                root.after(60, lambda: _do_capture(root, mode_var))
            except Exception:
                pass

        # 캡처 완료 후 툴바를 원래 상태로 복원
        # 원래 보였으면 → 다시 표시, 원래 숨겨져 있었으면 → 계속 숨김
        # (pending mode가 있으면 다음 캡처도 진행 중이므로 아직 유지)
        global _toolbar_was_visible
        if not _has_pending:
            if _toolbar_was_visible:
                def _restore_toolbar():
                    tb = _toolbar_win_ref[0] if _toolbar_win_ref else None
                    if tb:
                        try:
                            tb.deiconify()
                            tb.lift()
                        except Exception:
                            pass
                root.after(0, _restore_toolbar)
            else:
                def _keep_toolbar_hidden():
                    tb = _toolbar_win_ref[0] if _toolbar_win_ref else None
                    if tb:
                        try:
                            tb.withdraw()
                        except Exception:
                            pass
                root.after(0, _keep_toolbar_hidden)

        # 캡처 취소 시 숨겼던 편집기 복원
        # (성공 시에는 _open_editor 내 deiconify 처리, 취소 시만 여기서 복원)
        global _editor_hidden_for_capture
        if _editor_hidden_for_capture and not _has_pending:
            _editor_hidden_for_capture = False
            def _restore_editor():
                try:
                    ew = _editor_ref[0] if _editor_ref else None
                    if ew is not None and ew.root.winfo_exists():
                        ew.root.deiconify()
                        # 3-6 item 1: 캡처 전 창 상태 복원 (최대화 등)
                        if _editor_prev_state == "zoomed":
                            ew.root.wm_state("zoomed")
                        ew.root.attributes('-alpha', 1)  # alpha 복원
                        ew.root.lift()
                except Exception:
                    pass
            root.after(0, _restore_editor)


def _capture_by_mode(root: tk.Tk, mode: str):
    """모드에 따라 해당 캡처 클래스를 실행하고 이미지를 반환합니다."""
    global _current_capture_obj
    cap = None

    # 오버레이가 실제로 생성된 직후에 호출 → 툴바를 오버레이 위로 lift (비주얼 전용)
    def _on_overlay_ready():
        _lift_toolbar_above_overlay(root)

    try:
        if mode == "direct":
            from capture.direct import DirectCapture
            cap = DirectCapture(master=root, on_overlay_ready=_on_overlay_ready)
        elif mode == "smart":
            from capture.smart import SmartCapture
            cap = SmartCapture(master=root, on_overlay_ready=_on_overlay_ready)
        elif mode == "fixed":
            from capture.fixed import FixedCapture
            cap = FixedCapture(master=root, on_overlay_ready=_on_overlay_ready)
        else:
            from capture.smart import SmartCapture
            cap = SmartCapture(master=root, on_overlay_ready=_on_overlay_ready)
        _current_capture_obj = cap
        return cap.start()
    finally:
        _current_capture_obj = None


def _open_editor(root: tk.Tk, image, idx: int) -> None:
    """편집기 창을 엽니다. 이미 열려있으면 기존 창을 재활용합니다. idx=-1이면 빈 상태."""
    global _editor_ref
    try:
        # 기존 편집기가 살아있으면 재활용
        ew = _editor_ref[0] if _editor_ref else None
        if ew is not None:
            try:
                if ew.root.winfo_exists():
                    ew.root.deiconify()
                    # 3-6 item 1: 캡처 전 창 상태 복원 (최대화 등)
                    if _editor_prev_state == "zoomed":
                        ew.root.wm_state("zoomed")
                    ew.root.attributes('-alpha', 1)  # 캡처 전 alpha=0 설정 복원
                    ew.root.lift()
                    ew.load_image(idx)
                    return
            except Exception:
                pass

        from editor.window import open_editor
        ew = open_editor(image, master=root, history_idx=idx)
        _editor_ref[:] = [ew]
    except ImportError:
        try:
            from editor import open_editor as _open
            _open(image, master=root)
        except ImportError:
            pass


def _show_capture_list(root: tk.Tk) -> None:
    """캡처목록 버튼: 편집기를 열거나 포커스합니다. 빈 상태도 허용합니다."""
    hist = hist_module.get_history()
    # 기존 편집기가 살아있으면 포커스
    try:
        ew = _editor_ref[0] if _editor_ref else None
        if ew is not None and ew.root.winfo_exists():
            ew.root.deiconify()
            ew.root.lift()
            # after(50): 툴바 버튼 클릭 이벤트가 완전히 처리된 후 포커스 설정
            ew.root.after(50, ew.root.focus_force)
            return
    except Exception:
        pass
    # 새 편집기 열기 (빈 상태 포함)
    if hist.count() > 0:
        idx = hist.count() - 1
        _open_editor(root, hist.get(idx), idx)
    else:
        _open_editor(root, None, -1)


_hotkey_handle = None  # keyboard.add_hotkey 반환 핸들
_mode_hotkey_handles: dict = {}  # {mode: handle}
_toolbar_toggle_handle = None  # 툴바 표시/숨기기 단축키 핸들
_toolbar_was_visible = False   # 캡처 직전 툴바 표시 여부 (복원 판단용)

# 19회차 item 2: 캡처 중 모드 전환용
_current_capture_obj = None   # 현재 실행 중인 캡처 인스턴스
_pending_mode: str = ""       # 전환 대기 중인 모드

# 캡처 진입 시 편집기를 숨겼는지 여부 (취소 시 복원 용도)
_editor_hidden_for_capture: bool = False

# 3-6 item 1: 캡처 전 편집기 창 상태 저장 (최대화 복원용)
_editor_prev_state: str = ""

# 중복 실행 방지용 뮤텍스 (GC 방지용 전역 참조 필요)
_single_instance_mutex = None


def _ensure_single_instance() -> bool:
    """Windows 뮤텍스로 중복 실행을 방지합니다."""
    global _single_instance_mutex
    try:
        _single_instance_mutex = ctypes.windll.kernel32.CreateMutexW(
            None, False, "SmartCapture_SingleInstance_Mutex_2025")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def _register_mode_hotkeys(root: tk.Tk, mode_var: tk.StringVar) -> None:
    """모드별 단축키를 등록합니다 (config의 mode_hotkeys)."""
    global _mode_hotkey_handles
    try:
        import keyboard
    except ImportError:
        return

    for handle in _mode_hotkey_handles.values():
        try:
            keyboard.remove_hotkey(handle)
        except Exception:
            pass
    _mode_hotkey_handles.clear()

    cfg = cfg_module.get()
    mode_hotkeys: dict = cfg.get("mode_hotkeys", {})
    for mode, hk in mode_hotkeys.items():
        if not hk or hk == "없음":
            continue
        def _make_cb(m=mode):
            def _cb():
                global _pending_mode
                # 19회차 item 2: 캡처 중 다른 모드 단축키 → 현재 캡처 취소 후 전환
                if _capture_in_progress:
                    _pending_mode = m
                    cap = _current_capture_obj
                    if cap is not None:
                        root.after(0, lambda c=cap: _try_cancel(c))
                else:
                    mode_var.set(m)
                    root.after(0, lambda: _do_capture(root, mode_var))
            return _cb
        try:
            handle = keyboard.add_hotkey(hk, _make_cb())
            _mode_hotkey_handles[mode] = handle
        except Exception as exc:
            _log_warn(f"모드 단축키 등록 실패 ({mode}={hk}): {exc}")


def _try_cancel(cap) -> None:
    """캡처 인스턴스를 안전하게 취소합니다 (19회차 item 2)."""
    try:
        cap._cancel()
    except Exception:
        pass


def _register_toolbar_toggle_hotkey(root: tk.Tk, toolbar_ref: list) -> None:
    """툴바 표시/숨기기 단축키를 등록합니다."""
    global _toolbar_toggle_handle
    try:
        import keyboard
    except ImportError:
        return

    if _toolbar_toggle_handle is not None:
        try:
            keyboard.remove_hotkey(_toolbar_toggle_handle)
        except Exception:
            pass
        _toolbar_toggle_handle = None

    cfg = cfg_module.get()
    hk = cfg.get("toolbar_toggle_hotkey", "")
    if not hk or hk == "없음":
        return

    def _do_toggle():
        tb = toolbar_ref[0] if toolbar_ref else None
        if tb is not None:
            try:
                if tb.winfo_viewable():
                    tb.withdraw()
                    _set_toolbar_visible(False)
                else:
                    tb.deiconify()
                    tb.lift()
                    _set_toolbar_visible(True)
            except Exception:
                pass

    try:
        _toolbar_toggle_handle = keyboard.add_hotkey(
            hk, lambda: root.after(0, _do_toggle))
    except Exception as exc:
        _log_warn(f"툴바 토글 단축키 등록 실패: {exc}")


def _register_hotkey(root: tk.Tk, mode_var: tk.StringVar) -> None:
    """keyboard 전역 훅으로 단축키를 등록합니다."""
    global _hotkey_handle
    try:
        import keyboard
    except ImportError:
        _log_warn("keyboard 모듈 없음 - 전역 단축키 비활성화")
        return

    # 기존 핸들만 제거 (remove_all_hotkeys는 버전 호환성 문제가 있음)
    if _hotkey_handle is not None:
        try:
            keyboard.remove_hotkey(_hotkey_handle)
        except Exception:
            pass
        _hotkey_handle = None

    cfg = cfg_module.get()
    hotkey = cfg.get("hotkey", "f8")
    try:
        _hotkey_handle = keyboard.add_hotkey(
            hotkey,
            lambda: root.after(0, lambda: _do_capture(root, mode_var)),
        )
    except Exception as exc:
        _log_warn(f"단축키 등록 실패: {exc}")


# ------------------------------------------------------------------
# 시스템 트레이 아이콘
# ------------------------------------------------------------------

def make_tray_icon():
    """트레이 아이콘 이미지를 반환합니다.
    image/program/icon.png 가 있으면 해당 파일을 사용하고, 없으면 드로잉 폴백."""
    from pathlib import Path
    from PIL import Image
    try:
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).resolve().parent
        icon_path = base / "image" / "program" / "icon.png"
        if icon_path.exists():
            return Image.open(icon_path).convert("RGBA").resize((64, 64), Image.LANCZOS)
    except Exception:
        pass
    # 폴백: 드로잉 아이콘
    from PIL import ImageDraw
    img = Image.new('RGB', (64, 64), color='#0078D4')
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, 56, 56], outline='white', width=3)
    draw.line([20, 32, 44, 32], fill='white', width=3)
    draw.line([32, 20, 32, 44], fill='white', width=3)
    return img


def _setup_tray(root: tk.Tk, mode_var: tk.StringVar, toolbar_ref: list,
                open_settings_fn=None) -> None:
    """pystray 트레이 아이콘을 별도 스레드에서 실행합니다."""
    global _tray_icon
    try:
        import pystray
    except ImportError:
        _log_warn("pystray 모듈 없음 - 트레이 아이콘 비활성화")
        return

    def show_capture_list(icon, item):
        """더블클릭 또는 메뉴 선택 시 캡처 목록 편집기를 엽니다."""
        root.after(0, lambda: _show_capture_list(root))

    def toggle_toolbar(icon, item):
        """툴바 표시/숨기기를 메인 스레드에서 실행합니다."""
        def _toggle():
            tb = toolbar_ref[0] if toolbar_ref else None
            if tb is not None:
                try:
                    if tb.winfo_viewable():
                        tb.withdraw()
                        _set_toolbar_visible(False)
                    else:
                        tb.deiconify()
                        tb.lift()
                        _set_toolbar_visible(True)
                except Exception:
                    pass
            else:
                if root.winfo_viewable():
                    root.withdraw()
                    _set_toolbar_visible(False)
                else:
                    root.deiconify()
                    root.lift()
                    _set_toolbar_visible(True)
        root.after(0, _toggle)

    def open_settings_tray(icon, item):
        if open_settings_fn:
            root.after(0, open_settings_fn)

    def quit_app(icon, item):
        """앱을 종료합니다."""
        def _quit():
            icon.stop()
            root.quit()
            root.destroy()
        root.after(0, _quit)

    menu = pystray.Menu(
        # default=True → 더블클릭 동작, visible=False → 우클릭 메뉴에서 제외
        pystray.MenuItem("캡처목록 열기", show_capture_list, default=True, visible=False),
        pystray.MenuItem("툴바 보이기/숨기기", toggle_toolbar),
        pystray.MenuItem("설정", open_settings_tray),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("종료", quit_app),
    )

    _tray_icon = pystray.Icon("ScreenShit", make_tray_icon(), "ScreenShit", menu=menu)

    # 별도 스레드에서 트레이 아이콘 실행 (pystray는 자체 이벤트 루프를 가짐)
    t = threading.Thread(target=_tray_icon.run, daemon=True)
    t.start()


def _set_window_icon(win) -> None:
    """창 아이콘을 설정합니다.
    icon.ico 가 있으면 iconbitmap 으로 적용.
    없으면 icon.png 를 원본 크기 그대로 iconphoto 로 적용합니다.
    (icon.png 를 고해상도로 교체하면 자동으로 품질 향상)"""
    try:
        from pathlib import Path
        from PIL import Image, ImageTk
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).resolve().parent
        prog_dir = base / "image" / "program"
        ico_path = prog_dir / "icon.ico"
        png_path = prog_dir / "icon.png"

        if ico_path.exists():
            win.iconbitmap(str(ico_path))
            return

        if png_path.exists():
            img = Image.open(png_path).convert("RGBA")
            photo = ImageTk.PhotoImage(img)
            win.iconphoto(True, photo)
            win._icon_photo = photo  # GC 방지
    except Exception:
        pass


def _hide_from_taskbar(root: tk.Tk) -> None:
    """Windows API를 사용해 루트 창을 작업표시줄에서 숨깁니다."""
    try:
        root.update_idletasks()
        hwnd = root.winfo_id()
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
    except Exception as exc:
        _log_warn(f"작업표시줄 숨김 처리 실패: {exc}")


def main() -> None:
    # 중복 실행 방지 (Windows 뮤텍스)
    if not _ensure_single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                None, "ScreenShit이 이미 실행 중입니다.", "알림", 0x40)
        except Exception:
            pass
        sys.exit(0)

    root = tk.Tk()
    root.withdraw()  # 툴바가 표시하기 전까지 숨김
    _set_window_icon(root)

    # 작업표시줄에서 루트 창 숨기기
    _hide_from_taskbar(root)

    # 모드 변수 (캡처 시 설정, 완료 후 초기화 — 17회차: 기본값 없음)
    mode_var = tk.StringVar(value="")

    # 모드별 단축키만 등록 (전체 캡처 단축키 없음)
    _register_mode_hotkeys(root, mode_var)

    # toolbar_ref: 트레이 아이콘에서 툴바 창을 참조하기 위한 리스트
    toolbar_ref = []

    # 툴바 실행
    try:
        from toolbar import Toolbar

        def on_hotkey_changed(hk: str) -> None:
            cfg = cfg_module.get()
            cfg["hotkey"] = hk
            _register_hotkey(root, mode_var)

        def on_mode_hotkeys_changed() -> None:
            _register_mode_hotkeys(root, mode_var)
            _register_toolbar_toggle_hotkey(root, toolbar_ref)

        toolbar = Toolbar(
            root,
            mode_var=mode_var,
            on_capture=trigger_capture,
            on_hotkey_changed=on_hotkey_changed,
            on_mode_hotkeys_changed=on_mode_hotkeys_changed,
            on_show_list=lambda: _show_capture_list(root),
        )

        # toolbar 창·객체 참조를 저장 (트레이 + 캡처 중 숨기기 + set_interactive에 사용)
        _toolbar_win_ref.append(toolbar.win)
        _toolbar_obj_ref.append(toolbar)
        toolbar_ref.append(toolbar.win)

        # 18회차 item 2: Map/Unmap 이벤트로 _toolbar_visible 자동 동기화
        # (X버튼·단축키·트레이 모든 경로에서 동기화)
        toolbar.win.bind("<Map>",   lambda e: _set_toolbar_visible(True))
        toolbar.win.bind("<Unmap>", lambda e: _set_toolbar_visible(False))

        # 툴바 토글 단축키 등록
        _register_toolbar_toggle_hotkey(root, toolbar_ref)

        # 트레이 아이콘 설정 (별도 스레드)
        _setup_tray(root, mode_var, toolbar_ref,
                    open_settings_fn=toolbar._open_settings)

        toolbar.run()
    except ImportError:
        # toolbar.py가 없을 때 최소 동작 (개발/테스트용)
        _setup_tray(root, mode_var, toolbar_ref)
        _fallback_main(root, mode_var)


def _fallback_main(root: tk.Tk, mode_var: tk.StringVar) -> None:
    """toolbar.py가 없을 때 임시 최소 UI."""
    root.deiconify()
    root.title("ScreenShit (최소 모드)")
    root.geometry("300x120")
    root.attributes("-topmost", True)
    root.protocol("WM_DELETE_WINDOW", root.withdraw)  # 닫기 버튼은 숨기기 (트레이로)

    tk.Label(root, text="ScreenShit", font=("맑은 고딕", 13, "bold")).pack(pady=10)

    mode_options = [("직접지정", "direct"), ("단위영역", "smart"), ("크기지정", "fixed")]
    frame = tk.Frame(root)
    frame.pack()
    for label, val in mode_options:
        tk.Radiobutton(frame, text=label, variable=mode_var, value=val).pack(
            side=tk.LEFT, padx=4
        )

    tk.Button(
        root, text="캡처 (F8)",
        command=lambda: _do_capture(root, mode_var),
    ).pack(pady=6)

    root.bind("<F8>", lambda e: _do_capture(root, mode_var))
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
