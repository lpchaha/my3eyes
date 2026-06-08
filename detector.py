"""
人员检测模块
负责摄像头采集和 YOLOv8 人员检测
"""
import cv2
import numpy as np
from ultralytics import YOLO


class PersonDetector:
    """
    人员检测器
    封装摄像头读取和 YOLO 模型推理，对外提供简洁接口
    """

    def __init__(self, model_name="yolov8n.pt", camera_id=0,
                 frame_width=640, frame_height=480, conf_threshold=0.5):
        """
        初始化检测器

        Args:
            model_name: YOLO 模型名称或路径
            camera_id: 摄像头设备 ID
            frame_width: 帧宽度
            frame_height: 帧高度
            conf_threshold: 检测置信度阈值
        """
        self.model_name = model_name
        self.camera_id = camera_id
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.conf_threshold = conf_threshold
        self.model = None
        self.cap = None

    def list_cameras(self):
        """
        枚举所有可用的摄像头设备
        
        Returns:
            list: 可用摄像头索引列表
        """
        available = []
        print("[检测器] 正在枚举可用摄像头...")
        
        # 尝试常见的摄像头索引（0-9）
        for i in range(10):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    available.append(i)
                    print(f"[检测器] 发现摄像头 #{i}")
                cap.release()
        
        return available

    def start(self):
        """
        启动检测器：加载 YOLO 模型并打开摄像头

        Returns:
            bool: 是否成功启动
        """
        print(f"[检测器] 正在加载模型 {self.model_name} ...")
        self.model = YOLO(self.model_name)
        print("[检测器] 模型加载完成")

        # 先枚举摄像头
        cameras = self.list_cameras()
        if not cameras:
            print("[检测器] 错误：未发现可用摄像头")
            return False
        
        # 如果指定的摄像头ID不在可用列表中，使用第一个可用的
        if self.camera_id not in cameras:
            print(f"[检测器] 警告：指定的摄像头 #{self.camera_id} 不可用")
            print(f"[检测器] 可用摄像头: {cameras}")
            self.camera_id = cameras[0]
            print(f"[检测器] 自动选择摄像头 #{self.camera_id}")

        print(f"[检测器] 正在打开摄像头 #{self.camera_id} ...")
        
        # 尝试多个后端打开摄像头
        backends = [
            (cv2.CAP_DSHOW, "DirectShow"),
            (cv2.CAP_MSMF, "Media Foundation"),
            (cv2.CAP_ANY, "Auto"),
        ]
        
        for backend, name in backends:
            self.cap = cv2.VideoCapture(self.camera_id, backend)
            if self.cap.isOpened():
                # 验证能否读取帧
                ret, _ = self.cap.read()
                if ret:
                    print(f"[检测器] 成功使用 {name} 后端打开摄像头")
                    break
                self.cap.release()
        
        if self.cap is None or not self.cap.isOpened():
            print("[检测器] 错误：无法打开摄像头")
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        
        # 获取实际分辨率
        actual_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[检测器] 摄像头已就绪，分辨率 {actual_w}x{actual_h}")
        return True

    def _load_model_only(self):
        """
        仅加载 YOLO 模型，不连接摄像头。
        用于后台模式：模型常驻，摄像头按需开关。
        """
        print(f"[检测器] 正在加载模型 {self.model_name} ...")
        self.model = YOLO(self.model_name)
        print("[检测器] 模型加载完成")

    def _detect_with_model(self, model, frame):
        """
        使用已加载的 model 对 frame 执行人员检测。
        （与 detect() 逻辑相同，但可以传入外部模型）
        """
        results = model(frame, verbose=False, conf=self.conf_threshold,
                        classes=[0])
        persons = []
        if len(results) > 0 and results[0].boxes is not None:
            boxes = results[0].boxes
            h, w = frame.shape[:2]
            for i in range(len(boxes)):
                cls = int(boxes.cls[i])
                if cls != 0:
                    continue
                conf = float(boxes.conf[i])
                xyxy = boxes.xyxy[i].cpu().numpy()
                x1, y1, x2, y2 = map(int, xyxy)
                b_w, b_h = x2 - x1, y2 - y1
                persons.append({
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                    "width": b_w, "height": b_h,
                    "area": b_w * b_h,
                    "confidence": conf
                })
        return persons

    def read_frame(self):
        """
        从摄像头读取一帧图像

        Returns:
            np.ndarray or None: 图像帧，读取失败返回 None
        """
        if self.cap is None:
            return None
        ret, frame = self.cap.read()
        if not ret:
            return None
        return frame

    def detect(self, frame):
        """
        对给定帧执行人员检测

        Args:
            frame: BGR 格式的 numpy 图像数组

        Returns:
            list[dict]: 检测到的人员列表，每项包含:
                {
                    "x1": int, "y1": int, "x2": int, "y2": int,
                    "width": int, "height": int,
                    "area": float,      # 检测框像素面积
                    "confidence": float # 置信度
                }
            按面积从大到小排列
        """
        if self.model is None or frame is None:
            return []

        # 使用 YOLO 检测，仅检测 person 类（COCO class_id=0）
        results = self.model(
            frame,
            classes=[0],           # 仅检测 person
            conf=self.conf_threshold,
            verbose=False          # 不打印日志
        )

        detections = []
        if results and len(results) > 0:
            boxes = results[0].boxes
            if boxes is not None:
                for box in boxes:
                    x1, y1, x2, y2 = box.xyxy[0].tolist()
                    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                    w = x2 - x1
                    h = y2 - y1
                    area = float(w * h)
                    conf = float(box.conf[0])

                    detections.append({
                        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                        "width": w, "height": h,
                        "area": area,
                        "confidence": conf
                    })

        # 按面积从大到小排序（最大的人排最前）
        detections.sort(key=lambda d: d["area"], reverse=True)
        return detections

    def draw_detections(self, frame, detections, state_info=""):
        """
        在画面上绘制检测框和状态信息（用于预览窗口）

        Args:
            frame: 原始图像帧
            detections: detect() 返回的检测结果列表
            state_info: 状态文字（如 "FAR", "APPROACHING", "NEAR"）

        Returns:
            np.ndarray: 绘制后的图像帧
        """
        display = frame.copy()

        # 绘制每个检测框
        for i, det in enumerate(detections):
            color = (100, 200, 100)  # 绿色框
            if i == 0:
                color = (200, 200, 100)  # 最大的人用青色框突出显示

            cv2.rectangle(display,
                          (det["x1"], det["y1"]),
                          (det["x2"], det["y2"]),
                          color, 2)

            label = f"Person {i+1} ({det['confidence']:.2f})"
            cv2.putText(display, label,
                        (det["x1"], det["y1"] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

        # 绘制状态信息
        if state_info:
            cv2.putText(display, f"State: {state_info}",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (200, 200, 200), 2)

        return display

    def release(self):
        """释放摄像头和模型资源"""
        if self.cap is not None:
            self.cap.release()
            print("[检测器] 摄像头已释放")
        self.model = None
        self.cap = None
