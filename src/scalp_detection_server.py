#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import socket
import threading
import logging
import traceback
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scalp_detection import ScalpDetectionSystem, SystemState
from src.utils import setup_logging, load_config

logger = logging.getLogger(__name__)


class ScalpDetectionServer:
    PROTOCOL_DELIMITER = "\n"

    def __init__(self, config_path="config/config.json"):
        self.config = load_config(config_path)
        self.system = ScalpDetectionSystem(config_path)

        server_cfg = self.config.get("server", {})
        self.host = server_cfg.get("host", "0.0.0.0")
        self.port = server_cfg.get("port", 9999)
        self.buffer_size = server_cfg.get("buffer_size", 4096)
        self.timeout = server_cfg.get("timeout", 300)

        self.server_socket = None
        self.running = False
        self.detection_lock = threading.Lock()
        self.client_threads = []

    def start(self):
        logger.info("=" * 60)
        logger.info("头皮检测系统服务模式启动")
        logger.info(f"监听地址: {self.host}:{self.port}")
        logger.info("=" * 60)

        if not self.system.initialize():
            logger.error("系统初始化失败，无法启动服务")
            return False

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            self.server_socket.settimeout(1.0)
            self.running = True

            logger.info(f"服务已启动，等待客户端连接...")
            logger.info(f"支持的命令: start_detection, get_status, reset, shutdown")

            while self.running:
                try:
                    client_socket, client_address = self.server_socket.accept()
                    logger.info(f"客户端连接: {client_address}")

                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, client_address),
                        daemon=True
                    )
                    client_thread.start()
                    self.client_threads.append(client_thread)

                except socket.timeout:
                    continue
                except OSError:
                    if self.running:
                        logger.error("服务端Socket异常")
                    break

        except Exception as e:
            logger.error(f"服务启动失败: {e}")
            logger.error(traceback.format_exc())
            return False
        finally:
            self.stop()

        return True

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
            self.server_socket = None

        self.system.shutdown()
        logger.info("服务已停止")

    def _handle_client(self, client_socket, client_address):
        client_socket.settimeout(self.timeout)

        try:
            while self.running:
                try:
                    data = self._recv_message(client_socket)
                    if data is None:
                        logger.info(f"客户端断开连接: {client_address}")
                        break

                    logger.info(f"收到命令 [{client_address}]: {data}")

                    try:
                        request = json.loads(data)
                    except json.JSONDecodeError as e:
                        response = self._make_response(False, error=f"JSON解析失败: {e}")
                        self._send_message(client_socket, response)
                        continue

                    command = request.get("command", "")
                    params = request.get("params", {})

                    response = self._dispatch_command(command, params)
                    self._send_message(client_socket, response)

                    if command == "shutdown":
                        logger.info("收到关闭命令，服务即将停止")
                        self.running = False
                        break

                except socket.timeout:
                    response = self._make_response(False, error="操作超时")
                    self._send_message(client_socket, response)
                    break
                except ConnectionResetError:
                    logger.info(f"客户端连接重置: {client_address}")
                    break
                except Exception as e:
                    logger.error(f"处理客户端请求异常: {e}")
                    try:
                        response = self._make_response(False, error=str(e))
                        self._send_message(client_socket, response)
                    except Exception:
                        pass
                    break

        finally:
            try:
                client_socket.close()
            except Exception:
                pass
            logger.info(f"客户端连接已关闭: {client_address}")

    def _dispatch_command(self, command, params):
        if command == "start_detection":
            return self._cmd_start_detection(params)
        elif command == "get_status":
            return self._cmd_get_status()
        elif command == "reset":
            return self._cmd_reset()
        elif command == "shutdown":
            return self._cmd_shutdown()
        elif command == "reload_trajectory":
            return self._cmd_reload_trajectory(params)
        else:
            return self._make_response(False, error=f"未知命令: {command}")

    def _cmd_start_detection(self, params):
        if not self.detection_lock.acquire(blocking=False):
            return self._make_response(
                False,
                error="检测任务正在执行中，请等待完成后再试"
            )

        try:
            current_state = self.system.state
            if current_state != SystemState.IDLE:
                return self._make_response(
                    False,
                    error=f"当前系统状态为 {current_state.value}，无法启动检测"
                )

            if params.get("trajectory_file"):
                if self.system.trajectory_reader is None:
                    from src.trajectory_reader import TrajectoryReader
                    traj_cfg = self.system.config["trajectory"]
                    self.system.trajectory_reader = TrajectoryReader(
                        file_path=params["trajectory_file"],
                        angle_scale=traj_cfg["angle_scale"]
                    )
                else:
                    self.system.trajectory_reader.file_path = params["trajectory_file"]
                self.system.trajectory_points = self.system.trajectory_reader.read()
                self.system.start_point = self.system.trajectory_reader.get_start_point()
                logger.info(f"使用指定轨迹文件: {params['trajectory_file']}")

            logger.info("开始执行检测任务...")
            success, result = self.system.start_detection()

            if success:
                return self._make_response(
                    True,
                    data=result,
                    message="检测完成，文件路径已返回"
                )
            else:
                return self._make_response(
                    False,
                    error=self.system.error_message or "检测执行失败"
                )

        except Exception as e:
            logger.error(f"检测任务异常: {e}")
            logger.error(traceback.format_exc())
            return self._make_response(False, error=str(e))
        finally:
            self.detection_lock.release()

    def _cmd_get_status(self):
        state_info = self.system.get_state()
        return self._make_response(
            True,
            data=state_info,
            message=f"当前状态: {state_info['state']}"
        )

    def _cmd_reset(self):
        try:
            success = self.system.reset_system()
            if success:
                return self._make_response(True, message="系统复位成功，可以重新开始检测")
            else:
                return self._make_response(False, error="系统复位失败")
        except Exception as e:
            return self._make_response(False, error=f"复位异常: {e}")

    def _cmd_shutdown(self):
        return self._make_response(True, message="服务即将关闭")

    def _cmd_reload_trajectory(self, params):
        try:
            traj_file = params.get("trajectory_file")
            if not traj_file:
                return self._make_response(False, error="未指定轨迹文件路径")

            if self.system.trajectory_reader is None:
                from src.trajectory_reader import TrajectoryReader
                traj_cfg = self.system.config["trajectory"]
                self.system.trajectory_reader = TrajectoryReader(
                    file_path=traj_file,
                    angle_scale=traj_cfg["angle_scale"]
                )
            else:
                self.system.trajectory_reader.file_path = traj_file
            self.system.trajectory_points = self.system.trajectory_reader.read()
            self.system.start_point = self.system.trajectory_reader.get_start_point()

            return self._make_response(
                True,
                data={
                    "trajectory_file": traj_file,
                    "point_count": len(self.system.trajectory_points),
                    "start_point": self.system.start_point
                },
                message=f"轨迹文件重新加载成功，共{len(self.system.trajectory_points)}个点"
            )
        except Exception as e:
            return self._make_response(False, error=f"加载轨迹文件失败: {e}")

    @staticmethod
    def _make_response(success, data=None, message=None, error=None):
        resp = {"success": success}
        if data is not None:
            resp["data"] = data
        if message is not None:
            resp["message"] = message
        if error is not None:
            resp["error"] = error
        return resp

    def _recv_message(self, sock):
        chunks = []
        while True:
            try:
                chunk = sock.recv(self.buffer_size)
                if not chunk:
                    return None
                text = chunk.decode('utf-8')
                if self.PROTOCOL_DELIMITER in text:
                    parts = text.split(self.PROTOCOL_DELIMITER)
                    chunks.append(parts[0])
                    return "".join(chunks)
                chunks.append(text)
            except Exception:
                return None

    def _send_message(self, sock, response_dict):
        msg = json.dumps(response_dict, ensure_ascii=False) + self.PROTOCOL_DELIMITER
        sock.sendall(msg.encode('utf-8'))


class ScalpDetectionClient:
    def __init__(self, host="127.0.0.1", port=9999, timeout=300):
        self.host = host
        self.port = port
        self.timeout = timeout

    def send_command(self, command, params=None):
        if params is None:
            params = {}

        request = {"command": command, "params": params}

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))

            msg = json.dumps(request, ensure_ascii=False) + "\n"
            sock.sendall(msg.encode('utf-8'))

            chunks = []
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                text = chunk.decode('utf-8')
                if "\n" in text:
                    parts = text.split("\n")
                    chunks.append(parts[0])
                    break
                chunks.append(text)

            response_str = "".join(chunks)
            response = json.loads(response_str)
            return response

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def start_detection(self, trajectory_file=None):
        params = {}
        if trajectory_file:
            params["trajectory_file"] = trajectory_file
        return self.send_command("start_detection", params)

    def get_status(self):
        return self.send_command("get_status")

    def reset(self):
        return self.send_command("reset")

    def shutdown(self):
        return self.send_command("shutdown")

    def reload_trajectory(self, trajectory_file):
        return self.send_command("reload_trajectory", {"trajectory_file": trajectory_file})


def run_server():
    config_path = "config/config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    setup_logging(log_level="INFO")

    server = ScalpDetectionServer(config_path)

    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止服务...")
    finally:
        server.stop()


def run_client():
    import argparse

    parser = argparse.ArgumentParser(description="头皮检测系统客户端")
    parser.add_argument("--host", default="127.0.0.1", help="服务端地址")
    parser.add_argument("--port", type=int, default=9999, help="服务端端口")
    parser.add_argument("--command", default="get_status",
                        choices=["start_detection", "get_status", "reset", "shutdown", "reload_trajectory"],
                        help="要执行的命令")
    parser.add_argument("--trajectory", default=None, help="轨迹文件路径（start_detection/reload_trajectory时使用）")

    args = parser.parse_args()

    client = ScalpDetectionClient(args.host, args.port)

    if args.command == "start_detection":
        result = client.start_detection(args.trajectory)
    elif args.command == "reload_trajectory":
        result = client.reload_trajectory(args.trajectory)
    else:
        result = client.send_command(args.command)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "server"

    if mode == "client":
        run_client()
    else:
        run_server()
