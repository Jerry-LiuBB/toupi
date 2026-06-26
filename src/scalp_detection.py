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
            trajectory_connect=robot_cfg["trajectory_connect"]
        )

        canon_cfg = self.config["canon_camera"]
        self.canon_camera = CanonCameraController(
            exe_path=canon_cfg["exe_path"],
            config_path=canon_cfg["config_path"],
            timeout=canon_cfg["timeout"]
        )

        rs_cfg = self.config["realsense"]
        self.realsense = RealSenseController(
            width=rs_cfg["width"],
            height=rs_cfg["height"],
            fps=rs_cfg["fps"],
            align_depth_to_color=rs_cfg["align_depth_to_color"]
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
        self.image_dir = ensure_directory(os.path.join(self.output_dir, output_cfg["images_subdir"]))
        self.log_dir = ensure_directory(os.path.join(self.output_dir, output_cfg["logs_subdir"]))

        log_file = os.path.join(self.log_dir, f"{self.task_id}.log")
        setup_logging(
            log_level=self.config["system"]["log_level"],
            log_file=log_file
        )

        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"图像目录: {self.image_dir}")
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
            logger.info("移动机械臂到起始点位...")
            self.robot.move_to_start(self.start_point)

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

                timestamp = get_current_timestamp()
                logger.info(f"[步骤2] 暂停RealSense相机...")
                self.realsense.stop()
                time.sleep(1)

                logger.info(f"[步骤3] 触发佳能相机拍照...")
                canon_photo_path = self.canon_camera.capture(self.image_dir)
                if canon_photo_path is None:
                    raise RuntimeError(f"佳能相机拍照失败: 轨迹点 {i}")
                canon_image_name = os.path.basename(canon_photo_path)
                logger.info(f"佳能相机图像: {canon_image_name}")

                logger.info(f"[步骤4] 恢复RealSense相机...")
                self.realsense.initialize()
                time.sleep(1)

                logger.info(f"[步骤5] 触发RealSense D435拍照...")
                rs_result = self.realsense.capture(self.image_dir, i, timestamp)
                rs_image_name = rs_result["depth_tiff_path"]
                logger.info(f"RealSense深度图: {rs_image_name}")

                relative_angle = TrajectoryReader.calculate_relative_angle_joint(
                    point, self.start_point
                )

                self.detection_writer.add_view(
                    view_id=i,
                    scan_angle=relative_angle,
                    canon_image_name=canon_image_name,
                    rs_image_name=rs_image_name,
                    joint_pose=point,
                    timestamp=timestamp
                )

                logger.info(f"轨迹点 {i} 完成: 角度={relative_angle:.4f}°, "
                            f"佳能={canon_image_name}, 深度={rs_image_name}")

            if self.state == SystemState.RUNNING:
                xml_path = self.detection_writer.write_xml(
                    self.config["output"]["xml_filename"]
                )
                summary_path = self.detection_writer.write_summary()

                result = {
                    "output_dir": os.path.abspath(self.output_dir),
                    "image_dir": os.path.abspath(self.image_dir),
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
            else:
                return False, None

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
                try:
                    trigger_path = os.path.join(self.output_dir, "trigger.json")
                    atomic_write_json(trigger_path, trigger_data)
                except Exception as te:
                    logger.error(f"写入错误触发文件失败: {te}")

            self._handle_error()
            return False, None

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
