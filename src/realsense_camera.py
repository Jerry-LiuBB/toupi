#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import numpy as np

logger = logging.getLogger(__name__)

try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
except ImportError:
    REALSENSE_AVAILABLE = False
    logger.warning("pyrealsense2未安装，RealSense相机功能不可用")

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("opencv未安装，图像保存功能受限")


class RealSenseController:
    def __init__(self, width=640, height=480, fps=30, align_depth_to_color=True):
        self.width = width
        self.height = height
        self.fps = fps
        self.align_depth_to_color = align_depth_to_color
        self.pipeline = None
        self.align = None
        self.initialized = False
        self.depth_scale = None

    def initialize(self):
        if not REALSENSE_AVAILABLE:
            logger.error("pyrealsense2未安装，无法初始化RealSense相机")
            return False

        try:
            ctx = rs.context()
            devices = ctx.query_devices()
            if len(devices) == 0:
                logger.error("未检测到RealSense设备")
                return False

            device = devices[0]
            device_name = device.get_info(rs.camera_info.name)
            serial = device.get_info(rs.camera_info.serial_number)
            logger.info(f"检测到RealSense设备: {device_name}, 序列号: {serial}")

            self.pipeline = rs.pipeline()
            config = rs.config()

            try:
                config.enable_device(serial)
            except Exception:
                pass

            config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)
            config.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, self.fps)

            profile = self.pipeline.start(config)

            depth_sensor = profile.get_device().first_depth_sensor()
            self.depth_scale = depth_sensor.get_depth_scale()
            logger.info(f"深度比例因子: {self.depth_scale}")

            if self.align_depth_to_color:
                self.align = rs.align(rs.stream.color)

            for _ in range(30):
                self.pipeline.wait_for_frames()

            self.initialized = True
            logger.info("RealSense D435初始化成功")
            return True

        except Exception as e:
            logger.error(f"RealSense初始化失败: {e}")
            self.initialized = False
            return False

    def capture(self, save_path, index, timestamp):
        if not self.initialized:
            raise RuntimeError("RealSense相机未初始化")

        save_path = os.path.abspath(save_path)
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

        try:
            frames = self.pipeline.wait_for_frames()

            if self.align:
                frames = self.align.process(frames)

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()

            if not color_frame or not depth_frame:
                raise RuntimeError("获取帧数据失败")

            color_image = np.asanyarray(color_frame.get_data())
            depth_image = np.asanyarray(depth_frame.get_data())

            depth_tiff_name = f"DEPTH_{index:06d}.tiff"
            depth_tiff_path = os.path.join(save_path, depth_tiff_name)

            color_image_name = f"RS_color_{index:06d}.png"
            color_image_path = os.path.join(save_path, color_image_name)

            if CV2_AVAILABLE:
                cv2.imwrite(depth_tiff_path, depth_image)
                cv2.imwrite(color_image_path, color_image)
            else:
                np.save(depth_tiff_path.replace('.tiff', '.npy'), depth_image)
                np.save(color_image_path.replace('.png', '.npy'), color_image)

            logger.info(f"RealSense深度图保存: {depth_tiff_path}")
            logger.info(f"RealSense彩色图保存: {color_image_path}")

            return {
                "depth_tiff_path": depth_tiff_name,
                "color_image_path": color_image_name,
                "depth_data": depth_image,
                "color_data": color_image
            }

        except Exception as e:
            logger.error(f"RealSense拍照失败: {e}")
            raise

    def stop(self):
        if self.pipeline:
            try:
                self.pipeline.stop()
            except Exception as e:
                logger.warning(f"RealSense停止时出错: {e}")
            self.pipeline = None
        self.initialized = False
        self.align = None
        logger.info("RealSense相机已停止")

    def reset(self):
        self.stop()
        time.sleep(1)
        return self.initialize()
