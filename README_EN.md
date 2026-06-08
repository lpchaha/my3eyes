# 3eyes - Person Approach Detection & Alert System

A real-time camera-based person detection system powered by YOLOv8. Automatically pops up a desktop alert when someone approaches from a distance.

## Features

- **Real-time Person Detection** — YOLOv8n model, runs smoothly on CPU
- **Approach Tracking** — Detects approach behavior via bounding box area changes
- **Desktop Alert Popup** — Grey-themed Tkinter popup, supports system tray background mode
- **GUI Configuration** — Visual adjustment of camera, detection thresholds, and alert parameters
- **Persistent Config** — Settings saved to JSON file, auto-loaded on restart

## Project Structure

```
├── app.py              # Main entry point (GUI + system tray)
├── config_manager.py   # Config management (load/save JSON config)
├── detector.py         # Person detection module (OpenCV + YOLOv8)
├── tracker.py          # Approach tracking module (state machine)
├── alert.py            # Alert popup module (Tkinter)
├── run.bat             # Windows one-click launcher
├── requirements.txt    # Python dependencies
├── yolov8n.pt          # YOLOv8 Nano model weights (auto-downloaded on first run)
└── logs/               # Runtime log directory
```

## Quick Start

### Requirements

- Python 3.8+
- Windows OS
- Camera device

### Installation & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the application
python app.py
```

Or double-click `run.bat` to launch.

### Controls

| Action | Description |
|------|------|
| Click "Start Detection" | Save config and switch to background tray mode |
| Click "Save" | Save config and apply parameters to current preview |
| Tray right-click → Open Config | Restore the configuration window |
| Tray right-click → Exit | Fully quit the application |

## Design Rationale

### Technology Choices

| Module | Technology | Rationale |
|------|------|----------|
| Camera Capture | OpenCV (cv2) | Cross-platform, high performance, supports DirectShow/Media Foundation backends |
| Person Detection | Ultralytics YOLOv8n | Nano model only 6MB, 100+ FPS on CPU; COCO pre-trained with person class (class 0), ready out of the box |
| GUI Popup | Tkinter (Python built-in) | Zero extra dependencies, lightweight; `overrideredirect` enables borderless custom windows |
| System Tray | pystray + Pillow | Background persistence with right-click menu for show/hide and exit |
| Config Management | JSON file persistence | No database needed; config stored under `%APPDATA%/3eyes/`, auto-loaded on startup |

### Why Bounding Box Area Instead of Depth Camera

Depth cameras or ranging sensors offer higher accuracy but require additional hardware. This project uses a **monocular RGB camera**, leveraging perspective — objects appear larger when closer. As a person approaches the camera, their YOLO bounding box area gradually increases. Tracking this area trend is sufficient to detect approach behavior without extra hardware.

### Approach Detection State Machine

```
                Person detected, small area
  [IDLE]  ──────────────────────────>  [FAR]
                                         │
                    Area growth exceeds   │
                    threshold, mid-size   │
                                         ▼
                                    [APPROACHING]
                                         │
                    Area further increases │
                    exceeds "near" threshold│
                                         ▼
                                      [NEAR]  ───> Trigger alert popup
                                         │
                    Person disappears     │
                                         ▼
                                      [IDLE]
```

**State Descriptions**:
- **IDLE**: No person detected; reset all tracking data
- **FAR**: Bounding box area < 10% of frame; record historical minimum area as baseline
- **APPROACHING**: Area has grown > 50% from baseline, confirmed over N consecutive frames (default 5)
- **NEAR**: Area > 20% of frame; trigger alert, enter cooldown period

### Debounce & Deduplication

| Mechanism | Implementation | Purpose |
|------|------|------|
| Consecutive Frame Confirmation | State transitions require N consecutive frames meeting criteria; counter decrements on missed frames | Prevent false triggers from single-frame YOLO errors or jitter |
| Moving Average Filter | Maintain area history queue (default 5 frames), use mean value to smooth fluctuations | Filter frame-to-frame bounding box size jitter |
| Cooldown Period | No repeat alerts for N seconds after trigger (default 10s) | Prevent alert spam when a person remains nearby |

### System Architecture

```
┌──────────────────────────────────────────────────┐
│                     app.py                        │
│         (Tkinter GUI + System Tray + Main Loop)    │
├──────────────────────────────────────────────────┤
│                                                   │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐      │
│  │detector.py│   │tracker.py│   │ alert.py │      │
│  │           │   │          │   │          │      │
│  │ Camera    │──>│ State    │──>│ Desktop  │      │
│  │ Capture   │   │ Tracking │   │ Alert    │      │
│  │ YOLO      │   │ Area     │   │ Tkinter  │      │
│  │ Detection │   │ Analysis │   │ Grey Theme│     │
│  └──────────┘   └──────────┘   └──────────┘      │
│                                                   │
│  ┌─────────────────────────┐                      │
│  │    config_manager.py    │                      │
│  │  (JSON Config Persistence)│                    │
│  └─────────────────────────┘                      │
└──────────────────────────────────────────────────┘
```

### GUI Design Highlights

- **Singleton Tk Root**: Only one `tk.Tk()` instance exists application-wide; alerts use `Toplevel` to avoid multi-window conflicts
- **Thread Safety**: YOLO detection runs in a background thread; frames are passed to the main thread via `queue.Queue` for rendering; detection snapshots protected by `threading.Lock`
- **Print Redirection**: All `print()` calls are redirected to logging, simultaneously written to log file and console UI panel for easier debugging
- **Dual Mode**: Window mode provides real-time detection preview; tray mode runs silently in background, camera opens/closes per detection interval to conserve DSHOW resources

### Alert Popup Design (Grey Theme)

A grey color scheme was chosen over traditional red/orange alerts to avoid drawing unnecessary attention or causing alarm in office environments — subtle yet effective.

- Background `#f5f5f5` (light grey), title bar `#757575` (mid grey), button `#9e9e9e`
- Borderless window (`overrideredirect`), always on top (`-topmost`)
- Slide-in animation from bottom-right corner, positioned on the display where the mouse is located
- Supports manual close or auto-dismiss with countdown

## Configuration Parameters

All parameters are adjustable via the GUI and persist automatically:

| Parameter | Default | Description |
|------|------|------|
| Camera ID | 0 | Camera device index |
| Resolution | 640x480 | Processing frame size |
| Detection FPS | 10 | YOLO detection interval |
| Confidence Threshold | 0.5 | Minimum YOLO detection confidence |
| Near Threshold | 20% | Bounding box ratio triggering alert |
| Far Threshold | 10% | Bounding box ratio below this is "far" |
| Confirm Frames | 5 | Consecutive frame confirmation count |
| Growth Ratio | 1.5x | Area growth multiplier |
| Cooldown | 10s | Time before next alert can fire |

## Dependencies

```
ultralytics>=8.0.0    # YOLOv8 object detection
opencv-python>=4.5.0  # Camera capture & image processing
pystray>=0.19.0       # System tray support
Pillow>=10.0.0        # Image processing
```

Tkinter is part of the Python standard library — no additional installation required.
