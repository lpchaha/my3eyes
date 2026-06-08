"""
弹窗警示模块
在屏幕右下角弹出灰色风格的非阻塞警示窗口
"""
import tkinter as tk
import ctypes
import threading


class AlertPopup:
    """
    灰色风格警示弹窗
    在屏幕右下角显示，带滑入动画，非阻塞
    """

    # ---- 灰色配色方案 ----
    COLOR_BG_MAIN = "#f5f5f5"
    COLOR_TITLE_BG = "#757575"
    COLOR_TITLE_FG = "#ffffff"
    COLOR_TEXT = "#424242"
    COLOR_TEXT_BG = "#fafafa"
    COLOR_BUTTON = "#9e9e9e"
    COLOR_BUTTON_HOVER = "#bdbdbd"
    COLOR_BUTTON_FG = "#ffffff"
    COLOR_BORDER = "#bdbdbd"

    def __init__(self, master, width=340, height=160, duration_ms=6000):
        """
        初始化弹窗

        Args:
            master: 主 Tk 根窗口（必须传入，避免创建第二个 Tk 导致主程序退出）
            width: 弹窗宽度（像素）
            height: 弹窗高度（像素）
            duration_ms: 自动关闭时长（毫秒），0 为不自动关闭
        """
        self.master = master
        self.width = width
        self.height = height
        self.duration_ms = duration_ms
        self._popup = None
        self._after_id = None

    def show(self, message, title="Alert"):
        """
        显示警示弹窗（非阻塞，在独立线程中运行）

        Args:
            message: 弹窗正文内容
            title: 弹窗标题
        """
        self.dismiss()
        threading.Thread(
            target=self._show_thread,
            args=(message, title),
            daemon=True
        ).start()

    def _show_thread(self, message, title):
        """在独立线程中显示弹窗（使用主 Tk root 的 Toplevel，不创建新 Tk）"""
        try:
            self._popup = tk.Toplevel(self.master)
            self._popup.overrideredirect(True)
            self._popup.attributes("-topmost", True)
            self._popup.configure(bg=self.COLOR_BORDER)

            self._build_ui(message, title)
            self._position_at_bottom_right()
            self._slide_in()

            if self.duration_ms > 0:
                self._after_id = self._popup.after(self.duration_ms, self.dismiss)

            # 局部事件循环，仅等待此 Toplevel 被销毁
            self._popup.wait_window()

        except tk.TclError:
            pass
        except Exception:
            pass

    def _build_ui(self, message, title):
        """构建弹窗 UI"""
        # ---- 标题栏 ----
        title_bar = tk.Frame(self._popup, bg=self.COLOR_TITLE_BG, height=36)
        title_bar.pack(fill=tk.X)
        title_bar.pack_propagate(False)

        title_icon = tk.Label(title_bar, text="\u26A0", font=("Segoe UI", 12),
                              bg=self.COLOR_TITLE_BG, fg=self.COLOR_TITLE_FG)
        title_icon.pack(side=tk.LEFT, padx=(10, 2))

        title_label = tk.Label(title_bar, text=title, font=("Microsoft YaHei UI", 11, "bold"),
                               bg=self.COLOR_TITLE_BG, fg=self.COLOR_TITLE_FG)
        title_label.pack(side=tk.LEFT)

        close_btn = tk.Label(title_bar, text="\u00D7", font=("Segoe UI", 14),
                             bg=self.COLOR_TITLE_BG, fg=self.COLOR_TITLE_FG, cursor="hand2")
        close_btn.pack(side=tk.RIGHT, padx=(0, 10))
        close_btn.bind("<Button-1>", lambda e: self.dismiss())

        # ---- 内容区域 ----
        content_frame = tk.Frame(self._popup, bg=self.COLOR_BG_MAIN)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=(0, 2))

        inner = tk.Frame(content_frame, bg=self.COLOR_TEXT_BG)
        inner.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        msg_label = tk.Label(inner, text=message, font=("Microsoft YaHei UI", 10),
                             bg=self.COLOR_TEXT_BG, fg=self.COLOR_TEXT,
                             justify=tk.LEFT, wraplength=self.width - 50)
        msg_label.pack(anchor=tk.W, pady=(5, 10))

        # ---- 按钮 ----
        btn_frame = tk.Frame(content_frame, bg=self.COLOR_BG_MAIN)
        btn_frame.pack(fill=tk.X, padx=10, pady=(0, 10))

        confirm_btn = tk.Label(btn_frame, text="  OK  ", font=("Microsoft YaHei UI", 9),
                               bg=self.COLOR_BUTTON, fg=self.COLOR_BUTTON_FG,
                               padx=20, pady=4, cursor="hand2")
        confirm_btn.pack(side=tk.RIGHT)
        confirm_btn.bind("<Button-1>", lambda e: self.dismiss())
        confirm_btn.bind("<Enter>", lambda e: confirm_btn.configure(bg=self.COLOR_BUTTON_HOVER))
        confirm_btn.bind("<Leave>", lambda e: confirm_btn.configure(bg=self.COLOR_BUTTON))

    def _get_work_area(self):
        """获取 Windows 工作区尺寸（排除任务栏）"""
        try:
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)
                ]
            rc = RECT()
            ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rc), 0)
            return rc.right - rc.left, rc.bottom - rc.top
        except Exception:
            return (self._popup.winfo_screenwidth(),
                    self._popup.winfo_screenheight() - 40)

    def _get_mouse_monitor_work_area(self):
        """
        获取鼠标当前所在显示器的 work area（排除任务栏）。
        返回 (right, bottom) 绝对坐标，如果获取失败则回退到主显示器。
        """
        try:
            # 获取鼠标位置
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))

            # 找到鼠标所在的显示器
            MONITOR_DEFAULTTONEAREST = 0x00000002
            hmon = ctypes.windll.user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)

            # 获取该显示器的 work area
            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)
                ]
            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_ulong),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_ulong),
                ]
            mi = MONITORINFO()
            mi.cbSize = ctypes.sizeof(MONITORINFO)
            ctypes.windll.user32.GetMonitorInfoW(hmon, ctypes.byref(mi))

            return mi.rcWork.right, mi.rcWork.bottom
        except Exception:
            # 回退：使用主显示器
            return self._get_work_area()

    def _position_at_bottom_right(self):
        """将弹窗定位到鼠标所在显示器的右下角"""
        self._popup.update_idletasks()
        work_w, work_h = self._get_mouse_monitor_work_area()
        self._target_x = work_w - self.width
        self._target_y = work_h - self.height

    def _slide_in(self):
        """从鼠标所在显示器底部向上滑入"""
        work_w, work_h = self._get_mouse_monitor_work_area()
        start_y = work_h
        self._popup.geometry(f"{self.width}x{self.height}+{self._target_x}+{start_y}")
        step = 8
        current_y = start_y

        def animate():
            nonlocal current_y
            if current_y > self._target_y and self._popup is not None:
                current_y = max(self._target_y, current_y - step)
                try:
                    self._popup.geometry(
                        f"{self.width}x{self.height}+{self._target_x}+{current_y}"
                    )
                    self._popup.after(5, animate)
                except tk.TclError:
                    pass

        if self._popup is not None:
            animate()

    def dismiss(self):
        """关闭弹窗并清理"""
        if self._after_id is not None and self._popup is not None:
            try:
                self._popup.after_cancel(self._after_id)
            except (tk.TclError, ValueError):
                pass
            self._after_id = None

        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
            self._popup = None
