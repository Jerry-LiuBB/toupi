#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import math

logger = logging.getLogger(__name__)


class TrajectoryReader:
    def __init__(self, file_path, angle_scale=1000):
        self.file_path = file_path
        self.angle_scale = angle_scale
        self.trajectory_points = []
        self.start_point = None

    def read(self):
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"轨迹文件不存在: {self.file_path}")

        self.trajectory_points = []

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue

                    parts = line.split(',')
                    if len(parts) != 6:
                        logger.warning(f"第{line_num}行格式错误，跳过: {line}")
                        continue

                    try:
                        point = [float(p.strip()) for p in parts]
                        self.trajectory_points.append(point)
                    except ValueError as e:
                        logger.warning(f"第{line_num}行数值解析失败，跳过: {e}")
                        continue

            if not self.trajectory_points:
                raise ValueError("轨迹文件为空或格式全部无效")

            self.start_point = self.trajectory_points[0]
            logger.info(f"读取轨迹文件成功，共{len(self.trajectory_points)}个轨迹点")
            logger.info(f"起始点位: {self.start_point}")
            return self.trajectory_points

        except Exception as e:
            logger.error(f"读取轨迹文件失败: {e}")
            raise

    def get_points(self):
        return self.trajectory_points

    def get_start_point(self):
        return self.start_point

    def get_point_count(self):
        return len(self.trajectory_points)

    @staticmethod
    def calculate_relative_angle(current_point, start_point):
        if start_point is None or current_point is None:
            return 0.0

        if len(current_point) < 2 or len(start_point) < 2:
            return 0.0

        dx = current_point[0] - start_point[0]
        dy = current_point[1] - start_point[1]

        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0

        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)
        return angle_deg

    @staticmethod
    def calculate_relative_angle_joint(current_point, start_point):
        if start_point is None or current_point is None:
            return 0.0

        if len(current_point) < 1 or len(start_point) < 1:
            return 0.0

        relative_angle = current_point[0] - start_point[0]
        return relative_angle

    @staticmethod
    def degrees_to_int_list(joint_degrees, scale=1000):
        return [int(round(angle * scale)) for angle in joint_degrees]
