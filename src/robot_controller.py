#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import socket
import json
import time
import logging

logger = logging.getLogger(__name__)


class RobotController:
    def __init__(self, ip, port, timeout=30, velocity=50, acceleration=0, trajectory_connect=0, max_retries=3, retry_delay=2.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.velocity = velocity
        self.acceleration = acceleration
        self.trajectory_connect = trajectory_connect
        self.max_retries = max_retries
        self.retry_delay = retry_delay
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

    def move_to_joint(self, joint_degrees, velocity=None, trajectory_connect=None, wait=True):
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

        last_error = None
        for attempt in range(self.max_retries):
            try:
                if not self.connected:
                    logger.info(f"第 {attempt+1}/{self.max_retries} 次尝试重新连接机械臂...")
                    if not self.connect():
                        raise RuntimeError("重新连接机械臂失败")

                self._send_command(command)

                receive_resp = self._receive_response()
                if receive_resp.get("command") == "movej":
                    if not receive_resp.get("receive_state", False):
                        raise RuntimeError(f"机械臂指令接收失败: {receive_resp}")

                logger.info("指令接收成功")

                if not wait:
                    logger.info("异步模式，不等待运动到位")
                    return True

                logger.info("等待运动到位...")

                state_resp = self._receive_response()
                if state_resp.get("state") == "current_trajectory_state":
                    if not state_resp.get("trajectory_state", False):
                        raise RuntimeError(f"机械臂运动到位失败: {state_resp}")

                logger.info("机械臂运动到位成功")
                return True

            except Exception as e:
                last_error = e
                logger.warning(f"第 {attempt+1}/{self.max_retries} 次尝试失败: {e}")
                self.connected = False
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)

        raise RuntimeError(f"机械臂移动失败，已尝试 {self.max_retries} 次: {last_error}")

    def move_to_joint_async(self, joint_degrees, velocity=None, trajectory_connect=None):
        return self.move_to_joint(joint_degrees, velocity, trajectory_connect, wait=False)

    def wait_for_position(self, timeout=30):
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                state_resp = self._receive_response()
                if state_resp.get("state") == "current_trajectory_state":
                    if state_resp.get("trajectory_state", False):
                        logger.info("机械臂运动到位成功")
                        return True
            except Exception as e:
                logger.debug(f"等待到位时异常: {e}")
                time.sleep(0.5)
                continue
            time.sleep(0.1)
        raise RuntimeError(f"等待机械臂到位超时 ({timeout}秒)")

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
        # RealMan协议实际响应格式: {"joint": [J1×1000, ...], "state": "joint_degree"}
        # (2026-09-28实测: 之前误校验"degree"键, 导致正确响应被当作错位响应全部拒绝,
        #  连续模式轮询永远失败→零拍照+每秒约25次重连风暴)
        if "joint" not in response:
            # 响应错位(读到残留的stop/运动完成推送消息): 必须抛错触发上层重试+重连,
            # 重连会清空积压队列; 若静默返回None, safe包装会把它当成功值直接返回,
            # 重试机制完全失效, 导致连续模式轮询永远拿不到角度(零拍照)
            raise RuntimeError(f"get_joint_degree响应异常: {response}")
        return [d / 1000.0 for d in response["joint"]]

    def get_current_joint_safe(self, max_retries=5, retry_interval=0.01):
        last_err = None
        for attempt in range(max_retries):
            try:
                if not self.connected:
                    if not self.connect():
                        raise RuntimeError("机械臂未连接且重连失败")
                return self.get_current_joint()
            except Exception as e:
                last_err = e
                self.connected = False
                time.sleep(retry_interval)
        logger.warning(f"get_current_joint_safe 连续{max_retries}次失败: {last_err}")
        return None

    def wait_until_joint_close_to(self, target, tolerance_deg=0.3, timeout=30, poll_interval=0.02):
        deadline = time.time() + timeout
        while time.time() < deadline:
            current = self.get_current_joint_safe()
            if current is not None:
                max_err = max(abs(a - b) for a, b in zip(current, target))
                if max_err <= tolerance_deg:
                    return True, max_err
            time.sleep(poll_interval)
        current = self.get_current_joint_safe()
        if current is None:
            return False, None
        max_err = max(abs(a - b) for a, b in zip(current, target))
        return False, max_err

    def emergency_stop(self):
        command = {
            "command": "stop"
        }
        try:
            self._send_command(command)
            try:
                # 消费stop命令的响应, 避免残留消息导致后续通信错位
                self._receive_response()
            except Exception:
                pass
            logger.warning("紧急停止命令已发送")
        except Exception as e:
            logger.error(f"紧急停止命令发送失败: {e}")
