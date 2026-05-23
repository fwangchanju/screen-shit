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


# 캡처 진행 중 중복 실행 방지
_capture_in_progress = False

# 트레이 아이콘 전역 참조
_tray_icon = None

# 편집기 창 참조 (캡처목록 버튼용)
_editor_ref: list = []

# 툴바 창 참조 (캡처 중 숨기기/복원용)
_toolbar_win_ref: list = []


def _hide_toolbar() -> None:
    try:
        win = _toolbar_win_ref[0] if _toolbar_win_ref else None
        if win:
            win.withdraw()
    except Exception:
        pass


def _show_toolbar() -> None:
    try:
        win = _toolbar_win_ref[0] if _toolbar_win_ref else None
        if win:
            win.deiconify()
    except Exception:
        pass


def trigger_capture(root: tk.Tk, mode_var: tk.StringVar) -> None:
    """단축키 또는 버튼에 의해 호출되는 캡처 트리거."""
    root.after(0, lambda: _do_capture(root, mode_var))


def _do_capture(root: tk.Tk, mode_var: tk.StringVar) -> None:
    global _capture_in_progress
    if _capture_in_progress:
        return
    _capture_in_progress = True

    # 툴바 창 숨기기 (root가 아닌 toolbar Toplevel)
    _hide_toolbar()
    # 화면 갱신 후 캡처 시작 (창이 사라질 시간 확보)
    root.after(150, lambda: _run_capture(root, mode_var))


def _run_capture(root: tk.Tk, mode_var: tk.StringVar) -> None:
    global _capture_in_progress
    try:
        mode = mode_var.get() if mode_var else "smart"
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
        _show_toolbar()


def _capture_by_mode(root: tk.Tk, mode: str):
    """모드에 따라 해당 캡처 클래스를 실행하고 이미지를 반환합니다."""
    if mode == "direct":
        from capture.direct import DirectCapture
        return DirectCapture(master=root).start()
    elif mode == "smart":
        from capture.smart import SmartCapture
        return SmartCapture(master=root).start()
    elif mode == "fixed":
        from capture.fixed import FixedCapture
        return FixedCapture(master=root).start()
    else:
        from capture.smart import SmartCapture
        return SmartCapture(master=root).start()


def _open_editor(root: tk.Tk, image, idx: int) -> None:
    """편집기 창을 엽니다. 이미 열려있으면 기존 창을 재활용합니다."""
    global _editor_ref
    try:
        # 기존 편집기가 살아있으면 새 이미지만 로드
        ew = _editor_ref[0] if _editor_ref else None
        if ew is not None:
            try:
                if ew.root.winfo_exists():
                    ew.root.deiconify()
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
    """캡처목록 버튼: 편집기를 열거나 포커스합니다."""
    hist = hist_module.get_history()
    if hist.count() == 0:
        messagebox.showinfo("캡처목록", "아직 캡처된 이미지가 없습니다.", parent=root)
        return
    # 기존 편집기가 살아있으면 포커스
    try:
        ew = _editor_ref[0] if _editor_ref else None
        if ew is not None and ew.root.winfo_exists():
            ew.root.deiconify()
            ew.root.lift()
            ew.root.focus_force()
            return
    except Exception:
        pass
    # 새 편집기 열기
    idx = hist.count() - 1
    _open_editor(root, hist.get(idx), idx)


_hotkey_handle = None  # keyboard.add_hotkey 반환 핸들


def _register_hotkey(root: tk.Tk, mode_var: tk.StringVar) -> None:
    """keyboard 전역 훅으로 단축키를 등록합니다."""
    global _hotkey_handle
    try:
        import keyboard
    except ImportError:
        print("[경고] keyboard 모듈 없음 - 전역 단축키 비활성화", file=sys.stderr)
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
        print(f"[정보] 단축키 등록: {hotkey.upper()}")
    except Exception as exc:
        print(f"[경고] 단축키 등록 실패: {exc}", file=sys.stderr)


# ------------------------------------------------------------------
# 시스템 트레이 아이콘
# ------------------------------------------------------------------

def make_tray_icon():
    """PIL로 트레이 아이콘 이미지를 생성합니다."""
    from PIL import Image, ImageDraw
    img = Image.new('RGB', (64, 64), color='#0078D4')
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, 56, 56], outline='white', width=3)
    draw.line([20, 32, 44, 32], fill='white', width=3)
    draw.line([32, 20, 32, 44], fill='white', width=3)
    return img


def _setup_tray(root: tk.Tk, mode_var: tk.StringVar, toolbar_ref: list) -> None:
    """pystray 트레이 아이콘을 별도 스레드에서 실행합니다."""
    global _tray_icon
    try:
        import pystray
    except ImportError:
        print("[경고] pystray 모듈 없음 - 트레이 아이콘 비활성화", file=sys.stderr)
        return

    def toggle_toolbar(icon, item):
        """툴바 표시/숨기기를 메인 스레드에서 실행합니다."""
        def _toggle():
            tb = toolbar_ref[0] if toolbar_ref else None
            if tb is not None:
                try:
                    if tb.winfo_viewable():
                        tb.withdraw()
                    else:
                        tb.deiconify()
                        tb.lift()
                except Exception:
                    pass
            else:
                # toolbar_ref가 없을 때 root 창 자체를 토글
                if root.winfo_viewable():
                    root.withdraw()
                else:
                    root.deiconify()
                    root.lift()
        root.after(0, _toggle)

    def quit_app(icon, item):
        """앱을 종료합니다."""
        def _quit():
            icon.stop()
            root.quit()
            root.destroy()
        root.after(0, _quit)

    def on_double_click(icon, item):
        """더블클릭 시 툴바가 숨겨져 있으면 표시합니다."""
        def _show():
            tb = toolbar_ref[0] if toolbar_ref else None
            if tb is not None:
                try:
                    if not tb.winfo_viewable():
                        tb.deiconify()
                        tb.lift()
                        tb.focus_force()
                except Exception:
                    pass
        root.after(0, _show)

    menu = pystray.Menu(
        pystray.MenuItem("툴바 표시/숨기기", toggle_toolbar, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("종료", quit_app),
    )

    _tray_icon = pystray.Icon("SmartCapture", make_tray_icon(), "스마트 캡쳐", menu=menu)

    # 별도 스레드에서 트레이 아이콘 실행 (pystray는 자체 이벤트 루프를 가짐)
    t = threading.Thread(target=_tray_icon.run, daemon=True)
    t.start()


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
        print(f"[경고] 작업표시줄 숨김 처리 실패: {exc}", file=sys.stderr)


def main() -> None:
    root = tk.Tk()
    root.withdraw()  # 툴바가 표시하기 전까지 숨김

    # 작업표시줄에서 루트 창 숨기기
    _hide_from_taskbar(root)

    # 모드 변수 (toolbar.py에서 업데이트)
    mode_var = tk.StringVar(value="smart")

    # 전역 단축키 등록
    _register_hotkey(root, mode_var)

    # toolbar_ref: 트레이 아이콘에서 툴바 창을 참조하기 위한 리스트
    toolbar_ref = []

    # 툴바 실행
    try:
        from toolbar import Toolbar

        def on_hotkey_changed(hk: str) -> None:
            cfg = cfg_module.get()
            cfg["hotkey"] = hk
            _register_hotkey(root, mode_var)

        toolbar = Toolbar(
            root,
            mode_var=mode_var,
            on_capture=trigger_capture,
            on_hotkey_changed=on_hotkey_changed,
            on_show_list=lambda: _show_capture_list(root),
        )

        # toolbar 창 참조를 저장 (트레이 + 캡처 중 숨기기에 사용)
        _toolbar_win_ref.append(toolbar.win)
        toolbar_ref.append(toolbar.win)

        # 트레이 아이콘 설정 (별도 스레드)
        _setup_tray(root, mode_var, toolbar_ref)

        toolbar.run()
    except ImportError:
        # toolbar.py가 없을 때 최소 동작 (개발/테스트용)
        _setup_tray(root, mode_var, toolbar_ref)
        _fallback_main(root, mode_var)


def _fallback_main(root: tk.Tk, mode_var: tk.StringVar) -> None:
    """toolbar.py가 없을 때 임시 최소 UI."""
    root.deiconify()
    root.title("스마트 캡쳐 (최소 모드)")
    root.geometry("300x120")
    root.attributes("-topmost", True)
    root.protocol("WM_DELETE_WINDOW", root.withdraw)  # 닫기 버튼은 숨기기 (트레이로)

    tk.Label(root, text="스마트 캡쳐", font=("맑은 고딕", 13, "bold")).pack(pady=10)

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
    main()
