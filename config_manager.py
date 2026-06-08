"""
配置管理模块
负责配置的加载、保存和管理
"""
import os
import json
import platform


class ConfigManager:
    """配置管理器"""
    
    # 默认配置
    DEFAULT_CONFIG = {
        "camera_id": 0,
        "frame_width": 640,
        "frame_height": 480,
        "detection_fps": 10,
        "confidence_threshold": 0.5,
        "area_far_threshold": 0.10,
        "area_near_threshold": 0.20,
        "approach_frames": 5,
        "area_growth_ratio": 1.5,
        "cooldown_seconds": 10,
        "alert_duration_ms": 6000,
        "alert_title": "人员靠近警示",
        "alert_message": "检测到有人从远处走近\n请注意周围安全",
        "alert_width": 340,
        "alert_height": 160,
        "show_debug": True
    }
    
    def __init__(self):
        self.config = {}
        self.config_path = self._get_config_path()
        self.load_config()
    
    def _get_config_path(self):
        """获取配置文件路径"""
        if platform.system() == "Windows":
            app_data = os.environ.get("APPDATA", ".")
            config_dir = os.path.join(app_data, "3eyes")
        else:
            config_dir = os.path.join(os.path.expanduser("~"), ".3eyes")
        
        os.makedirs(config_dir, exist_ok=True)
        return os.path.join(config_dir, "config.json")
    
    def load_config(self):
        """加载配置文件"""
        self.config = self.DEFAULT_CONFIG.copy()
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    # 合并配置（保留默认值，覆盖已保存的值）
                    self.config.update(saved)
                print(f"[配置] 已加载配置: {self.config_path}")
            except Exception as e:
                print(f"[配置] 加载配置失败: {e}")
        else:
            print(f"[配置] 使用默认配置")
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            print(f"[配置] 已保存配置: {self.config_path}")
            return True
        except Exception as e:
            print(f"[配置] 保存配置失败: {e}")
            return False
    
    def get(self, key, default=None):
        """获取配置项"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """设置配置项"""
        self.config[key] = value
    
    def get_all(self):
        """获取所有配置"""
        return self.config.copy()
    
    def update(self, new_config):
        """批量更新配置"""
        self.config.update(new_config)
