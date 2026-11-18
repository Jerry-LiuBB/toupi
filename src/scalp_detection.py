#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import logging
import traceback
from enum import Enum
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils import setup_logging, ensure_directory, get_current_timestamp, get_task_id, load_config, atomic_write_json
from src.robot_controller import RobotController
from src.canon_camera import CanonCameraController
from src.realsense_camera import RealSenseController
from src.trajectory_reader import TrajectoryReader
from src.detection_info import DetectionInfoWriter

logger = logging.getLogger(__name__)


class SystemState(Enum):
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    COMPLETED = "completed"
    RESETTING = "resetting"


class ScalpDetectionSystem:
    def __init__(self, config_path="config/config.json"):
        self.config = load_config(config_path)
        self.state = SystemState.IDLE
        self.task_id = None
        self.output_dir = None
        self.image_dir = None
        self.log_dir = None
        self.error_message = None

        self.robot = None
        self.canon_camera = None
        self.realsense = None
        self.trajectory_reader = None
        self.detection_writer = None

        self.trajectory_points = []
        self.start_point = None
        self.current_point_index = 0

    def _init_components(self):
        robot_cfg = self.config["robot"]
        self.robot = RobotController(
            ip=robot_cfg["ip"],
            port=robot_cfg["port"],
            timeout=robot_cfg["timeout"],
            velocity=robot_cfg["velocity"],
            acceleration=robot_cfg["acceleration"],
            trajectory_connect=robot_cfg["trajectory_connect"],
            max_retries=robot_cfg.get("max_retries", 3),
            retry_delay=robot_cfg.get("retry_delay", 2.0)
        )

        canon_cfg = self.config["canon_camera"]
        self.canon_camera = CanonCameraController(
            exe_path=canon_cfg["exe_path"],
            config_path=canon_cfg["config_path"],
            timeout=canon_cfg["timeout"],
            server_port=canon_cfg.get("server_port", 8765)
        )

        rs_cfg = self.config["realsense"]
        self.realsense = RealSenseController(
            width=rs_cfg["width"],
            height=rs_cfg["height"],
            fps=rs_cfg["fps"],
            align_depth_to_color=rs_cfg["align_depth_to_color"],
            colorizer_scheme=rs_cfg.get("colorizer_scheme", 9),
            min_distance=rs_cfg.get("min_distance", 0.2),
            max_distance=rs_cfg.get("max_distance", 1.73),
            preset_profile=rs_cfg.get("preset_profile", "HighDensity"),
            init_max_frames=rs_cfg.get("init_max_frames", 30),
            init_min_valid_frames=rs_cfg.get("init_min_valid_frames", 3),
            init_max_retries=rs_cfg.get("init_max_retries", 2),
            init_retry_delay=rs_cfg.get("init_retry_delay", 0.5),
            hardware_reset_delay=rs_cfg.get("hardware_reset_delay", 1),
            use_frame_buffer=True
        )

        traj_cfg = self.config["trajectory"]
        self.trajectory_reader = TrajectoryReader(
            file_path=traj_cfg["file_path"],
            angle_scale=traj_cfg["angle_scale"]
        )

    def _create_output_directories(self):
        self.task_id = get_task_id()
        output_cfg = self.config["output"]
        base_path = output_cfg["base_path"]

        self.output_dir = ensure_directory(os.path.join(base_path, self.task_id))
        self.canon_raw_dir = ensure_directory(os.path.join(self.output_dir, "canonraw"))
        self.rs_raw_dir = ensure_directory(os.path.join(self.output_dir, "rsraw"))
        self.image_dir = ""
        self.log_dir = ensure_directory(os.path.join(self.output_dir, output_cfg["logs_subdir"]))

        log_file = os.path.join(self.log_dir, f"{self.task_id}.log")
        # 固定INFO: 与服务端日志级别一致(config中的log_level从未实际生效过)
        setup_logging(
            log_level="INFO",
            log_file=log_file
        )

        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"佳能图像目录: {self.canon_raw_dir}")
        logger.info(f"RealSense图像目录: {self.rs_raw_dir}")
        logger.info(f"日志目录: {self.log_dir}")

    def initialize(self):
        self.state = SystemState.INITIALIZING
        logger.info("=" * 60)
        logger.info("头皮检测系统初始化开始")
        logger.info("=" * 60)

        try:
            self._init_components()

            logger.info("[1/4] 连接机械臂...")
            if not self.robot.connect():
                raise ConnectionError("机械臂连接失败")

            logger.info("[2/4] 初始化佳能相机...")
            if not self.canon_camera.initialize():
                raise RuntimeError("佳能相机初始化失败")

            logger.info("[3/4] 初始化RealSense D435...")
            if not self.realsense.initialize():
                raise RuntimeError("RealSense D435初始化失败")

            logger.info("[4/4] 读取轨迹文件...")
            self.trajectory_points = self.trajectory_reader.read()
            if not self.trajectory_points:
                raise ValueError("轨迹文件为空")
            self.start_point = self.trajectory_reader.get_start_point()

            logger.info(f"系统初始化成功！共{len(self.trajectory_points)}个轨迹点")
            self.state = SystemState.IDLE
            return True

        except Exception as e:
            self.error_message = str(e)
            self.state = SystemState.ERROR
            logger.error(f"系统初始化失败: {e}")
            logger.error(traceback.format_exc())
            return False

    def stop_detection(self):
        """停止当前检测流程（在任何状态下都可调用）"""
        if self.state in (SystemState.RUNNING, SystemState.STOPPING, SystemState.ERROR):
            logger.info("收到停止命令，正在停止检测流程...")
            self.state = SystemState.STOPPING
            
            try:
                self.robot.emergency_stop()
            except Exception as e:
                logger.warning(f"停止机械臂失败: {e}")

            # 注意: 此处不停止RealSense相机 — 保留流水线/帧缓冲/保存线程池,
            # 停止后用户可立即再次开始检测 (停止仅中断扫描循环)
            # (之前在此处realsense.stop()会把相机彻底摧毁, 导致
            #  1)正在拍照的capture线程崩溃 2)停止后无法继续检测)

            self.state = SystemState.IDLE
            logger.info("检测流程已停止")
        else:
            logger.info(f"当前状态 {self.state.value}，无需停止")

    def start_detection(self):
        if self.state not in (SystemState.IDLE,):
            logger.error(f"当前状态 {self.state.value} 不允许启动检测")
            return False, None

        self.state = SystemState.RUNNING
        self._create_output_directories()

        logger.info("=" * 60)
        logger.info(f"开始检测流程 - 任务ID: {self.task_id}")
        logger.info(f"轨迹点数量: {len(self.trajectory_points)}")
        logger.info("=" * 60)

        self.detection_writer = DetectionInfoWriter(self.output_dir, self.task_id)

        try:
            # 自愈: 若RealSense在错误流程中被释放, 自动重新初始化, 保证可继续检测
            if self.realsense and not self.realsense.initialized:
                logger.info("RealSense相机未初始化, 正在重新初始化...")
                if not self.realsense.initialize():
                    raise RuntimeError("RealSense相机重新初始化失败")

            logger.info("移动机械臂到起始点位...")
            self.robot.move_to_start(self.start_point)

            parallel_enabled = self.config.get("system", {}).get("parallel_capture", True)
            logger.info(f"并行拍照模式: {'启用' if parallel_enabled else '禁用'}")

            continuous_enabled = self.config.get("system", {}).get("continuous_mode", False)
            logger.info(f"连续运动拍摄模式: {'启用' if continuous_enabled else '禁用'}")

            if continuous_enabled and len(self.trajectory_points) > 1:
                return self._start_detection_continuous()
            elif parallel_enabled and len(self.trajectory_points) > 1:
                return self._start_detection_parallel()
            else:
                return self._start_detection_sequential()

        except Exception as e:
            self.error_message = str(e)
            self.state = SystemState.ERROR
            logger.error(f"检测过程出错: {e}")
            logger.error(traceback.format_exc())

            if self.output_dir:
                trigger_data = {
                    "event": "scan_failed",
                    "task_id": self.task_id,
                    "out_dir": os.path.abspath(self.output_dir),
                    "error": self.error_message,
                    "current_point": self.current_point_index,
                    "total_points": len(self.trajectory_points)
                }
                trigger_path = os.path.join(self.output_dir, "trigger.json")
                try:
                    atomic_write_json(trigger_path, trigger_data)
                except Exception:
                    pass

            return False, None

    def _wait_for_stabilization(self):
        """机械臂到位后等待震荡衰减再拍照(防止照片模糊/深度图扭曲)。

        机械臂控制器报"到位"仅表示伺服到达目标角度, 相机支架的机械震荡
        还会持续数百毫秒。等待时间由config system.stabilization_time_ms控制,
        期间以50ms为步进轮询运行状态, 停止检测时不死等。
        """
        ms = self.config.get("system", {}).get("stabilization_time_ms", 0)
        if not ms or ms <= 0:
            return
        logger.info(f"[稳定等待] {ms}ms 等待机械臂震荡衰减...")
        deadline = time.time() + ms / 1000.0
        while time.time() < deadline:
            if self.state != SystemState.RUNNING:
                logger.info("[稳定等待] 检测已中断, 提前结束等待")
                return
            time.sleep(0.05)

    def _start_detection_sequential(self):
        try:
            for i, point in enumerate(self.trajectory_points):
                if self.state != SystemState.RUNNING:
                    logger.warning(f"检测流程被中断，当前状态: {self.state.value}")
                    break

                self.current_point_index = i
                logger.info(f"\n{'='*40}")
                logger.info(f"执行轨迹点 [{i+1}/{len(self.trajectory_points)}]")
                logger.info(f"关节角度: {point}")
                logger.info(f"{'='*40}")

                logger.info(f"[步骤1] 移动机械臂到轨迹点 {i}...")
                self.robot.move_to_joint(point)

                if self.state != SystemState.RUNNING:
                    logger.warning(f"检测流程被中断，跳过拍照步骤")
                    break

                self._wait_for_stabilization()

                timestamp = get_current_timestamp()

                logger.info(f"[步骤2] 触发佳能相机拍照...")
                canon_photo_path = self.canon_camera.capture(self.canon_raw_dir, photo_index=i)
                if canon_photo_path is None:
                    raise RuntimeError(f"佳能相机拍照失败: 轨迹点 {i}")
                canon_image_name = os.path.basename(canon_photo_path)
                logger.info(f"佳能相机图像: {canon_image_name}")

                if self.state != SystemState.RUNNING:
                    logger.warning(f"检测流程被中断，跳过RealSense拍照")
                    break

                logger.info(f"[步骤3] 触发RealSense D435拍照...")
                rs_result = self.realsense.capture(self.rs_raw_dir, i, timestamp)
                rs_image_name = rs_result["depth_tiff_path"]
                logger.info(f"RealSense深度图: {rs_image_name}")

                relative_angle = TrajectoryReader.calculate_relative_angle_joint(
                    point, self.start_point
                )

                self.detection_writer.add_view(
                    view_id=i,
                    scan_angle=relative_angle,
                    canon_image_name=canon_image_name,
                    rs_image_name=rs_image_name
                )

                logger.info(f"轨迹点 {i} 完成: 角度={relative_angle:.4f}°, "
                            f"佳能={canon_image_name}, 深度={rs_image_name}")

            return self._finish_detection()
        except Exception as e:
            self.error_message = str(e)
            self.state = SystemState.ERROR
            logger.error(f"检测过程出错: {e}")
            logger.error(traceback.format_exc())
            return False, None

    def _start_detection_continuous(self):
        try:
            sys_cfg = self.config.get("system", {})
            velocity = sys_cfg.get("continuous_velocity", 30)
            threshold_deg = sys_cfg.get("angle_trigger_threshold_deg", 1.0)
            poll_interval = sys_cfg.get("joint_poll_interval_ms", 20) / 1000.0
            predict_lead_deg = sys_cfg.get("photo_predict_lead_deg", 2.0)
            async_save_enabled = sys_cfg.get("async_save", True)
            fast_capture_enabled = sys_cfg.get("fast_capture", True)

            target_info = []
            for i, point in enumerate(self.trajectory_points):
                angle = TrajectoryReader.calculate_relative_angle_joint(point, self.start_point)
                target_info.append({
                    "index": i,
                    "point": list(point),
                    "target_angle": angle,
                    "captured": False,
                })

            n_points = len(target_info)
            end_point = list(self.trajectory_points[-1])

            logger.info("=" * 60)
            logger.info(f"[连续运动拍摄] 速度 velocity={velocity}, 触发阈值={threshold_deg}°, "
                        f"预判提前={predict_lead_deg}°, 目标点数={n_points}")
            logger.info(f"[连续运动拍摄] 结束点位: {end_point}")
            logger.info("=" * 60)

            logger.info("[1] 异步发送机械臂连续运动指令 (不等待到位)...")
            self.robot.move_to_joint_async(
                joint_degrees=end_point,
                velocity=velocity,
                trajectory_connect=0,
            )
            logger.info("[2] 启动关节角度轮询 + 触发拍摄循环")

            last_joint_read_time = 0.0
            current_joint = None
            safety_deadline = time.time() + max(60.0, n_points * 3.0)
            poll_ok = 0
            poll_none = 0
            last_health_log = time.time()

            while self.state == SystemState.RUNNING:
                if time.time() > safety_deadline:
                    remaining = [t for t in target_info if not t["captured"]]
                    logger.error(f"[连续运动拍摄] 安全超时, 剩余未拍照 {len(remaining)} 点")
                    raise RuntimeError(f"连续拍摄安全超时，仍有 {len(remaining)} 个点未拍照")

                if time.time() - last_joint_read_time >= poll_interval:
                    current_joint = self.robot.get_current_joint_safe()
                    last_joint_read_time = time.time()

                if current_joint is None:
                    poll_none += 1
                    time.sleep(poll_interval)
                    continue
                poll_ok += 1

                current_angle = TrajectoryReader.calculate_relative_angle_joint(
                    current_joint, self.start_point
                )

                if time.time() - last_health_log >= 5.0:
                    uncaptured = sum(1 for t in target_info if not t["captured"])
                    logger.info(f"[连续运动拍摄] 轮询健康: 成功={poll_ok} 失败={poll_none}, "
                                f"当前角度={current_angle:.2f}°, 未拍摄={uncaptured}点")
                    last_health_log = time.time()

                end_reached, _ = self.robot.wait_until_joint_close_to(
                    end_point, tolerance_deg=0.5, timeout=0.001, poll_interval=0.001
                )

                all_done = True
                for t in target_info:
                    if t["captured"]:
                        continue
                    all_done = False

                    delta = t["target_angle"] - current_angle

                    in_trigger_zone = (
                        (abs(delta) <= threshold_deg) or
                        (delta > 0 and delta <= threshold_deg + predict_lead_deg) or
                        (delta < 0 and abs(delta) <= threshold_deg)
                    )

                    if in_trigger_zone:
                        self.current_point_index = t["index"]
                        logger.info(f"\n[触发] 视图 {t['index']+1}/{n_points} 视图ID={t['index']}, "
                                    f"目标角度={t['target_angle']:.2f}°, 当前实际={current_angle:.2f}°, "
                                    f"差值={delta:+.2f}°")
                        timestamp = get_current_timestamp()

                        joint_before = current_joint

                        logger.info("  [步骤A] 触发佳能相机拍照...")
                        if self.canon_camera.use_server_mode and fast_capture_enabled:
                            canon_photo_path = self.canon_camera.capture_fast(
                                self.canon_raw_dir, photo_index=t["index"]
                            )
                        else:
                            canon_photo_path = self.canon_camera.capture(
                                self.canon_raw_dir, photo_index=t["index"]
                            )

                        logger.info("  [步骤B] 触发RealSense D435拍照...")
                        rs_result = self.realsense.capture(
                            self.rs_raw_dir, t["index"], timestamp,
                            async_save=async_save_enabled
                        )
                        rs_image_name = rs_result["depth_tiff_path"]
                        logger.info(f"  RealSense深度图: {rs_image_name}")

                        if canon_photo_path is None:
                            raise RuntimeError(f"佳能相机拍照失败: 视图 {t['index']}")
                        canon_image_name = os.path.basename(canon_photo_path)
                        logger.info(f"  佳能相机图像: {canon_image_name}")

                        joint_after = self.robot.get_current_joint_safe()
                        if joint_before is not None and joint_after is not None:
                            mid_joint = [(a + b) / 2.0 for a, b in zip(joint_before, joint_after)]
                        elif joint_after is not None:
                            mid_joint = joint_after
                        else:
                            mid_joint = current_joint
                        actual_angle = TrajectoryReader.calculate_relative_angle_joint(
                            mid_joint, self.start_point
                        )
                        logger.info(f"  记录真实扫描角度: {actual_angle:.4f}° (目标 {t['target_angle']:.4f}°, "
                                    f"偏差 {actual_angle - t['target_angle']:+.4f}°)")

                        self.detection_writer.add_view(
                            view_id=t["index"],
                            scan_angle=actual_angle,
                            canon_image_name=canon_image_name,
                            rs_image_name=rs_image_name,
                        )
                        t["captured"] = True

                        logger.info(f"  视图 {t['index']} 完成")

                if all_done:
                    logger.info(f"[连续运动拍摄] 全部 {n_points} 个视图已拍照完成")
                    break

                if end_reached:
                    remaining = [t for t in target_info if not t["captured"]]
                    if not remaining:
                        logger.info("[连续运动拍摄] 机械臂已到达终点，且全部视图已拍照")
                        break
                    if current_joint is None:
                        time.sleep(poll_interval)
                        continue
                    final_angle = TrajectoryReader.calculate_relative_angle_joint(
                        current_joint, self.start_point
                    )
                    remaining_forward = [
                        t for t in remaining if t["target_angle"] <= final_angle + threshold_deg
                    ]
                    if remaining_forward:
                        logger.warning(
                            f"[连续运动拍摄] 机械臂已到终点，但仍有 {len(remaining_forward)} "
                            f"角度点尚未触发。尝试补拍剩余点（机械臂保持终点位置静止）。"
                        )
                        self._wait_for_stabilization()
                        for t in sorted(remaining_forward, key=lambda x: x["target_angle"]):
                            if self.state != SystemState.RUNNING:
                                break
                            self.current_point_index = t["index"]
                            logger.info(f"[补拍] 视图 {t['index']+1}/{n_points} ID={t['index']}, "
                                        f"目标角度={t['target_angle']:.2f}°")
                            timestamp = get_current_timestamp()
                            if self.canon_camera.use_server_mode and fast_capture_enabled:
                                canon_photo_path = self.canon_camera.capture_fast(
                                    self.canon_raw_dir, photo_index=t["index"]
                                )
                            else:
                                canon_photo_path = self.canon_camera.capture(
                                    self.canon_raw_dir, photo_index=t["index"]
                                )
                            rs_result = self.realsense.capture(
                                self.rs_raw_dir, t["index"], timestamp,
                                async_save=async_save_enabled
                            )
                            rs_image_name = rs_result["depth_tiff_path"]
                            if canon_photo_path is None:
                                raise RuntimeError(f"补拍失败: 视图 {t['index']}")
                            canon_image_name = os.path.basename(canon_photo_path)
                            j = self.robot.get_current_joint_safe() or current_joint
                            actual_angle = TrajectoryReader.calculate_relative_angle_joint(
                                j, self.start_point
                            )
                            self.detection_writer.add_view(
                                view_id=t["index"],
                                scan_angle=actual_angle,
                                canon_image_name=canon_image_name,
                                rs_image_name=rs_image_name,
                            )
                            t["captured"] = True
                            logger.info(f"[补拍] 视图 {t['index']} 完成")
                    break

                time.sleep(poll_interval)

            logger.info("[3] 等待机械臂最终到位...")
            self.robot.wait_until_joint_close_to(
                end_point, tolerance_deg=0.5, timeout=60, poll_interval=0.05
            )

            return self._finish_detection(async_save_enabled)
        except Exception as e:
            self.error_message = str(e)
            self.state = SystemState.ERROR
            logger.error(f"检测过程出错: {e}")
            logger.error(traceback.format_exc())
            return False, None

    def _start_detection_parallel(self):
        try:
            logger.info("使用并行模式: 机械臂移动与拍照并行")

            async_save_enabled = self.config.get("system", {}).get("async_save", True)
            fast_capture_enabled = self.config.get("system", {}).get("fast_capture", True)
            logger.info(f"异步保存: {'启用' if async_save_enabled else '禁用'}")
            logger.info(f"快速拍照: {'启用' if fast_capture_enabled else '禁用'}")

            for i, point in enumerate(self.trajectory_points):
                if self.state != SystemState.RUNNING:
                    logger.warning(f"检测流程被中断，当前状态: {self.state.value}")
                    break

                self.current_point_index = i
                logger.info(f"\n{'='*40}")
                logger.info(f"执行轨迹点 [{i+1}/{len(self.trajectory_points)}]")
                logger.info(f"关节角度: {point}")
                logger.info(f"{'='*40}")

                if i == 0:
                    logger.info(f"[步骤1] 移动机械臂到轨迹点 {i}...")
                    self.robot.move_to_joint(point)
                else:
                    logger.info(f"[步骤1] 等待机械臂到位...")
                    self.robot.wait_for_position()

                if self.state != SystemState.RUNNING:
                    logger.warning(f"检测流程被中断，跳过拍照步骤")
                    break

                self._wait_for_stabilization()

                timestamp = get_current_timestamp()

                logger.info(f"[步骤2] 触发佳能相机拍照...")
                if self.canon_camera.use_server_mode and fast_capture_enabled:
                    canon_photo_path = self.canon_camera.capture_fast(self.canon_raw_dir, photo_index=i)
                elif self.canon_camera.use_server_mode:
                    self.canon_camera.capture_async(self.canon_raw_dir, photo_index=i)
                else:
                    canon_photo_path = self.canon_camera.capture(self.canon_raw_dir, photo_index=i)

                logger.info(f"[步骤3] 触发RealSense D435拍照...")
                rs_result = self.realsense.capture(
                    self.rs_raw_dir, i, timestamp, async_save=async_save_enabled
                )
                rs_image_name = rs_result["depth_tiff_path"]
                logger.info(f"RealSense深度图: {rs_image_name}")

                if self.canon_camera.use_server_mode and not fast_capture_enabled:
                    logger.info(f"[步骤4] 等待佳能相机拍照完成...")
                    canon_photo_path = self.canon_camera.wait_for_capture(timeout=15)

                if canon_photo_path is None:
                    raise RuntimeError(f"佳能相机拍照失败: 轨迹点 {i}")
                canon_image_name = os.path.basename(canon_photo_path)
                logger.info(f"佳能相机图像: {canon_image_name}")

                relative_angle = TrajectoryReader.calculate_relative_angle_joint(
                    point, self.start_point
                )

                self.detection_writer.add_view(
                    view_id=i,
                    scan_angle=relative_angle,
                    canon_image_name=canon_image_name,
                    rs_image_name=rs_image_name
                )

                if i < len(self.trajectory_points) - 1:
                    next_point = self.trajectory_points[i + 1]
                    logger.info(f"[步骤5] 异步发送下一个点位移动命令...")
                    self.robot.move_to_joint_async(next_point)

                logger.info(f"轨迹点 {i} 完成: 角度={relative_angle:.4f}°, "
                            f"佳能={canon_image_name}, 深度={rs_image_name}")

            return self._finish_detection(async_save_enabled)
        except Exception as e:
            self.error_message = str(e)
            self.state = SystemState.ERROR
            logger.error(f"检测过程出错: {e}")
            logger.error(traceback.format_exc())
            return False, None

    def _finish_detection(self, async_save_enabled=False):
        if self.state != SystemState.RUNNING:
            return False, None

        if async_save_enabled:
            logger.info("等待所有异步图像保存完成...")
            self.realsense.wait_for_all_saves()
            logger.info("所有异步图像保存完成")

        xml_path = self.detection_writer.write_xml(
            self.config["output"]["xml_filename"]
        )
        summary_path = self.detection_writer.write_summary()

        result = {
            "output_dir": os.path.abspath(self.output_dir),
            "image_dir": "",
            "xml_path": os.path.abspath(xml_path),
            "summary_path": os.path.abspath(summary_path),
            "task_id": self.task_id,
            "total_points": len(self.trajectory_points)
        }

        trigger_data = {
            "event": "scan_completed",
            "task_id": self.task_id,
            "out_dir": os.path.abspath(self.output_dir),
            "poses_file": os.path.abspath(xml_path),
            "total_points": len(self.trajectory_points)
        }
        trigger_path = os.path.join(self.output_dir, "trigger.json")
        atomic_write_json(trigger_path, trigger_data)

        logger.info("=" * 60)
        logger.info("检测流程完成！")
        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"XML文件: {xml_path}")
        logger.info(f"摘要文件: {summary_path}")
        logger.info(f"触发文件: {trigger_path}")
        logger.info("=" * 60)

        self.state = SystemState.IDLE
        self.current_point_index = 0

        return True, result

    def _handle_error(self):
        logger.error("=" * 60)
        logger.error("错误处理流程启动")
        logger.error("=" * 60)

        try:
            logger.info("[1/3] 紧急停止机械臂...")
            if self.robot and self.robot.connected:
                self.robot.emergency_stop()
        except Exception as e:
            logger.error(f"紧急停止机械臂失败: {e}")

        try:
            logger.info("[2/3] 停止RealSense相机...")
            if self.realsense:
                self.realsense.stop()
        except Exception as e:
            logger.error(f"停止RealSense失败: {e}")

        try:
            logger.info("[3/3] 释放相机资源...")
            if hasattr(self, 'canon_camera') and self.canon_camera:
                self.canon_camera.stop()
        except Exception as e:
            logger.error(f"停止佳能相机失败: {e}")

        logger.info(f"错误信号: {self.error_message}")
        logger.info("错误处理完成，请使用复位功能恢复系统")

    def reset_system(self):
        if self.state == SystemState.IDLE:
            logger.info("系统当前处于空闲状态，无需复位")
            return True

        if self.state == SystemState.RUNNING:
            logger.warning("系统正在运行中，先执行错误处理")
            self._handle_error()

        self.state = SystemState.RESETTING
        logger.info("=" * 60)
        logger.info("系统复位流程启动")
        logger.info("=" * 60)

        try:
            logger.info("[1/4] 复位机械臂到起始点...")
            if self.robot and self.robot.connected:
                self.robot.reset_to_start()
                logger.info("机械臂已复位到起始点")
            else:
                logger.info("机械臂未连接，尝试重新连接...")
                if self.robot:
                    self.robot.connect()
                    self.robot.reset_to_start()

            logger.info("[2/4] 重新初始化佳能相机...")
            if self.canon_camera:
                self.canon_camera.reset()
                logger.info("佳能相机重新初始化成功")

            logger.info("[3/4] 重新初始化RealSense D435...")
            if self.realsense:
                self.realsense.reset()
                logger.info("RealSense D435重新初始化成功")

            logger.info("[4/4] 清除错误状态...")
            self.error_message = None
            self.state = SystemState.IDLE

            logger.info("=" * 60)
            logger.info("系统复位完成！可以重新开始检测")
            logger.info("=" * 60)
            return True

        except Exception as e:
            self.error_message = str(e)
            self.state = SystemState.ERROR
            logger.error(f"系统复位失败: {e}")
            logger.error(traceback.format_exc())
            return False

    def shutdown(self):
        logger.info("系统关闭中...")

        try:
            if self.realsense:
                self.realsense.stop()
        except Exception as e:
            logger.error(f"关闭RealSense失败: {e}")

        try:
            if self.robot:
                self.robot.disconnect()
        except Exception as e:
            logger.error(f"断开机械臂连接失败: {e}")

        self.state = SystemState.IDLE
        logger.info("系统已关闭")

    def reload_trajectory(self, file_path):
        """热重载轨迹文件 (TCP/HTTP共用入口)。

        约束与保证:
        - 仅IDLE状态允许, 防止扫描进行中轨迹被换导致错乱
        - 文件必须在轨迹目录内且为.txt后缀, 防止任意文件读取
        - 原子性: 先用临时reader读成功才替换现有轨迹,
          坏文件不会污染当前生效的轨迹点
        """
        if self.state != SystemState.IDLE:
            raise RuntimeError(f"当前系统状态为 {self.state.value}，仅空闲(IDLE)时允许重载轨迹")

        traj_dir = os.path.normcase(os.path.realpath(
            os.path.dirname(self.config["trajectory"]["file_path"])))
        real_path = os.path.realpath(file_path)
        if os.path.normcase(os.path.dirname(real_path)) != traj_dir:
            raise ValueError("轨迹文件必须位于轨迹目录内")
        if not real_path.lower().endswith(".txt"):
            raise ValueError("轨迹文件必须为 .txt 后缀")
        if not os.path.isfile(real_path):
            raise ValueError(f"轨迹文件不存在: {real_path}")

        reader = TrajectoryReader(
            file_path=real_path,
            angle_scale=self.config["trajectory"]["angle_scale"]
        )
        points = reader.read()
        if not points:
            raise ValueError("轨迹文件为空或无有效轨迹点")

        self.trajectory_reader = reader
        self.trajectory_points = points
        self.start_point = reader.get_start_point()
        logger.info(f"轨迹热重载成功: {real_path}, 共{len(points)}个点")
        return {
            "trajectory_file": real_path,
            "point_count": len(points),
            "start_point": self.start_point
        }

    def get_state(self):
        return {
            "state": self.state.value,
            "task_id": self.task_id,
            "current_point": self.current_point_index,
            "total_points": len(self.trajectory_points),
            "error_message": self.error_message,
            "output_dir": self.output_dir
        }


def main():
    config_path = "config/config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    setup_logging(log_level="INFO")

    system = ScalpDetectionSystem(config_path)

    try:
        if not system.initialize():
            logger.error("系统初始化失败，程序退出")
            return

        success, result = system.start_detection()

        if success:
            logger.info(f"检测成功！输出路径: {result}")
        else:
            logger.error("检测失败")
            logger.info("尝试复位系统...")
            if system.reset_system():
                logger.info("系统复位成功")
            else:
                logger.error("系统复位失败")

    except KeyboardInterrupt:
        logger.info("用户中断，正在停止...")
        system._handle_error()
    finally:
        system.shutdown()


if __name__ == "__main__":
    main()
