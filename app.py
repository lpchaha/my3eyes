"""
3eyes - 人员靠近检测警示系统主程序
包含配置界面和系统托盘功能
"""
import os
import sys
import builtins
import cv2
import time
import threading
import queue
import traceback
import logging
import logging.handlers
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# ============================================================
# 日志系统 —— 写文件 + 可选 UI handler
# ============================================================
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "3eyes.log")

_logger = logging.getLogger("3eyes")
_logger.setLevel(logging.DEBUG)
_logger.handlers.clear()
_logger.propagate = False

_fh = logging.handlers.TimedRotatingFileHandler(
    _LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8"
)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
_logger.addHandler(_fh)

# ---- Tkinter 日志 Handler（挂载后日志同步到 UI 控件） ----
class TkLogHandler(logging.Handler):
    """线程安全地将日志推送到 tk.Text 控件"""
    def __init__(self, text_widget, max_lines=500):
        super().__init__()
        self.widget = text_widget
        self.max_lines = max_lines
        self._queue = queue.Queue()
        self._check_id = None

    def emit(self, record):
        try:
            self._queue.put(self.format(record))
        except Exception:
            pass
        self._schedule()

    def _schedule(self):
        w = self.widget
        if self._check_id is None and w and w.winfo_exists():
            self._check_id = w.after(100, self._flush)

    def _flush(self):
        self._check_id = None
        try:
            w = self.widget
            if not w or not w.winfo_exists():
                return
            while True:
                try:
                    msg = self._queue.get_nowait()
                except queue.Empty:
                    break
                w.insert(tk.END, msg + "\n")
            # 保持行数不超标
            try:
                end = w.index("end-1c")
                line_num = int(end.split(".")[0]) if end else 0
                if line_num > self.max_lines:
                    w.delete("1.0", f"{line_num - self.max_lines}.0")
                w.see(tk.END)
            except Exception:
                pass
        except Exception:
            pass
        if not self._queue.empty():
            self._schedule()

    def detach(self):
        if self._check_id is not None:
            try:
                self.widget.after_cancel(self._check_id)
            except Exception:
                pass
            self._check_id = None

# ---- 重定向 print → logging（不改动任何现有 print 语句） ----
_original_print = builtins.print

def _log_print(*args, **kwargs):
    """
    将所有 print(...) 重定向到 logging.info
    不再做 file=sys.stderr 判断 —— 该判断在某些环境下不可靠，
    会导致全部日志误写成 [ERROR] 级别
    """
    msg = " ".join(str(a) for a in args)
    _logger.info(msg)

builtins.print = _log_print

# ============================================================
# 全局异常捕获 —— 任何未捕获异常都会输出到 stderr（通过 _original_print 确保输出）
# ============================================================
def _global_excepthook(exc_type, exc_value, exc_tb):
    """全局未捕获异常钩子"""
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print(f"\n{'─' * 60}\n【全局异常】\n{msg}─{'─' * 60}\n", flush=True)
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _global_excepthook

# 线程异常钩子（Python 3.8+）
if hasattr(threading, "excepthook"):
    def _thread_excepthook(args):
        msg = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
        print(f"\n{'─' * 60}\n【线程异常】{args.thread.name}\n{msg}─{'─' * 60}\n", flush=True)
    threading.excepthook = _thread_excepthook


# 导入第三方库
try:
    from pystray import Icon, MenuItem as item
    from PIL import Image, ImageDraw, ImageTk
    HAS_SYSTRAY = True
except ImportError:
    HAS_SYSTRAY = False
    ImageTk = None
    print("【警告】未安装 pystray/PIL")

from detector import PersonDetector
from tracker import ApproachTracker, ApproachState
from alert import AlertPopup
from config_manager import ConfigManager


# ============================================================
# 主应用（单例 Tk root）
# ============================================================
class App:
    """3eyes 主应用 —— 拥有唯一的 tk.Tk() 根窗口"""

    def __init__(self):
        print("【初始化】开始加载配置...", flush=True)
        self.config = ConfigManager()
        print(f"【初始化】配置文件路径: {self.config.config_path}", flush=True)

        # ---- 线程安全锁（保护检测快照） ----
        self._snapshot_lock = threading.Lock()

        # ---- 唯一的 Tk 根窗口（全程复用，不销毁） ----
        print("【初始化】创建 Tk 根窗口...", flush=True)
        self.root = tk.Tk()
        self.root.title("3eyes - 配置")
        self.root.geometry("960x700")
        self.root.minsize(900, 650)
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # ---- UI 控件引用 ----
        self.preview_label = None
        self.status_label = None
        self.camera_combo = None
        self.fps_spin = None
        self.title_entry = None
        self.msg_text = None
        self.camera_options = []

        # ---- Tk 变量 ----
        self.selected_camera = tk.StringVar()
        self.detection_fps = tk.IntVar(value=self.config.get("detection_fps", 10))
        self.resolution_var = tk.StringVar()
        self.alert_title_var = tk.StringVar(value=self.config.get("alert_title", "人员靠近警示"))
        self.alert_msg_var = tk.StringVar()
        self.var_near_threshold = tk.DoubleVar(value=self.config.get("area_near_threshold", 0.20))
        self.var_far_threshold = tk.DoubleVar(value=self.config.get("area_far_threshold", 0.10))
        self.var_approach_frames = tk.IntVar(value=self.config.get("approach_frames", 5))
        self.var_growth_ratio = tk.DoubleVar(value=self.config.get("area_growth_ratio", 1.5))
        self.var_cooldown = tk.IntVar(value=self.config.get("cooldown_seconds", 10))
        self.var_conf_threshold = tk.DoubleVar(value=self.config.get("confidence_threshold", 0.5))

        # ---- 检测流水线 ----
        self.detector = None
        self.tracker = None
        self.alert = None
        self.detection_thread = None
        self._stop_event_config = threading.Event()    # 配置窗口检测停止事件
        self._stop_event_bg = threading.Event()        # 后台检测停止事件
        self.frame_queue = queue.Queue(maxsize=2)
        self.detections_snapshot = []
        self.state_text = "Status: Waiting for camera..."
        self._after_id = None
        self._ui_active = False    # UI 刷新开关（托盘模式关闭）

        # ---- 后台 / 托盘 ----
        self.tray = None
        self.background_thread = None

        # ---- 构建界面 ----
        print("【初始化】构建界面...", flush=True)
        self._build_ui()
        print("【初始化】完成", flush=True)

    # ========================================================
    # 线程安全的状态读写
    # ========================================================
    def _set_snapshot(self, detections, state_text):
        """线程安全地更新检测快照"""
        with self._snapshot_lock:
            self.detections_snapshot = list(detections) if detections else []
            self.state_text = state_text

    def _get_snapshot(self):
        """线程安全地读取检测快照"""
        with self._snapshot_lock:
            return list(self.detections_snapshot), self.state_text

    # ========================================================
    # UI 构建
    # ========================================================
    def _build_ui(self):
        """构建全部 UI 控件 —— 左右布局：左摄像头 / 右配置 / 下日志"""
        print("【UI】构建控件...", flush=True)

        # ---- 顶栏：左侧摄像头 + 右侧配置 ----
        top = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        top.pack(fill=tk.BOTH, expand=True)

        # ============ 左侧：摄像头预览 ============
        left = ttk.Frame(top, width=360)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        left.pack_propagate(False)

        preview_frame = ttk.LabelFrame(left, text="摄像头预览", padding=5)
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self.preview_label = tk.Label(preview_frame, bg="#1a1a2e", relief=tk.SUNKEN,
                                       width=340, height=255)
        self.preview_label.pack()
        self.preview_label.pack_propagate(False)  # 固定 4:3 比例不伸缩

        self.status_label = ttk.Label(preview_frame,
                                      text="状态: 等待摄像头...",
                                      font=("Microsoft YaHei UI", 9))
        self.status_label.pack(pady=(4, 0))

        # ============ 右侧：参数配置 ============
        right = ttk.Frame(top)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cfg_frame = ttk.LabelFrame(right, text="参数配置", padding=10)
        cfg_frame.pack(fill=tk.BOTH, expand=True)

        # 使用 Notebook 分页组织配置项
        nb = ttk.Notebook(cfg_frame)
        nb.pack(fill=tk.BOTH, expand=True)

        # ---- Tab 1: 基本设置 ----
        tab1 = ttk.Frame(nb, padding=(8, 8))
        nb.add(tab1, text="基本设置")

        r0 = ttk.Frame(tab1)
        r0.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r0, text="摄像头:", width=10, anchor=tk.E).pack(side=tk.LEFT, padx=(0, 4))
        self.camera_combo = ttk.Combobox(r0, textvariable=self.selected_camera,
                                         state="readonly", width=24)
        self.camera_combo.pack(side=tk.LEFT)
        self.camera_combo.bind("<<ComboboxSelected>>", self._on_camera_changed)
        ttk.Button(r0, text="刷新", command=self._refresh_cameras).pack(side=tk.LEFT, padx=(4, 0))

        r1 = ttk.Frame(tab1)
        r1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r1, text="检测帧率:", width=10, anchor=tk.E).pack(side=tk.LEFT, padx=(0, 4))
        self.fps_spin = ttk.Spinbox(r1, from_=1, to=30, textvariable=self.detection_fps, width=6)
        self.fps_spin.pack(side=tk.LEFT)
        ttk.Label(r1, text="FPS", foreground="gray").pack(side=tk.LEFT, padx=(4, 0))

        r1b = ttk.Frame(tab1)
        r1b.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r1b, text="分辨率:", width=10, anchor=tk.E).pack(side=tk.LEFT, padx=(0, 4))
        self.resolution_combo = ttk.Combobox(r1b, textvariable=self.resolution_var,
                                             state="readonly", width=18)
        self.resolution_combo.pack(side=tk.LEFT)

        r2 = ttk.Frame(tab1)
        r2.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(r2, text="弹窗标题:", width=10, anchor=tk.E).pack(side=tk.LEFT, padx=(0, 4))
        self.title_entry = ttk.Entry(r2, textvariable=self.alert_title_var, width=26)
        self.title_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        r3 = ttk.Frame(tab1)
        r3.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(r3, text="弹窗内容:", width=10, anchor=tk.E).pack(side=tk.LEFT, anchor=tk.N,
                                                                   padx=(0, 4), pady=(2, 0))
        self.msg_text = scrolledtext.ScrolledText(r3, height=3, wrap=tk.WORD)
        self.msg_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # ---- Tab 2: 检测阈值 ----
        tab2 = ttk.Frame(nb, padding=(8, 8))
        nb.add(tab2, text="检测阈值")

        def _spin_row(parent, label, var, from_, to, suffix, inc=1):
            f = ttk.Frame(parent)
            f.pack(fill=tk.X, pady=(0, 6))
            ttk.Label(f, text=label, width=10, anchor=tk.E).pack(side=tk.LEFT, padx=(0, 4))
            ttk.Spinbox(f, from_=from_, to=to, textvariable=var,
                        width=6, format="%.0f" if isinstance(from_, int) else "%.1f",
                        increment=inc).pack(side=tk.LEFT)
            ttk.Label(f, text=suffix, foreground="gray").pack(side=tk.LEFT, padx=(4, 0))

        _spin_row(tab2, "近距阈值:", self.var_near_threshold, 5, 100,
                  "%（检测框占比达到此值触发警示）", 5)
        _spin_row(tab2, "远距阈值:", self.var_far_threshold, 1, 50,
                  "%（检测框小于此值判定为远处）", 5)
        _spin_row(tab2, "确认帧数:", self.var_approach_frames, 1, 30,
                  "（连续确认帧数，越大越稳定）")
        _spin_row(tab2, "增长比:", self.var_growth_ratio, 1.1, 5.0,
                  "x（面积增长倍数，超此值判定靠近中）", 0.1)
        _spin_row(tab2, "冷却时间:", self.var_cooldown, 1, 60,
                  "秒（触发后多久不重复弹窗）")
        _spin_row(tab2, "置信度:", self.var_conf_threshold, 0.1, 1.0,
                  "（YOLO检测下限，越高误报越少）", 0.1)

        # ---- 按钮 ----
        btn = ttk.Frame(cfg_frame)
        btn.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(btn, text="保存=应用当前 | 开始检测=保存+后台",
                  foreground="gray").pack(side=tk.LEFT)
        ttk.Button(btn, text="开始检测", command=self._on_start_detect).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn, text="保存", command=self._on_save).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn, text="退出", command=self._on_quit).pack(side=tk.RIGHT)

        # ---- 底栏：运行日志（通栏） ----
        log_frame = ttk.LabelFrame(self.root, text="运行日志", padding=5)
        log_frame.pack(fill=tk.BOTH, side=tk.BOTTOM, padx=10, pady=(4, 5))

        self.log_widget = scrolledtext.ScrolledText(
            log_frame, height=6, wrap=tk.WORD, state=tk.NORMAL,
            font=("Consolas", 8), bg="#1e1e1e", fg="#d4d4d4"
        )
        self.log_widget.pack(fill=tk.BOTH, expand=True)

        # 挂载 UI 日志 handler
        self._ui_log_handler = TkLogHandler(self.log_widget)
        self._ui_log_handler.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
        self._ui_log_handler.setFormatter(fmt)
        _logger.addHandler(self._ui_log_handler)

        # 加载配置值到 UI
        self._load_config_to_ui()
        # 枚举摄像头
        self._refresh_cameras()
        print("【UI】控件构建完成", flush=True)

    # ========================================================
    # 摄像头列表
    # ========================================================
    def _refresh_cameras(self):
        """刷新摄像头列表（仅枚举，不加载模型）"""
        print("【UI】正在枚举摄像头...", flush=True)
        available = []
        try:
            for i in range(10):
                try:
                    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                    if cap.isOpened():
                        ret, _ = cap.read()
                        if ret:
                            available.append(i)
                            print(f"【UI】发现摄像头 #{i}", flush=True)
                        cap.release()
                except Exception as e:
                    print(f"【UI】枚举摄像头 #{i} 出错: {e}", flush=True)
                    try:
                        cap.release()
                    except Exception:
                        pass
        except Exception as e:
            print(f"【UI】摄像头枚举异常: {e}", flush=True)

        self.camera_options = [(cid, f"摄像头 #{cid}") for cid in available]
        values = [t for _, t in self.camera_options]
        try:
            self.camera_combo["values"] = values
        except Exception as e:
            print(f"【UI】设置摄像头列表失败: {e}", flush=True)

        if values:
            saved = self.config.get("camera_id", 0)
            found = None
            for cid, t in self.camera_options:
                if cid == saved:
                    found = t
                    break
            new_val = found or values[0]
            old_val = self.selected_camera.get()
            self.selected_camera.set(new_val)
            try:
                self.status_label.config(text="状态: 等待检测启动...")
            except Exception:
                pass
            if new_val != old_val and self.detector is not None:
                print("【UI】摄像头列表变更，自动切换...", flush=True)
                self._on_camera_changed()
        else:
            self.selected_camera.set("未检测到摄像头")
            try:
                self.status_label.config(text="状态: 无可用摄像头")
            except Exception:
                pass

    def _get_selected_camera_id(self):
        """从 combobox 文本反查摄像头 ID"""
        try:
            sel = self.selected_camera.get()
            for cid, t in self.camera_options:
                if t == sel:
                    return cid
        except Exception as e:
            print(f"【UI】获取摄像头ID失败: {e}", flush=True)
        return -1

    def _get_resolution_labels(self):
        """分辨率选项列表"""
        return ["640x480 (推荐)", "1280x720", "1920x1080"]

    def _parse_resolution(self, label):
        """
        解析分辨率字符串为 (width, height)
        "640x480 (推荐)" → (640, 480)
        """
        try:
            num_part = label.split("x")[0].strip()
            w = int(num_part)
            h = int(label.split("x")[1].split()[0].strip())
            return w, h
        except Exception:
            return 640, 480

    def _on_camera_changed(self, event=None):
        """摄像头选择变更时自动切换"""
        cam_id = self._get_selected_camera_id()
        if cam_id < 0:
            return
        print(f"【UI】切换摄像头 → #{cam_id}", flush=True)
        self._stop_detection()
        self._start_detection()

    # ========================================================
    # 配置 加载 / 保存
    # ========================================================
    def _load_config_to_ui(self):
        """把配置文件值填到 UI"""
        try:
            self.detection_fps.set(self.config.get("detection_fps", 10))
            # 分辨率
            w = self.config.get("frame_width", 640)
            h = self.config.get("frame_height", 480)
            res_key = f"{w}x{h}"
            res_labels = self._get_resolution_labels()
            self.resolution_combo["values"] = res_labels
            found = res_key
            if res_key not in res_labels:
                # 非标准分辨率 → 用最接近的
                found = res_labels[0]
            self.resolution_var.set(found)
            # 弹窗
            self.alert_title_var.set(self.config.get("alert_title", "人员靠近警示"))
            msg = self.config.get("alert_message", "检测到有人从远处走近\n请注意周围安全")
            self.alert_msg_var.set(msg)
            self.msg_text.insert("1.0", msg)
            # 阈值
            self.var_near_threshold.set(self.config.get("area_near_threshold", 0.20) * 100)
            self.var_far_threshold.set(self.config.get("area_far_threshold", 0.10) * 100)
            self.var_approach_frames.set(self.config.get("approach_frames", 5))
            self.var_growth_ratio.set(self.config.get("area_growth_ratio", 1.5))
            self.var_cooldown.set(self.config.get("cooldown_seconds", 10))
            self.var_conf_threshold.set(self.config.get("confidence_threshold", 0.5))
        except Exception as e:
            print(f"【UI】加载配置到界面失败: {e}", flush=True)

    def _save_config(self):
        """把 UI 值写回配置并持久化"""
        try:
            self.config.set("camera_id", self._get_selected_camera_id())
            self.config.set("detection_fps", self.detection_fps.get())
            w, h = self._parse_resolution(self.resolution_var.get())
            self.config.set("frame_width", w)
            self.config.set("frame_height", h)
            self.config.set("alert_title", self.alert_title_var.get())
            self.config.set("alert_message", self.msg_text.get("1.0", "end-1c"))
            self.config.set("area_near_threshold", self.var_near_threshold.get() / 100.0)
            self.config.set("area_far_threshold", self.var_far_threshold.get() / 100.0)
            self.config.set("approach_frames", self.var_approach_frames.get())
            self.config.set("area_growth_ratio", self.var_growth_ratio.get())
            self.config.set("cooldown_seconds", self.var_cooldown.get())
            self.config.set("confidence_threshold", self.var_conf_threshold.get())
            self.config.save_config()
            print("【配置】已保存", flush=True)
        except Exception as e:
            print(f"【配置】保存失败: {e}", flush=True)

    # ========================================================
    # 按钮回调
    # ========================================================
    def _on_save(self):
        """「保存」→ 保存配置并应用参数到当前窗口"""
        if self._get_selected_camera_id() < 0:
            messagebox.showwarning("警告", "请先选择可用摄像头")
            return
        self._save_config()
        print("【保存】配置已保存，应用参数到当前窗口...", flush=True)
        # 重启检测以应用新参数（摄像头、帧率等在当前窗口生效）
        self._stop_detection()
        self._start_detection()
        messagebox.showinfo("提示", "配置已保存，参数已生效")

    def _on_start_detect(self):
        """「开始检测」→ 保存配置并进入后台托盘模式"""
        if self._get_selected_camera_id() < 0:
            messagebox.showwarning("警告", "请先选择可用摄像头")
            return
        self._save_config()
        messagebox.showinfo("提示", "配置已保存，系统将在后台运行")
        self._hide_to_tray()

    def _on_quit(self):
        """「退出」按钮"""
        print("【退出】用户点击退出按钮", flush=True)
        self._cleanup()
        try:
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    def _on_window_close(self):
        """窗口关闭按钮 → 隐藏到托盘"""
        self._hide_to_tray()

    # ========================================================
    # 隐藏 / 显示 切换
    # ========================================================
    def _hide_to_tray(self):
        """隐藏窗口，进入后台托盘模式"""
        print("【模式切换】进入后台托盘模式", flush=True)
        self._ui_active = False       # 停止 UI 刷新（防止 _ui_refresh 复活定时器）
        self._stop_detection()
        try:
            self.root.withdraw()
        except Exception as e:
            print(f"【模式切换】withdraw 失败: {e}", flush=True)

        # 启动后台检测
        self._stop_event_bg.clear()
        self.background_thread = threading.Thread(
            target=self._background_loop, daemon=True, name="BackgroundDetect"
        )
        self.background_thread.start()
        print("【模式切换】后台检测线程已启动", flush=True)

        # 系统托盘
        self.tray = self._create_tray()
        if HAS_SYSTRAY and self.tray:
            threading.Thread(target=self.tray.run, daemon=True, name="TrayIcon").start()
            print("【模式切换】系统托盘已显示", flush=True)
        else:
            print("【模式切换】未启用托盘，后台运行中", flush=True)

    def _show_from_tray(self, icon):
        """从托盘打开配置窗口"""
        print("【模式切换】从托盘恢复配置窗口", flush=True)
        try:
            icon.stop()
        except Exception as e:
            print(f"【模式切换】停止托盘图标失败: {e}", flush=True)

        # 停止后台检测
        if self.background_thread:
            print("【模式切换】停止后台检测...", flush=True)
            self._stop_event_bg.set()
            self.background_thread.join(timeout=2.0)
            self.background_thread = None
            print("【模式切换】后台检测已停止", flush=True)

        # 重新显示窗口
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            print("【模式切换】窗口已恢复", flush=True)
        except Exception as e:
            print(f"【模式切换】恢复窗口失败: {e}", flush=True)

        # 重新枚举摄像头
        self._refresh_cameras()

        # 重新加载配置值
        try:
            self.detection_fps.set(self.config.get("detection_fps", 10))
            w = self.config.get("frame_width", 640)
            h = self.config.get("frame_height", 480)
            res_key = f"{w}x{h}"
            res_labels = self._get_resolution_labels()
            self.resolution_combo["values"] = res_labels
            self.resolution_var.set(res_key if res_key in res_labels else res_labels[0])
            self.alert_title_var.set(self.config.get("alert_title", "人员靠近警示"))
            msg = self.config.get("alert_message", "检测到有人从远处走近\n请注意周围安全")
            self.msg_text.delete("1.0", tk.END)
            self.msg_text.insert("1.0", msg)
            self.var_near_threshold.set(self.config.get("area_near_threshold", 0.20) * 100)
            self.var_far_threshold.set(self.config.get("area_far_threshold", 0.10) * 100)
            self.var_approach_frames.set(self.config.get("approach_frames", 5))
            self.var_growth_ratio.set(self.config.get("area_growth_ratio", 1.5))
            self.var_cooldown.set(self.config.get("cooldown_seconds", 10))
            self.var_conf_threshold.set(self.config.get("confidence_threshold", 0.5))
        except Exception as e:
            print(f"【模式切换】恢复UI值失败: {e}", flush=True)

        # 延迟启动检测
        self.root.after(500, self._start_detection)
        print("【模式切换】已安排检测启动", flush=True)

    # ========================================================
    # 系统托盘
    # ========================================================
    def _create_tray(self):
        """创建系统托盘图标和菜单"""
        if not HAS_SYSTRAY:
            return None
        try:
            img = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse((8, 16, 56, 48), fill=(50, 100, 180))
            draw.ellipse((22, 26, 42, 38), fill=(255, 255, 255))
            draw.ellipse((28, 28, 36, 36), fill=(20, 60, 120))
            menu = (
                item("打开配置", self._show_from_tray),
                item("退出", self._tray_quit),
            )
            return Icon("3eyes", img, "3eyes - 人员检测系统", menu)
        except Exception as e:
            print(f"【托盘】创建失败: {e}", flush=True)
            return None

    def _tray_quit(self, icon):
        """托盘退出"""
        print("【退出】从托盘退出", flush=True)
        try:
            icon.stop()
        except Exception:
            pass
        self._cleanup()
        try:
            self.root.destroy()
        except Exception:
            pass
        sys.exit(0)

    # ========================================================
    # 检测启动 / 停止
    # ========================================================
    def _start_detection(self):
        """启动检测（在窗口显示后调用，模型加载在后台线程）"""
        cam_id = self._get_selected_camera_id()
        if cam_id < 0:
            print("【检测启动】无可用摄像头，跳过", flush=True)
            try:
                self.status_label.config(text="状态: 无可用摄像头")
            except Exception:
                pass
            return

        print(f"【检测启动】准备启动，摄像头 #{cam_id}", flush=True)
        self._stop_event_config.clear()
        self._set_snapshot([], "Status: Loading model...")
        try:
            self.status_label.config(text="状态: 正在加载模型...")
        except Exception:
            pass

        # 缓存 Tk 变量值（避免后台线程访问 Tk 变量）
        try:
            self._cached_title = self.alert_title_var.get() or "警示"
            self._cached_msg = self.msg_text.get("1.0", "end-1c") or "人员靠近"
            self._cached_fps = self.detection_fps.get()
        except Exception as e:
            print(f"【检测启动】缓存变量失败: {e}", flush=True)
            self._cached_title = "警示"
            self._cached_msg = "人员靠近"
            self._cached_fps = 10

        self.detection_thread = threading.Thread(
            target=self._detection_init, daemon=True, name="DetectThread"
        )
        self.detection_thread.start()
        print("【检测启动】后台线程已启动", flush=True)

    def _detection_init(self):
        """后台线程：加载模型 + 打开摄像头 + 进入检测循环"""
        print("【检测线程】开始初始化", flush=True)
        try:
            cam_id = self._get_selected_camera_id()
            print(f"【检测线程】目标摄像头 #{cam_id}", flush=True)

            self.detector = PersonDetector(
                camera_id=cam_id,
                frame_width=self.config.get("frame_width", 640),
                frame_height=self.config.get("frame_height", 480),
                conf_threshold=self.config.get("confidence_threshold", 0.5),
            )

            self.tracker = ApproachTracker(
                area_far_threshold=self.config.get("area_far_threshold", 0.10),
                area_near_threshold=self.config.get("area_near_threshold", 0.20),
                approach_frames=self.config.get("approach_frames", 5),
                area_growth_ratio=self.config.get("area_growth_ratio", 1.5),
                cooldown_seconds=self.config.get("cooldown_seconds", 10),
            )

            self.alert = AlertPopup(
                self.root,
                width=self.config.get("alert_width", 340),
                height=self.config.get("alert_height", 160),
                duration_ms=self.config.get("alert_duration_ms", 6000),
            )

            print("【检测线程】开始加载模型并打开摄像头...", flush=True)
            if not self.detector.start():
                self._set_snapshot([], "Status: Camera failed")
                print("【检测线程】摄像头启动失败", flush=True)
                return

            print("【检测线程】摄像头就绪", flush=True)
            self._set_snapshot([], "Status: Running...")

            # 在主线程启动 UI 刷新定时器
            self._ui_active = True
            self.root.after(0, self._schedule_ui_update)

            # 进入检测循环
            self._detection_loop()

        except Exception as e:
            print(f"【检测线程】致命异常:\n{traceback.format_exc()}", flush=True)

    def _stop_detection(self):
        """停止配置窗口的检测"""
        print("【检测停止】正在停止...", flush=True)
        self._stop_event_config.set()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self.detection_thread:
            print("【检测停止】等待检测线程退出...", flush=True)
            self.detection_thread.join(timeout=2.0)
            self.detection_thread = None
        if self.detector:
            try:
                self.detector.release()
            except Exception as e:
                print(f"【检测停止】释放 detector 失败: {e}", flush=True)
            self.detector = None
        print("【检测停止】完成", flush=True)

    def _cleanup(self):
        """清理所有资源"""
        print("【清理】开始...", flush=True)
        self._stop_detection()
        self._stop_event_bg.set()
        if self.background_thread:
            print("【清理】等待后台线程退出...", flush=True)
            self.background_thread.join(timeout=2.0)
            self.background_thread = None
        print("【清理】完成", flush=True)

    # ========================================================
    # 检测循环（后台线程）
    # ========================================================
    def _detection_loop(self):
        """检测循环 —— 后台线程，全速读帧供 UI 渲染，YOLO 按配置间隔抽帧"""
        fps = getattr(self, "_cached_fps", 10)
        interval = 1.0 / max(fps, 1)
        last_detect_t = 0.0          # 上次 YOLO 检测时间
        frame_count = 0              # 总读取帧数(=摄像头帧数)
        detect_count = 0             # 总检测次数
        detect_1s = 0                # 近 1 秒内的检测次数
        err_count = 0
        fps_timer = time.time()
        actual_fps = 0
        start_t = time.time()

        print(f"【检测循环】启动, 检测FPS={fps}, 每秒抽帧检测{fps}次, 摄像头全速读取供UI渲染", flush=True)

        while not self._stop_event_config.is_set():
            try:
                # 全速读帧 —— 摄像头出多少读多少，保证 UI 预览丝滑
                frame = self.detector.read_frame()
                if frame is None:
                    time.sleep(0.005)
                    continue

                frame_count += 1
                now = time.time()

                # 每秒刷新一次实际检测 FPS
                if now - fps_timer >= 1.0:
                    actual_fps = detect_1s
                    detect_1s = 0
                    fps_timer = now

                # 按配置间隔抽帧做 YOLO 检测（与摄像头帧率完全解耦）
                if now - last_detect_t >= interval:
                    last_detect_t = now
                    detect_count += 1
                    detect_1s += 1

                    try:
                        detections = self.detector.detect(frame)
                        state, should_alert = self.tracker.update(detections, frame.shape)
                    except Exception as e:
                        err_count += 1
                        if err_count <= 3:
                            print(f"【检测循环】YOLO/追踪异常: {e}", flush=True)
                            if err_count == 3:
                                print(f"【检测循环】连续出错 {err_count} 次，后续静默", flush=True)
                        time.sleep(0.05)
                        continue
                    else:
                        err_count = 0

                    # 线程安全地保存快照
                    self._set_snapshot(
                        detections,
                        f"Status: {state.value}  Detected: {len(detections)}  FPS: {actual_fps}"
                    )

                    if should_alert:
                        title = getattr(self, "_cached_title", "警示")
                        msg = getattr(self, "_cached_msg", "人员靠近")
                        try:
                            self.alert.show(msg, title)
                            print(f"【弹窗】已触发: {title}", flush=True)
                        except Exception as e:
                            print(f"【弹窗】触发失败: {e}", flush=True)

                # 全速入队供 UI 渲染
                try:
                    self.frame_queue.put(frame, block=False)
                except queue.Full:
                    pass

            except Exception as e:
                err_count += 1
                if err_count <= 3:
                    print(f"【检测循环】读帧异常: {e}", flush=True)
                time.sleep(0.05)

        elapsed = time.time() - start_t
        print(f"【检测循环】退出, 共检测 {detect_count} 次, 摄像头出帧 {frame_count}, 运行 {elapsed:.0f}s", flush=True)
        try:
            self.detector.release()
        except Exception:
            pass

    # ========================================================
    # 后台检测循环（无预览窗口）
    # ========================================================
    def _background_loop(self):
        """后台检测 —— 无 UI，仅弹窗。每轮检测后释放摄像头以消除 DSHOW 持续开销。"""
        print("【后台检测】开始...", flush=True)
        try:
            cam_id = self.config.get("camera_id", 0)
            res_w = self.config.get("frame_width", 640)
            res_h = self.config.get("frame_height", 480)
            conf_th = self.config.get("confidence_threshold", 0.5)
            print(f"【后台检测】摄像头 #{cam_id}, {res_w}x{res_h}", flush=True)

            # 追踪器和弹窗复用（不需要每轮重建）
            tracker = ApproachTracker(
                area_far_threshold=self.config.get("area_far_threshold", 0.10),
                area_near_threshold=self.config.get("area_near_threshold", 0.20),
                approach_frames=self.config.get("approach_frames", 5),
                area_growth_ratio=self.config.get("area_growth_ratio", 1.5),
                cooldown_seconds=self.config.get("cooldown_seconds", 10),
            )

            alert = AlertPopup(
                self.root,
                width=self.config.get("alert_width", 340),
                height=self.config.get("alert_height", 160),
                duration_ms=self.config.get("alert_duration_ms", 6000),
            )

            fps = self.config.get("detection_fps", 10)
            interval = 1.0 / max(fps, 1)
            detect_count = 0
            start_t = time.time()

            # 模型只加载一次
            from detector import PersonDetector as PD
            print("【后台检测】正在加载 YOLO 模型...", flush=True)
            model_detector = PD(
                camera_id=cam_id, frame_width=res_w, frame_height=res_h,
                conf_threshold=conf_th,
            )
            model_detector._load_model_only()  # 只加载模型，不连接摄像头
            model = model_detector.model
            print("【后台检测】模型就绪, 开始轮询...", flush=True)

            print(f"【后台检测】FPS={fps}, 每轮: 开摄像头→取帧→关摄像头→YOLO", flush=True)

            while not self._stop_event_bg.is_set():
                try:
                    # 1. 短暂打开摄像头获取一帧
                    import cv2 as _cv2
                    cap = _cv2.VideoCapture(cam_id, _cv2.CAP_DSHOW)
                    cap.set(_cv2.CAP_PROP_FRAME_WIDTH, res_w)
                    cap.set(_cv2.CAP_PROP_FRAME_HEIGHT, res_h)
                    time.sleep(0.25)  # 等 DSHOW 稳定
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        try:
                            ret, frame = cap.read()  # 再试一次
                        except Exception:
                            pass
                    cap.release()
                    cap = None

                    if frame is None:
                        time.sleep(1.0)
                        continue

                    detect_count += 1

                    # 2. YOLO 检测
                    try:
                        dets = model_detector._detect_with_model(model, frame)
                        state, should_alert = tracker.update(dets, frame.shape)
                    except Exception as e:
                        print(f"【后台检测】YOLO异常: {e}", flush=True)
                        time.sleep(0.1)
                        continue

                    # 3. 弹窗
                    if should_alert:
                        title = self.config.get("alert_title", "警示")
                        msg = self.config.get("alert_message", "人员靠近")
                        try:
                            alert.show(msg, title)
                            print(f"【后台弹窗】已触发: {title}", flush=True)
                        except Exception as e:
                            print(f"【后台弹窗】触发失败: {e}", flush=True)

                    # 4. 休眠到下一个检测时刻（相对于 start_t 的绝对时间点）
                    next_tick_time = start_t + detect_count * interval
                    remain = next_tick_time - time.time()
                    if remain > 0:
                        time.sleep(remain)

                except Exception as e:
                    print(f"【后台检测】轮询异常: {e}", flush=True)
                    time.sleep(1.0)

            elapsed = time.time() - start_t
            print(f"【后台检测】退出, 共检测 {detect_count} 次, 运行 {elapsed:.0f}s", flush=True)

        except Exception as e:
            print(f"【后台检测】致命异常:\n{traceback.format_exc()}", flush=True)

    # ========================================================
    # UI 刷新（主线程 after 回调）
    # ========================================================
    def _schedule_ui_update(self):
        """调度下一次 UI 刷新"""
        if not getattr(self, "_ui_active", True):
            return
        try:
            self._after_id = self.root.after(66, self._ui_refresh)  # ~15 FPS
        except Exception as e:
            print(f"【UI刷新】调度失败: {e}", flush=True)

    def _ui_refresh(self):
        """在主线程中取帧 → 绘制检测框 → 更新预览"""
        if not getattr(self, "_ui_active", True):
            return
        try:
            frame = self.frame_queue.get(block=False)
        except queue.Empty:
            self._schedule_ui_update()
            return
        except Exception as e:
            print(f"【UI刷新】取帧异常: {e}", flush=True)
            self._schedule_ui_update()
            return

        try:
            display = frame.copy()

            # 读取快照
            snaps, state_txt = self._get_snapshot()

            # 绘制检测框
            for i, det in enumerate(snaps):
                try:
                    conf = det.get("confidence", 0)
                    x1, y1 = det.get("x1", 0), det.get("y1", 0)
                    x2, y2 = det.get("x2", 0), det.get("y2", 0)

                    if conf > 0.8:
                        color = (100, 255, 100)
                    elif conf > 0.5:
                        color = (100, 220, 220)
                    else:
                        color = (200, 100, 100)

                    cv2.rectangle(display, (x1, y1), (x2, y2), color, 2)

                    area = det.get("area", 0)
                    ratio = area / (frame.shape[0] * frame.shape[1]) if frame.shape[0] > 0 else 0
                    label = f"#{i+1} {conf:.2f} {ratio:.1%}"
                    cv2.putText(display, label, (x1, y1 - 6),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2)
                except Exception as e:
                    print(f"【UI刷新】绘制检测框 #{i} 失败: {e}", flush=True)

            # 状态文字
            cv2.putText(display, state_txt, (8, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (220, 220, 220), 2)

            # 转 PIL → ImageTk
            rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            pil.thumbnail((340, 255), Image.LANCZOS)  # 匹配预览标签 4:3 比例

            if ImageTk is None:
                self._schedule_ui_update()
                return

            imgtk = ImageTk.PhotoImage(pil)

            self.preview_label.config(image=imgtk)
            self.preview_label.image = imgtk
            self.status_label.config(text=state_txt)

        except tk.TclError as e:
            print(f"【UI刷新】Tk 错误（窗口可能已销毁）: {e}", flush=True)
        except Exception as e:
            print(f"【UI刷新】异常:\n{traceback.format_exc()}", flush=True)
        finally:
            self._schedule_ui_update()

    # ========================================================
    # 运行
    # ========================================================
    def run(self):
        """启动应用"""
        print("=" * 56, flush=True)
        print("  3eyes - 人员靠近检测警示系统", flush=True)
        print("=" * 56, flush=True)
        print(f"  配置文件: {self.config.config_path}", flush=True)
        print(flush=True)

        # 延迟 500ms 启动检测（让窗口先完整渲染）
        print("【运行】窗口即将显示, 500ms 后启动检测", flush=True)
        self.root.after(500, self._start_detection)
        self.root.mainloop()


# ============================================================
# 入口
# ============================================================
if __name__ == "__main__":
    print("【主程序】启动", flush=True)
    App().run()
    print("【主程序】退出", flush=True)
