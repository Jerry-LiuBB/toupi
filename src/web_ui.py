#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import threading
import logging
import queue
import json
import os
import sys
import time
from flask import Flask, render_template_string, jsonify, Response, request

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.scalp_detection import SystemState

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("cv2未安装，实时画面功能不可用")

logger = logging.getLogger(__name__)


class LogStreamHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        log_entry = {
            "level": record.levelname,
            "time": record.asctime,
            "message": record.getMessage()
        }
        try:
            self.log_queue.put_nowait(log_entry)
        except queue.Full:
            pass


class WebUI:
    def __init__(self, system, host="0.0.0.0", port=8080):
        self.system = system
        self.host = host
        self.port = port
        self.app = Flask(__name__)
        self.log_queue = queue.Queue(maxsize=2000)
        self.running = False
        self.thread = None

        self._setup_routes()
        self._setup_log_handler()

    def _setup_routes(self):
        @self.app.route('/')
        def index():
            return render_template_string(self._get_html())

        @self.app.route('/api/status')
        def api_status():
            state_info = self.system.get_state()
            return jsonify(state_info)

        @self.app.route('/api/devices')
        def api_devices():
            devices = {
                "robot": {
                    "connected": self.system.robot is not None and self.system.robot.connected,
                    "ip": self.system.config["robot"]["ip"],
                    "port": self.system.config["robot"]["port"]
                },
                "canon": {
                    "initialized": self.system.canon_camera is not None and self.system.canon_camera.initialized,
                    "exe_path": self.system.config["canon_camera"]["exe_path"]
                },
                "realsense": {
                    "initialized": self.system.realsense is not None and self.system.realsense.initialized,
                    "width": self.system.config["realsense"]["width"],
                    "height": self.system.config["realsense"]["height"],
                    "fps": self.system.config["realsense"]["fps"]
                }
            }
            return jsonify(devices)

        @self.app.route('/api/trajectories')
        def api_trajectories():
            traj_dir = os.path.dirname(self.system.config["trajectory"]["file_path"])
            if not os.path.exists(traj_dir):
                return jsonify([])
            
            files = []
            for f in os.listdir(traj_dir):
                if f.endswith('.txt'):
                    filepath = os.path.join(traj_dir, f)
                    files.append({
                        "name": f,
                        "path": filepath,
                        "size": os.path.getsize(filepath),
                        "modified": os.path.getmtime(filepath)
                    })
            return jsonify(files)

        @self.app.route('/api/initialize_device/<device_type>', methods=['POST'])
        def api_initialize_device(device_type):
            try:
                if device_type == 'robot':
                    if self.system.robot and self.system.robot.connect():
                        return jsonify({"success": True, "message": "机械臂连接成功"})
                    return jsonify({"success": False, "error": "机械臂连接失败"})
                elif device_type == 'canon':
                    if self.system.canon_camera and self.system.canon_camera.initialize():
                        return jsonify({"success": True, "message": "佳能相机初始化成功"})
                    return jsonify({"success": False, "error": "佳能相机初始化失败"})
                elif device_type == 'realsense':
                    if self.system.realsense and self.system.realsense.initialize():
                        return jsonify({"success": True, "message": "RealSense初始化成功"})
                    return jsonify({"success": False, "error": "RealSense初始化失败"})
                else:
                    return jsonify({"success": False, "error": f"未知设备类型: {device_type}"})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})

        @self.app.route('/api/start_detection', methods=['POST'])
        def api_start_detection():
            try:
                if self.system.state != SystemState.IDLE:
                    return jsonify({
                        "success": False,
                        "error": f"当前系统状态为 {self.system.state.value}，无法启动检测"
                    })

                logger.info("Web UI 发起检测请求...")
                self.system.error_message = None
                
                threading.Thread(
                    target=self.system.start_detection,
                    daemon=True
                ).start()

                return jsonify({
                    "success": True,
                    "message": "检测已启动"
                })
            except Exception as e:
                logger.error(f"检测任务异常: {e}")
                return jsonify({"success": False, "error": str(e)})

        @self.app.route('/api/stop', methods=['POST'])
        def api_stop():
            try:
                self.system.stop_detection()
                return jsonify({"success": True, "message": "已停止当前检测"})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})

        @self.app.route('/api/reset', methods=['POST'])
        def api_reset():
            try:
                success = self.system.reset_system()
                if success:
                    return jsonify({"success": True, "message": "系统复位成功"})
                else:
                    return jsonify({"success": False, "error": "系统复位失败"})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})

        @self.app.route('/api/shutdown', methods=['POST'])
        def api_shutdown():
            try:
                threading.Thread(target=self.system.shutdown, daemon=True).start()
                return jsonify({"success": True, "message": "系统正在关闭..."})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)})

        @self.app.route('/api/logs')
        def api_logs():
            def generate():
                while self.running:
                    try:
                        log_entry = self.log_queue.get(timeout=1)
                        yield f"data: {json.dumps(log_entry, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        continue

            return Response(generate(), mimetype='text/event-stream')

        @self.app.route('/api/config')
        def api_config():
            if hasattr(self.system, 'config'):
                return jsonify({
                    "robot": {
                        "ip": self.system.config["robot"]["ip"],
                        "port": self.system.config["robot"]["port"],
                        "velocity": self.system.config["robot"]["velocity"]
                    },
                    "realsense": {
                        "width": self.system.config["realsense"]["width"],
                        "height": self.system.config["realsense"]["height"],
                        "fps": self.system.config["realsense"]["fps"],
                        "preset_profile": self.system.config["realsense"]["preset_profile"],
                        "colorizer_scheme": self.system.config["realsense"].get("colorizer_scheme", 9),
                        "min_distance": self.system.config["realsense"].get("min_distance", 0.2),
                        "max_distance": self.system.config["realsense"].get("max_distance", 1.73)
                    },
                    "output": {
                        "base_path": self.system.config["output"]["base_path"]
                    },
                    "trajectory": {
                        "file_path": self.system.config["trajectory"]["file_path"],
                        "point_count": len(self.system.trajectory_points) if hasattr(self.system, 'trajectory_points') else 0
                    }
                })
            return jsonify({})

        @self.app.route('/api/video/<stream_type>')
        def api_video(stream_type):
            if stream_type not in ('color', 'depth'):
                return jsonify({"success": False, "error": "未知流类型"}), 404
            if not CV2_AVAILABLE:
                return jsonify({"success": False, "error": "cv2未安装，实时画面不可用"}), 503
            return Response(
                self._gen_mjpeg(stream_type),
                mimetype='multipart/x-mixed-replace; boundary=frame'
            )

        @self.app.route('/api/reload_trajectory', methods=['POST'])
        def api_reload_trajectory():
            try:
                data = request.get_json(silent=True) or {}
                result = self.system.reload_trajectory(data.get('trajectory_file', ''))
                return jsonify({
                    "success": True,
                    "message": f"轨迹重载成功，共{result['point_count']}个点",
                    **result
                })
            except (RuntimeError, ValueError) as e:
                return jsonify({"success": False, "error": str(e)})
            except Exception as e:
                return jsonify({"success": False, "error": f"加载轨迹文件失败: {e}"})

    def _gen_mjpeg(self, stream_type):
        """MJPEG流生成器: 浏览器<img>原生支持multipart/x-mixed-replace。

        - 仅IDLE状态拉取相机帧; 检测进行中完全停止拉帧,
          只推占位图保活连接。原因: preview与capture()并发共用
          align/colorizer处理块, pyrealsense2处理块非线程安全,
          扫描时预览继续取帧会导致采集失败
        - 相机未初始化/无帧时推占位图(而非断流503),
          相机就绪或回到IDLE后画面自动切换, <img>标签无需刷新
        """
        while self.running:
            image = None
            state = self.system.state
            if state == SystemState.IDLE:
                realsense = self.system.realsense
                if realsense is not None and realsense.initialized:
                    frames = realsense.get_preview_frames()
                    if frames is not None:
                        image = frames[0] if stream_type == 'color' else frames[1]
                if image is None:
                    image = self._placeholder_frame('D435 Not Initialized')
            else:
                # 检测进行中: 占位提示, 每2秒一帧仅保活连接, 零相机访问
                image = self._placeholder_frame('Detection in Progress', '(Preview Paused)')
            ok, buf = cv2.imencode('.jpg', image, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
            # 预览已跳过align重量级对齐, IDLE下约15fps低延迟推流
            time.sleep(0.066 if state == SystemState.IDLE else 2.0)

    @staticmethod
    def _placeholder_frame(text, sub_text=None):
        img = np.full((240, 424, 3), 30, dtype=np.uint8)
        cv2.putText(img, text, (60, 128), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (170, 170, 170), 2)
        if sub_text:
            cv2.putText(img, sub_text, (110, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 120, 120), 1)
        return img

    def _setup_log_handler(self):
        handler = LogStreamHandler(self.log_queue)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        logging.getLogger().addHandler(handler)

    def _get_html(self):
        return '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>头皮检测系统 - 控制面板</title>
    <style>
        :root {
            --primary: #4F46E5;
            --primary-dark: #4338CA;
            --success: #10B981;
            --warning: #F59E0B;
            --danger: #EF4444;
            --info: #3B82F6;
            --dark: #1F2937;
            --gray: #6B7280;
            --light-gray: #F3F4F6;
            --border-color: #E5E7EB;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
            --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        }

        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Microsoft YaHei', 'Segoe UI', Tahoma, sans-serif; 
            background: var(--light-gray); 
            color: var(--dark); 
            min-height: 100vh;
        }

        .container { max-width: 1600px; margin: 0 auto; padding: 20px; }

        .header { 
            background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%); 
            color: white; 
            padding: 24px 32px; 
            border-radius: 16px; 
            margin-bottom: 24px;
            box-shadow: var(--shadow-lg);
        }
        .header-top { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 15px; }
        .header-title { font-size: 28px; font-weight: 700; }
        .header-subtitle { font-size: 14px; opacity: 0.85; margin-top: 4px; }
        .system-status { 
            display: flex; 
            align-items: center; 
            gap: 10px; 
            padding: 10px 20px; 
            background: rgba(255,255,255,0.15); 
            border-radius: 25px; 
            font-size: 14px;
        }
        .status-dot { 
            width: 12px; 
            height: 12px; 
            border-radius: 50%; 
            background: var(--success); 
            animation: pulse 2s infinite; 
        }
        .status-dot.error { background: var(--danger); }
        .status-dot.warning { background: var(--warning); }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

        .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 20px; }
        .card { 
            background: white; 
            border-radius: 16px; 
            padding: 24px; 
            box-shadow: var(--shadow); 
            transition: all 0.3s;
        }
        .card:hover { box-shadow: var(--shadow-lg); }
        .card-header { 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 20px; 
            padding-bottom: 16px; 
            border-bottom: 2px solid var(--border-color);
        }
        .card-title { font-size: 18px; font-weight: 600; color: var(--dark); display: flex; align-items: center; gap: 10px; }
        .card-icon { font-size: 24px; }
        .card-badge { 
            padding: 4px 12px; 
            border-radius: 20px; 
            font-size: 12px; 
            font-weight: 600;
        }
        .card-badge.success { background: #D1FAE5; color: var(--success); }
        .card-badge.error { background: #FEE2E2; color: var(--danger); }
        .card-badge.warning { background: #FEF3C7; color: var(--warning); }
        .card-badge.info { background: #DBEAFE; color: var(--info); }

        .col-3 { grid-column: span 3; }
        .col-4 { grid-column: span 4; }
        .col-6 { grid-column: span 6; }
        .col-8 { grid-column: span 8; }
        .col-9 { grid-column: span 9; }
        .col-12 { grid-column: span 12; }

        .device-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; }
        .device-item { 
            background: var(--light-gray); 
            padding: 20px 15px; 
            border-radius: 12px; 
            text-align: center;
            border-left: 4px solid var(--gray);
            transition: all 0.3s;
        }
        .device-item.connected { border-left-color: var(--success); background: #F0FDF4; }
        .device-item.disconnected { border-left-color: var(--danger); background: #FEF2F2; }
        .device-item.initialized { border-left-color: var(--info); background: #EFF6FF; }
        .device-item:hover { transform: translateY(-2px); }
        .device-icon { font-size: 32px; margin-bottom: 10px; }
        .device-name { font-size: 14px; font-weight: 600; color: var(--dark); }
        .device-status { font-size: 12px; margin-top: 5px; }
        .device-status.connected { color: var(--success); }
        .device-status.disconnected { color: var(--danger); }

        .btn-group { display: flex; gap: 12px; flex-wrap: wrap; }
        .btn { 
            padding: 14px 28px; 
            border: none; 
            border-radius: 10px; 
            font-size: 15px; 
            font-weight: 600; 
            cursor: pointer; 
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 140px;
            justify-content: center;
        }
        .btn:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
        .btn:active { transform: translateY(0); }
        .btn:disabled { 
            opacity: 0.5; 
            cursor: not-allowed; 
            transform: none; 
        }
        .btn-primary { background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%); color: white; }
        .btn-success { background: var(--success); color: white; }
        .btn-warning { background: var(--warning); color: white; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-info { background: var(--info); color: white; }
        .btn-secondary { background: var(--gray); color: white; }
        .btn-outline { background: white; border: 2px solid var(--border-color); color: var(--dark); }
        .btn-outline:hover { border-color: var(--primary); color: var(--primary); }

        .progress-section { margin-top: 20px; }
        .progress-bar-bg { 
            height: 16px; 
            background: var(--light-gray); 
            border-radius: 8px; 
            overflow: hidden; 
            position: relative;
        }
        .progress-bar { 
            height: 100%; 
            background: linear-gradient(90deg, var(--primary) 0%, var(--success) 100%); 
            border-radius: 8px; 
            transition: width 0.5s ease; 
            position: relative;
        }
        .progress-bar::after {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
            animation: shimmer 2s infinite;
        }
        @keyframes shimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
        .progress-info { 
            display: flex; 
            justify-content: space-between; 
            margin-top: 10px; 
            font-size: 14px; 
            color: var(--gray);
        }
        .progress-info strong { color: var(--dark); }

        .log-panel { height: 450px; display: flex; flex-direction: column; }
        .log-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .log-container { 
            flex: 1;
            overflow-y: auto; 
            border: 1px solid var(--border-color); 
            border-radius: 10px; 
            padding: 15px; 
            background: #FAFAFA; 
            font-family: 'Consolas', 'Monaco', monospace; 
            font-size: 13px;
            line-height: 1.6;
        }
        .log-container::-webkit-scrollbar { width: 6px; }
        .log-container::-webkit-scrollbar-track { background: var(--light-gray); border-radius: 3px; }
        .log-container::-webkit-scrollbar-thumb { background: var(--gray); border-radius: 3px; }
        .log-entry { 
            margin-bottom: 6px; 
            padding: 6px 10px; 
            border-radius: 6px;
            border-left: 3px solid transparent;
            word-break: break-all;
        }
        .log-entry.INFO { color: var(--dark); background: white; border-left-color: var(--info); }
        .log-entry.WARNING { color: #92400E; background: #FFFBEB; border-left-color: var(--warning); }
        .log-entry.ERROR { color: #991B1B; background: #FEF2F2; border-left-color: var(--danger); }
        .log-entry.DEBUG { color: var(--gray); background: var(--light-gray); }
        .log-entry.SUCCESS { color: #166534; background: #F0FDF4; border-left-color: var(--success); }

        .config-table { width: 100%; border-collapse: collapse; }
        .config-table td { padding: 12px 15px; border-bottom: 1px solid var(--border-color); }
        .config-table tr:last-child td { border-bottom: none; }
        .config-label { color: var(--gray); font-weight: 500; width: 40%; }
        .config-value { font-weight: 600; color: var(--dark); }

        .output-info { 
            background: var(--light-gray); 
            padding: 16px; 
            border-radius: 10px;
            font-family: 'Consolas', monospace;
            font-size: 13px;
            word-break: break-all;
            margin-bottom: 15px;
        }
        .output-info strong { color: var(--primary); }

        .stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-top: 15px; }
        .stat-item { 
            background: var(--light-gray); 
            padding: 15px; 
            border-radius: 10px; 
            text-align: center;
        }
        .stat-value { font-size: 28px; font-weight: 700; color: var(--primary); }
        .stat-label { font-size: 12px; color: var(--gray); margin-top: 5px; text-transform: uppercase; letter-spacing: 1px; }

        .error-banner {
            background: #FEF2F2;
            border: 1px solid #FECACA;
            border-radius: 10px;
            padding: 16px 20px;
            margin-bottom: 20px;
            display: none;
        }
        .error-banner.show { display: flex; align-items: center; gap: 12px; }
        .error-icon { font-size: 20px; color: var(--danger); }
        .error-content { flex: 1; }
        .error-title { color: var(--danger); font-weight: 600; margin-bottom: 4px; }
        .error-message { color: #991B1B; font-size: 14px; }

        .action-history { 
            max-height: 180px; 
            overflow-y: auto; 
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 10px;
            background: #FAFAFA;
        }
        .history-item { 
            padding: 8px 12px; 
            margin-bottom: 6px; 
            background: white; 
            border-radius: 6px;
            font-size: 13px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .history-item .time { color: var(--gray); font-size: 11px; }

        .modal-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .modal-overlay.show { display: flex; }
        .modal {
            background: white;
            border-radius: 16px;
            padding: 24px;
            width: 90%;
            max-width: 500px;
            box-shadow: var(--shadow-lg);
        }
        .modal-title { font-size: 20px; font-weight: 600; margin-bottom: 20px; }
        .modal-body { margin-bottom: 20px; }
        .modal-footer { display: flex; justify-content: flex-end; gap: 10px; }

        .select-wrapper { position: relative; margin-bottom: 15px; }
        .select-wrapper select {
            width: 100%;
            padding: 12px 16px;
            border: 2px solid var(--border-color);
            border-radius: 10px;
            font-size: 15px;
            background: white;
            cursor: pointer;
            appearance: none;
        }
        .select-wrapper select:focus { outline: none; border-color: var(--primary); }
        .select-wrapper::after {
            content: '▼';
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 12px;
            color: var(--gray);
            pointer-events: none;
        }

        .toggle-switch {
            position: relative;
            display: inline-block;
            width: 48px;
            height: 26px;
        }
        .toggle-switch input { opacity: 0; width: 0; height: 0; }
        .toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0; left: 0; right: 0; bottom: 0;
            background-color: var(--gray);
            transition: 0.3s;
            border-radius: 26px;
        }
        .toggle-slider:before {
            position: absolute;
            content: "";
            height: 20px;
            width: 20px;
            left: 3px;
            bottom: 3px;
            background-color: white;
            transition: 0.3s;
            border-radius: 50%;
        }
        input:checked + .toggle-slider { background-color: var(--success); }
        input:checked + .toggle-slider:before { transform: translateX(22px); }

        @media (max-width: 768px) {
            .col-3, .col-4, .col-6, .col-8, .col-9 { grid-column: span 12; }
            .header-top { flex-direction: column; align-items: flex-start; }
            .btn { min-width: 100%; }
            .stats-row { grid-template-columns: repeat(2, 1fr); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-top">
                <div>
                    <div class="header-title">🧠 头皮检测系统</div>
                    <div class="header-subtitle">机械臂轨迹控制 · 双相机同步拍摄 · 自动数据采集</div>
                </div>
                <div class="system-status">
                    <span class="status-dot" id="statusDot"></span>
                    <span id="systemStatusText">系统运行中</span>
                </div>
            </div>
        </div>

        <div class="error-banner" id="errorBanner">
            <span class="error-icon">⚠️</span>
            <div class="error-content">
                <div class="error-title">系统错误</div>
                <div class="error-message" id="errorMessage"></div>
            </div>
        </div>

        <div class="grid">
            <div class="card col-4">
                <div class="card-header">
                    <div class="card-title">
                        <span class="card-icon">🔌</span>
                        设备状态
                    </div>
                    <span class="card-badge" id="devicesBadge">检测中...</span>
                </div>
                <div class="device-grid" id="deviceGrid">
                    <div class="device-item" id="robot">
                        <div class="device-icon">🤖</div>
                        <div class="device-name">机械臂</div>
                        <div class="device-status" id="robotStatus">未知</div>
                    </div>
                    <div class="device-item" id="canon">
                        <div class="device-icon">📷</div>
                        <div class="device-name">佳能相机</div>
                        <div class="device-status" id="canonStatus">未知</div>
                    </div>
                    <div class="device-item" id="rs">
                        <div class="device-icon">🖥️</div>
                        <div class="device-name">D435深度相机</div>
                        <div class="device-status" id="rsStatus">未知</div>
                    </div>
                </div>
                <div class="btn-group" style="margin-top: 20px;">
                    <button class="btn btn-outline" id="btnReconnectRobot" style="min-width: 100%;">
                        <span>🔄</span>
                        重新连接机械臂
                    </button>
                    <button class="btn btn-outline" id="btnReconnectCanon" style="min-width: 100%;">
                        <span>🔄</span>
                        重新初始化佳能
                    </button>
                    <button class="btn btn-outline" id="btnReconnectRS" style="min-width: 100%;">
                        <span>🔄</span>
                        重新初始化D435
                    </button>
                </div>
            </div>

            <div class="card col-4">
                <div class="card-header">
                    <div class="card-title">
                        <span class="card-icon">📊</span>
                        扫描进度
                    </div>
                    <span class="card-badge" id="stateBadge">IDLE</span>
                </div>
                
                <div class="progress-section">
                    <div class="progress-bar-bg">
                        <div class="progress-bar" id="progressBar" style="width: 0%"></div>
                    </div>
                    <div class="progress-info">
                        <span><strong id="progressLabel">等待开始</strong></span>
                        <span><strong id="progressPercent">0%</strong></span>
                    </div>
                </div>

                <div class="stats-row">
                    <div class="stat-item">
                        <div class="stat-value" id="statCurrentPoint">0</div>
                        <div class="stat-label">当前点位</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="statTotalPoints">0</div>
                        <div class="stat-label">总点位</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="statCanonImages">0</div>
                        <div class="stat-label">佳能图片</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-value" id="statRsImages">0</div>
                        <div class="stat-label">深度图片</div>
                    </div>
                </div>

                <div style="margin-top: 15px;">
                    <div class="output-info" id="outputPath">
                        <strong>输出路径:</strong> 等待开始...
                    </div>
                </div>
            </div>

            <div class="card col-4">
                <div class="card-header">
                    <div class="card-title">
                        <span class="card-icon">⚙️</span>
                        当前配置
                    </div>
                </div>
                <table class="config-table">
                    <tr>
                        <td class="config-label">机械臂 IP</td>
                        <td class="config-value" id="cfgRobotIp">--</td>
                    </tr>
                    <tr>
                        <td class="config-label">机械臂端口</td>
                        <td class="config-value" id="cfgRobotPort">--</td>
                    </tr>
                    <tr>
                        <td class="config-label">D435 分辨率</td>
                        <td class="config-value" id="cfgRsResolution">--</td>
                    </tr>
                    <tr>
                        <td class="config-label">D435 FPS</td>
                        <td class="config-value" id="cfgRsFps">--</td>
                    </tr>
                    <tr>
                        <td class="config-label">深度预设</td>
                        <td class="config-value" id="cfgRsPreset">--</td>
                    </tr>
                    <tr>
                        <td class="config-label">输出目录</td>
                        <td class="config-value" id="cfgOutputPath">--</td>
                    </tr>
                </table>

                <div style="margin-top: 20px;">
                    <div class="card-title" style="font-size: 14px; margin-bottom: 10px;">📁 轨迹文件</div>
                    <div class="select-wrapper">
                        <select id="trajectorySelect">
                            <option value="">选择轨迹文件...</option>
                        </select>
                    </div>
                    <div style="font-size: 12px; color: var(--gray); margin-top: 5px;">
                        当前轨迹点: <span id="trajectoryPointCount">0</span>
                    </div>
                    <button class="btn btn-secondary" id="btnReloadTraj" style="margin-top: 10px; min-width: auto; padding: 8px 14px; font-size: 13px;">
                        <span>🔄</span> 重新加载轨迹
                    </button>
                    <div id="reloadResult" style="font-size: 12px; margin-top: 6px; min-height: 16px;"></div>
                </div>
            </div>

            <div class="card col-6">
                <div class="card-header">
                    <div class="card-title">
                        <span class="card-icon">🎮</span>
                        操作控制
                    </div>
                </div>
                
                <div class="btn-group">
                    <button class="btn btn-primary" id="btnStart">
                        <span>▶️</span>
                        开始检测
                    </button>
                    <button class="btn btn-danger" id="btnStop">
                        <span>⏹️</span>
                        停止检测
                    </button>
                    <button class="btn btn-warning" id="btnReset">
                        <span>🔄</span>
                        复位系统
                    </button>
                </div>

                <div class="btn-group" style="margin-top: 15px;">
                    <button class="btn btn-info" id="btnRefresh">
                        <span>🔃</span>
                        刷新状态
                    </button>
                    <button class="btn btn-secondary" id="btnShutdown" onclick="return confirm('确定要关闭系统吗？')">
                        <span>🚪</span>
                        关闭系统
                    </button>
                </div>

                <div style="margin-top: 25px; padding: 20px; background: #FFFBEB; border-radius: 12px; border-left: 4px solid var(--warning);">
                    <div style="font-weight: 600; color: #92400E; margin-bottom: 8px;">💡 操作提示</div>
                    <ul style="font-size: 13px; color: #78350F; line-height: 1.8; padding-left: 20px;">
                        <li>确保所有设备已连接并开机</li>
                        <li>检查设备状态指示灯是否正常</li>
                        <li>点击"开始检测"启动扫描流程</li>
                        <li>检测完成后数据保存在输出路径下</li>
                        <li>出现错误时点击"复位系统"恢复</li>
                    </ul>
                </div>

                <div style="margin-top: 20px;">
                    <div class="card-title" style="font-size: 14px; margin-bottom: 10px;">📜 操作历史</div>
                    <div class="action-history" id="actionHistory"></div>
                </div>
            </div>

            <div class="card col-6">
                <div class="card-header">
                    <div class="card-title">
                        <span class="card-icon">📝</span>
                        实时日志
                    </div>
                    <div class="log-header">
                        <span style="font-size: 12px; color: var(--gray);" id="logCount">0 条日志</span>
                        <button class="btn btn-secondary" style="min-width: auto; padding: 6px 12px; font-size: 12px;" onclick="clearLogs()">
                            清空日志
                        </button>
                    </div>
                </div>
                <div class="log-panel">
                    <div class="log-container" id="logContainer"></div>
                </div>
            </div>
        </div>

        <div class="card" style="margin-top: 24px;">
            <div class="card-header">
                <div class="card-title">
                    <span class="card-icon">📷</span>
                    实时画面 (D435)
                </div>
                <span style="font-size: 12px; color: var(--gray);">彩色 + 深度伪彩 | 空闲约10fps，检测期间预览自动暂停（避免干扰采集）</span>
            </div>
            <div style="display: flex; gap: 16px; flex-wrap: wrap;">
                <div style="flex: 1; min-width: 320px;">
                    <div style="font-size: 13px; color: var(--gray); margin-bottom: 6px;">彩色画面</div>
                    <img id="videoColor" src="/api/video/color" alt="彩色画面" onerror="videoFallback('videoColor')"
                         style="width: 100%; border-radius: 10px; background: #111; display: block;">
                </div>
                <div style="flex: 1; min-width: 320px;">
                    <div style="font-size: 13px; color: var(--gray); margin-bottom: 6px;">深度伪彩</div>
                    <img id="videoDepth" src="/api/video/depth" alt="深度伪彩" onerror="videoFallback('videoDepth')"
                         style="width: 100%; border-radius: 10px; background: #111; display: block;">
                </div>
            </div>
        </div>

        <div style="text-align: center; margin-top: 24px; padding: 15px; background: white; border-radius: 10px; color: var(--gray); font-size: 13px;">
            🧠 头皮检测系统 v1.0 | 基于 Flask + Python 构建 | 支持 SSE 实时通信 | 双相机同步采集
        </div>
    </div>

    <script>
        let eventSource = null;
        let statusInterval = null;
        let deviceInterval = null;
        let statusPollInterval = 3000;
        let actionHistory = [];
        let logCount = 0;

        function addHistory(action) {
            const now = new Date();
            const timeStr = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            actionHistory.unshift({ action, time: timeStr });
            if (actionHistory.length > 15) actionHistory.pop();
            
            const container = document.getElementById('actionHistory');
            container.innerHTML = actionHistory.map(item => 
                `<div class="history-item"><span>${item.action}</span><span class="time">${item.time}</span></div>`
            ).join('');
        }

        function updateStatus() {
            fetch('/api/status')
                .then(response => response.json())
                .then(data => {
                    const state = (data.state || 'IDLE').toUpperCase();
                    
                    document.getElementById('stateBadge').textContent = state;
                    document.getElementById('stateBadge').className = 'card-badge ' + 
                        (state === 'RUNNING' ? 'info' : state === 'ERROR' ? 'error' : state === 'COMPLETED' ? 'success' : 'warning');

                    document.getElementById('statCurrentPoint').textContent = data.current_point !== undefined ? data.current_point + 1 : 0;
                    document.getElementById('statTotalPoints').textContent = data.total_points || 0;
                    
                    if (data.output_dir) {
                        document.getElementById('outputPath').innerHTML = `<strong>输出路径:</strong> ${data.output_dir}`;
                    } else {
                        document.getElementById('outputPath').innerHTML = '<strong>输出路径:</strong> 等待开始...';
                    }

                    const btnStart = document.getElementById('btnStart');
                    const btnStop = document.getElementById('btnStop');
                    const btnReset = document.getElementById('btnReset');

                    btnStart.disabled = state !== 'IDLE';
                    btnStop.disabled = !(state === 'RUNNING' || state === 'ERROR' || state === 'STOPPING');
                    btnReset.disabled = !(state === 'ERROR' || state === 'COMPLETED');
                    document.getElementById('btnReloadTraj').disabled = state !== 'IDLE';

                    if (state === 'RUNNING') {
                        btnStart.innerHTML = '<span>⏳</span>检测中...';
                        if (statusPollInterval !== 1000) {
                            statusPollInterval = 1000;
                            clearInterval(statusInterval);
                            statusInterval = setInterval(updateStatus, statusPollInterval);
                        }
                    } else {
                        btnStart.innerHTML = '<span>▶️</span>开始检测';
                        if ((state === 'IDLE' || state === 'COMPLETED') && statusPollInterval !== 5000) {
                            statusPollInterval = 5000;
                            clearInterval(statusInterval);
                            statusInterval = setInterval(updateStatus, statusPollInterval);
                        }
                    }

                    const current = data.current_point !== undefined ? data.current_point + 1 : 0;
                    const total = data.total_points || 1;
                    const percent = total > 0 ? Math.round((current / total) * 100) : 0;
                    
                    document.getElementById('progressBar').style.width = percent + '%';
                    document.getElementById('progressPercent').textContent = percent + '%';
                    document.getElementById('progressLabel').textContent = 
                        state === 'RUNNING' ? `正在执行点位 ${current}/${total}` :
                        state === 'COMPLETED' ? '🎉 检测完成' :
                        state === 'ERROR' ? '❌ 检测失败' :
                        state === 'STOPPING' ? '⏹️ 正在停止' :
                        state === 'RESETTING' ? '🔄 正在复位' :
                        '等待开始';

                    if (data.error_message) {
                        document.getElementById('errorBanner').classList.add('show');
                        document.getElementById('errorMessage').textContent = data.error_message;
                    } else {
                        document.getElementById('errorBanner').classList.remove('show');
                    }

                    document.getElementById('statusDot').className = 'status-dot';
                    document.getElementById('systemStatusText').textContent = 
                        state === 'ERROR' ? '系统错误' : 
                        state === 'RUNNING' ? '检测进行中' : '系统运行中';
                })
                .catch(error => {
                    console.error('获取状态失败:', error);
                    document.getElementById('statusDot').className = 'status-dot error';
                    document.getElementById('systemStatusText').textContent = '连接断开';
                });
        }

        function updateDevices() {
            fetch('/api/devices')
                .then(response => response.json())
                .then(data => {
                    const updateDevice = (id, connected, initialized, name) => {
                        const item = document.getElementById(id);
                        const status = document.getElementById(id + 'Status');
                        if (connected || initialized) {
                            item.classList.add('connected');
                            item.classList.remove('disconnected');
                            status.textContent = connected ? '已连接' : '已初始化';
                            status.className = 'device-status connected';
                        } else {
                            item.classList.add('disconnected');
                            item.classList.remove('connected');
                            status.textContent = '未连接';
                            status.className = 'device-status disconnected';
                        }
                    };

                    updateDevice('robot', data.robot?.connected, false, '机械臂');
                    updateDevice('canon', false, data.canon?.initialized, '佳能相机');
                    updateDevice('rs', false, data.realsense?.initialized, 'D435深度相机');

                    const allConnected = (data.robot?.connected || false) && 
                                        (data.canon?.initialized || false) && 
                                        (data.realsense?.initialized || false);
                    document.getElementById('devicesBadge').textContent = allConnected ? '全部就绪' : '部分未就绪';
                    document.getElementById('devicesBadge').className = 'card-badge ' + (allConnected ? 'success' : 'warning');
                })
                .catch(error => console.error('获取设备状态失败:', error));
        }

        function loadConfig() {
            fetch('/api/config')
                .then(response => response.json())
                .then(data => {
                    if (data.robot) {
                        document.getElementById('cfgRobotIp').textContent = data.robot.ip;
                        document.getElementById('cfgRobotPort').textContent = data.robot.port;
                    }
                    if (data.realsense) {
                        document.getElementById('cfgRsResolution').textContent = 
                            data.realsense.width + '×' + data.realsense.height;
                        document.getElementById('cfgRsFps').textContent = data.realsense.fps;
                        document.getElementById('cfgRsPreset').textContent = data.realsense.preset_profile;
                    }
                    if (data.output) {
                        document.getElementById('cfgOutputPath').textContent = data.output.base_path;
                    }
                    if (data.trajectory) {
                        document.getElementById('trajectoryPointCount').textContent = data.trajectory.point_count;
                    }
                })
                .catch(error => console.error('加载配置失败:', error));
        }

        function loadTrajectories() {
            fetch('/api/trajectories')
                .then(response => response.json())
                .then(data => {
                    const select = document.getElementById('trajectorySelect');
                    select.innerHTML = '<option value="">选择轨迹文件...</option>';
                    data.forEach(file => {
                        const option = document.createElement('option');
                        option.value = file.path;
                        option.textContent = file.name;
                        select.appendChild(option);
                    });
                })
                .catch(error => console.error('加载轨迹文件失败:', error));
        }

        function reloadTrajectory() {
            const select = document.getElementById('trajectorySelect');
            const resultBox = document.getElementById('reloadResult');
            if (!select.value) {
                resultBox.style.color = '#B45309';
                resultBox.textContent = '请先在上方选择轨迹文件';
                return;
            }
            const btn = document.getElementById('btnReloadTraj');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span>加载中...';
            fetch('/api/reload_trajectory', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ trajectory_file: select.value })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('trajectoryPointCount').textContent = data.point_count;
                        resultBox.style.color = '#059669';
                        resultBox.textContent = '✅ ' + data.message;
                        addHistory('重新加载轨迹: ' + select.options[select.selectedIndex].text + ' (' + data.point_count + '点)');
                    } else {
                        resultBox.style.color = '#DC2626';
                        resultBox.textContent = '❌ ' + (data.error || '未知错误');
                    }
                })
                .catch(error => {
                    resultBox.style.color = '#DC2626';
                    resultBox.textContent = '❌ 请求失败: ' + error;
                })
                .finally(() => {
                    btn.innerHTML = '<span>🔄</span> 重新加载轨迹';
                    btn.disabled = false;
                });
        }

        function videoFallback(id) {
            document.getElementById(id).src = 'data:image/svg+xml;utf8,' + encodeURIComponent(
                '<svg xmlns="http://www.w3.org/2000/svg" width="424" height="240"><rect width="100%" height="100%" fill="#222"/><text x="50%" y="50%" fill="#888" font-size="16" text-anchor="middle">画面不可用</text></svg>'
            );
        }

        function startDetection() {
            const btn = document.getElementById('btnStart');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span>启动中...';

            fetch('/api/start_detection', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (!data.success) {
                        alert('启动失败: ' + (data.error || '未知错误'));
                        btn.innerHTML = '<span>▶️</span>开始检测';
                        btn.disabled = false;
                    } else {
                        addHistory('开始检测');
                        document.getElementById('statCanonImages').textContent = '0';
                        document.getElementById('statRsImages').textContent = '0';
                    }
                    updateStatus();
                })
                .catch(error => {
                    console.error('启动检测失败:', error);
                    btn.innerHTML = '<span>▶️</span>开始检测';
                    btn.disabled = false;
                });
        }

        function stopDetection() {
            fetch('/api/stop', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    addHistory('停止检测');
                    updateStatus();
                })
                .catch(error => console.error('停止检测失败:', error));
        }

        function resetSystem() {
            if (!confirm('确定要复位系统吗？机械臂将回到起始点。')) return;

            const btn = document.getElementById('btnReset');
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span>复位中...';

            fetch('/api/reset', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        addHistory('系统复位');
                    }
                    alert(data.success ? '复位成功' : '复位失败: ' + (data.error || ''));
                    btn.innerHTML = '<span>🔄</span>复位系统';
                    btn.disabled = false;
                    updateStatus();
                    updateDevices();
                })
                .catch(error => {
                    console.error('复位失败:', error);
                    btn.innerHTML = '<span>🔄</span>复位系统';
                    btn.disabled = false;
                });
        }

        function shutdownSystem() {
            fetch('/api/shutdown', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    addHistory('关闭系统');
                    document.getElementById('statusDot').className = 'status-dot error';
                    document.getElementById('systemStatusText').textContent = '系统已关闭';
                    setTimeout(() => location.reload(), 3000);
                });
        }

        function reconnectDevice(deviceType) {
            const btnId = 'btnReconnect' + (deviceType === 'robot' ? 'Robot' : deviceType === 'canon' ? 'Canon' : 'RS');
            const btn = document.getElementById(btnId);
            btn.disabled = true;
            btn.innerHTML = '<span>⏳</span>连接中...';

            fetch(`/api/initialize_device/${deviceType}`, { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    alert(data.success ? data.message : '失败: ' + (data.error || ''));
                    btn.innerHTML = '<span>🔄</span>重新连接' + (deviceType === 'robot' ? '机械臂' : deviceType === 'canon' ? '佳能' : 'D435');
                    btn.disabled = false;
                    updateDevices();
                })
                .catch(error => {
                    console.error('重新连接失败:', error);
                    btn.innerHTML = '<span>🔄</span>重新连接' + (deviceType === 'robot' ? '机械臂' : deviceType === 'canon' ? '佳能' : 'D435');
                    btn.disabled = false;
                });
        }

        function connectLogs() {
            if (eventSource) {
                eventSource.close();
            }

            eventSource = new EventSource('/api/logs');
            eventSource.onmessage = function(event) {
                const log = JSON.parse(event.data);
                const container = document.getElementById('logContainer');
                const entry = document.createElement('div');
                entry.className = 'log-entry ' + log.level;
                entry.textContent = '[' + log.time + '] ' + log.message;
                container.appendChild(entry);
                container.scrollTop = container.scrollHeight;
                
                logCount++;
                document.getElementById('logCount').textContent = logCount + ' 条日志';

                if (log.message.includes('拍照成功') && log.message.includes('佳能')) {
                    const count = parseInt(document.getElementById('statCanonImages').textContent) || 0;
                    document.getElementById('statCanonImages').textContent = count + 1;
                }
                if (log.message.includes('RealSense深度图保存')) {
                    const count = parseInt(document.getElementById('statRsImages').textContent) || 0;
                    document.getElementById('statRsImages').textContent = count + 1;
                }
                if (log.message.includes('检测流程完成')) {
                    addHistory('检测完成');
                }
                if (log.message.includes('检测过程出错')) {
                    addHistory('检测失败');
                }
            };

            eventSource.onerror = function() {
                eventSource.close();
                setTimeout(connectLogs, 3000);
            };
        }

        function clearLogs() {
            document.getElementById('logContainer').innerHTML = '';
            logCount = 0;
            document.getElementById('logCount').textContent = '0 条日志';
        }

        document.getElementById('btnStart').addEventListener('click', startDetection);
        document.getElementById('btnStop').addEventListener('click', stopDetection);
        document.getElementById('btnReset').addEventListener('click', resetSystem);
        document.getElementById('btnRefresh').addEventListener('click', function() {
            updateStatus();
            updateDevices();
            loadConfig();
            loadTrajectories();
        });
        document.getElementById('btnShutdown').addEventListener('click', shutdownSystem);
        
        document.getElementById('btnReconnectRobot').addEventListener('click', () => reconnectDevice('robot'));
        document.getElementById('btnReconnectCanon').addEventListener('click', () => reconnectDevice('canon'));
        document.getElementById('btnReconnectRS').addEventListener('click', () => reconnectDevice('realsense'));

        document.getElementById('trajectorySelect').addEventListener('change', function() {
            if (this.value) {
                addHistory('选择轨迹文件: ' + this.options[this.selectedIndex].text);
            }
        });

        document.getElementById('btnReloadTraj').addEventListener('click', reloadTrajectory);

        const now = new Date();
        addHistory('系统启动 ' + now.toLocaleTimeString('zh-CN'));

        updateStatus();
        updateDevices();
        loadConfig();
        loadTrajectories();
        
        statusInterval = setInterval(updateStatus, statusPollInterval);
        deviceInterval = setInterval(updateDevices, 5000);
        connectLogs();

        window.onbeforeunload = function() {
            if (eventSource) eventSource.close();
            if (statusInterval) clearInterval(statusInterval);
            if (deviceInterval) clearInterval(deviceInterval);
        };
    </script>
</body>
</html>
'''

    def start(self):
        self.running = True
        self.thread = threading.Thread(
            target=self.app.run,
            kwargs={
                'host': self.host,
                'port': self.port,
                'debug': False,
                'use_reloader': False,
                'threaded': True
            },
            daemon=True
        )
        self.thread.start()
        logger.info(f"Web UI 服务已启动: http://{self.host}:{self.port}")

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            try:
                self.thread.join(timeout=5)
            except Exception:
                pass