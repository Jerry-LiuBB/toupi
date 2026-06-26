#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import json
import time
import logging

logger = logging.getLogger(__name__)


class RobotController:
    def __init__(self, ip, port, timeout=30, velocity=50, acceleration=0, trajectory_connect=0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.velocity = velocity
        self.acceleration = acceleration
        self.trajectory_connect = trajectory_connect
        self.socket = None
        self.connected = False
        self.start_joint = None

    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.settimeout(self.timeout)
            self.socket.connect((self.ip, self.port))
            self.connected = True
            logger.info(f"机械臂连接成功: {self.ip}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"机械臂连接失败: {e}")
            self.connected = False
            return False

    def disconnect(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        self.connected = False
        logger.info("机械臂连接已断开")

    def _send_command(self, command_dict):
        if not self.connected or not self.socket:
            raise ConnectionError("机械臂未连接")

        try:
            cmd_str = json.dumps(command_dict)
            self.socket.sendall(cmd_str.encode('utf-8'))
            logger.debug(f"发送命令: {cmd_str}")
            return True
        except Exception as e:
            logger.error(f"发送命令失败: {e}")
            self.connected = False
            raise

    def _receive_response(self, buffer_size=1024):
        if not self.connected or not self.socket:
            raise ConnectionError("机械臂未连接")

        try:
            data = self.socket.recv(buffer_size)
            if not data:
                raise ConnectionError("连接已断开，未收到数据")
            response = json.loads(data.decode('utf-8'))
            logger.debug(f"收到响应: {response}")
            return response
        except json.JSONDecodeError as e:
            logger.error(f"响应JSON解析失败: {e}, 原始数据: {data}")
            raise
        except Exception as e:
            logger.error(f"接收响应失败: {e}")
            self.connected = False
            raise

    def _degrees_to_int(self, joint_degrees):
        return [int(round(angle * 1000)) for angle in joint_degrees]

    def move_to_joint(self, joint_degrees, velocity=None, trajectory_connect=None):
        if velocity is None:
            velocity = self.velocity
        if trajectory_connect is None:
            trajectory_connect = self.trajectory_connect

        joint_int = self._degrees_to_int(joint_degrees)

        command = {
            "command": "movej",
            "joint": joint_int,
            "v": velocity,
            "r": self.acceleration,
            "trajectory_connect": trajectory_connect
        }

        logger.info(f"移动到关节角度: {joint_degrees} -> 整数: {joint_int}")

        self._send_command(command)

        receive_resp = self._receive_response()
        if receive_resp.get("command") == "movej":
            if not receive_resp.get("receive_state", False):
                raise RuntimeError(f"机械臂指令接收失败: {receive_resp}")

        logger.info("指令接收成功，等待运动到位...")

        state_resp = self._receive_response()
        if state_resp.get("state") == "current_trajectory_state":
            if not state_resp.get("trajectory_state", False):
                raise RuntimeError(f"机械臂运动到位失败: {state_resp}")

        logger.info("机械臂运动到位成功")
        return True

    def move_to_start(self, start_joint_degrees):
        self.start_joint = start_joint_degrees
        return self.move_to_joint(start_joint_degrees)

    def reset_to_start(self):
        if self.start_joint is None:
            raise RuntimeError("起始点位未设置，无法复位")
        logger.info(f"复位到起始点位: {self.start_joint}")
        return self.move_to_joint(self.start_joint, trajectory_connect=0)

    def get_current_joint(self):
        command = {
            "command": "get_joint_degree"
        }
        self._send_command(command)
        response = self._receive_response()
        if "degree" in response:
            return [d / 1000.0 for d in response["degree"]]
        return None

    def emergency_stop(self):
        command = {
            "command": "stop"
        }
        try:
            self._send_command(command)
            logger.warning("紧急停止命令已发送")
        except Exception as e:
            logger.error(f"紧急停止命令发送失败: {e}")
