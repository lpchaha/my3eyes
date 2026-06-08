"""
靠近追踪模块
通过检测框面积变化判断人员是否从远处走近
"""
import time
import collections
from enum import Enum


class ApproachState(Enum):
    """靠近状态枚举"""
    IDLE = "idle"               # 画面中无人
    FAR = "far"                 # 检测到人，距离较远
    APPROACHING = "approaching" # 人员正在靠近
    NEAR = "near"               # 人员已经靠近（触发警示）


class ApproachTracker:
    """
    靠近追踪器
    使用状态机追踪人员从远到近的变化过程
    """

    def __init__(self, area_far_threshold=0.10, area_near_threshold=0.20,
                 approach_frames=5, area_growth_ratio=1.5,
                 cooldown_seconds=10, history_size=5):
        """
        初始化追踪器

        Args:
            area_far_threshold:  面积占比低于此值视为"远"
            area_near_threshold: 面积占比高于此值视为"近"
            approach_frames:     连续靠近帧数阈值
            area_growth_ratio:   面积增长比例阈值
            cooldown_seconds:    警示冷却时间（秒）
            history_size:        面积历史队列大小
        """
        self.area_far_threshold = area_far_threshold
        self.area_near_threshold = area_near_threshold
        self.approach_frames = approach_frames
        self.area_growth_ratio = area_growth_ratio
        self.cooldown_seconds = cooldown_seconds
        self.history_size = history_size

        # 当前状态
        self.state = ApproachState.IDLE
        # 面积历史队列（用于平滑和趋势判断）
        self.area_history = collections.deque(maxlen=history_size)
        # 连续靠近帧计数
        self.approach_count = 0
        # 上次触发警示的时间戳
        self.last_alert_time = 0.0
        # 历史最小面积（用于判断增长比例）
        self.min_area_in_track = 0.0
        # 当前帧的画面尺寸
        self.frame_area = 640 * 480

    def update(self, detections, frame_shape=None):
        """
        根据当前帧的检测结果更新状态

        Args:
            detections: detector.detect() 返回的检测结果列表
            frame_shape: 帧的形状 (height, width, channels)，用于计算面积占比

        Returns:
            tuple: (ApproveState, bool) — 当前状态和是否需要弹窗
        """
        if frame_shape is not None:
            self.frame_area = frame_shape[0] * frame_shape[1]

        # 没有检测到人：回到 IDLE，重置
        if not detections:
            self._reset()
            return self.state, False

        # 取最大的人（面积最大）
        largest_person = detections[0]
        current_area = largest_person["area"]
        area_ratio = current_area / self.frame_area

        # 更新面积历史（移动平均）
        self.area_history.append(current_area)
        smoothed_area = (sum(self.area_history) / len(self.area_history)
                         if self.area_history else current_area)
        smoothed_ratio = smoothed_area / self.frame_area

        # 状态机逻辑
        new_state = self._determine_state(area_ratio, smoothed_ratio, current_area)

        # 检查是否需要弹窗（NEAR 状态下，冷却时间到了就弹）
        should_alert = False
        if new_state == ApproachState.NEAR and self._can_alert():
            should_alert = True
            self.last_alert_time = time.time()

        self.state = new_state
        return self.state, should_alert

    def _determine_state(self, area_ratio, smoothed_ratio, current_area):
        """
        根据面积占比和趋势判断当前状态

        Args:
            area_ratio: 原始面积占比
            smoothed_ratio: 平滑后的面积占比
            current_area: 当前检测框面积（像素）

        Returns:
            AppendState: 判定的新状态
        """
        # NEAR 判断：原始值或平滑值任一达到阈值即可
        # 这样可以快速响应突然靠近的情况
        if area_ratio >= self.area_near_threshold or smoothed_ratio >= self.area_near_threshold:
            return ApproachState.NEAR

        # FAR 判断：面积 < 远阈值
        elif area_ratio < self.area_far_threshold:
            # 更新历史最小面积（只在 FAR 状态时更新）
            if self.min_area_in_track <= 0 or current_area < self.min_area_in_track:
                self.min_area_in_track = current_area
            return ApproachState.FAR

        # 中间区域（FAR_THRESHOLD <= area < NEAR_THRESHOLD）
        else:
            # 更新历史最小面积
            if self.min_area_in_track <= 0 or current_area < self.min_area_in_track:
                self.min_area_in_track = current_area

            # 判断是否正在靠近
            if self._is_approaching(current_area):
                return ApproachState.APPROACHING
            else:
                return ApproachState.FAR

    def _is_approaching(self, current_area):
        """
        判断人员是否正在靠近

        判定条件：
        1. 当前面积 > 历史最小面积 × 增长比例阈值
        2. 连续 N 帧满足条件

        Args:
            current_area: 当前帧检测框面积

        Returns:
            bool: 是否正在靠近
        """
        if self.min_area_in_track <= 0:
            return False

        # 判断面积是否显著增长
        if current_area >= self.min_area_in_track * self.area_growth_ratio:
            self.approach_count += 1
        else:
            # 增长不够显著，计数递减
            self.approach_count = max(0, self.approach_count - 1)

        return self.approach_count >= self.approach_frames

    def _can_alert(self):
        """
        检查是否可以弹窗（仅判断冷却时间）

        Returns:
            bool: 是否允许弹窗
        """
        if self.last_alert_time <= 0:
            return True
        elapsed = time.time() - self.last_alert_time
        return elapsed >= self.cooldown_seconds

    def _reset(self):
        """重置追踪状态（人员消失时调用）"""
        self.state = ApproachState.IDLE
        self.area_history.clear()
        self.approach_count = 0
        self.min_area_in_track = 0.0

    def get_state_info(self):
        """
        获取当前状态的描述信息（用于预览窗口显示）

        Returns:
            str: 状态描述文字
        """
        info = f"State: {self.state.value}"
        if self.area_history:
            avg_area = sum(self.area_history) / len(self.area_history)
            ratio = avg_area / self.frame_area
            info += f" | Area: {ratio:.2%}"
        if self.state == ApproachState.NEAR:
            cooldown = time.time() - self.last_alert_time
            if cooldown < self.cooldown_seconds:
                info += f" | Cool: {cooldown:.1f}s"
        return info
