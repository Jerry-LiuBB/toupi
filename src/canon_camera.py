#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import time
import json
import logging
import shutil
import socket
import threading
import queue

logger = logging.getLogger(__name__)


class CanonCameraController:
    def __init__(self, exe_path, config_path, timeout=15, server_port=8765):
        self.exe_path = os.path.abspath(exe_path)
        self.config_path = os.path.abspath(config_path)
        self.timeout = timeout
        self.server_port = server_port
        self.initialized = False
        self.last_photo_path = None
        self.server_process = None
        self.use_server_mode = False
        self._save_path = None
        self._photo_index = 0
        self._image_queue = queue.Queue()
        self._save_thread = None
        self._save_running = False

    def _send_command(self, command):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                sock.connect(('127.0.0.1', self.server_port))
                sock.sendall(command.encode('utf-8'))
                response = sock.recv(4096).decode('utf-8').strip()
                return json.loads(response)
        except socket.error as e:
            logger.error(f"TCP连接失败: {e}")
            return {"success": False, "error": str(e)}

    def _check_server_status(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2)
                sock.connect(('127.0.0.1', self.server_port))
                return True
        except socket.error:
            return False

    def _check_camera_ready(self):
        if not self._check_server_status():
            return False
        response = self._send_command("status")
        return response.get("success", False) and response.get("connected", False)

    def _start_server(self):
        if self._check_server_status():
            logger.info("佳能相机服务已在运行")
            return True

        if not os.path.exists(self.exe_path):
            logger.error(f"佳能相机控制程序不存在: {self.exe_path}")
            return False

        try:
            cmd = [self.exe_path, "-server", str(self.server_port)]
            logger.info(f"启动佳能相机服务: {' '.join(cmd)}")

            log_file = os.path.join(os.path.dirname(self.exe_path), "canon_server.log")
            
            self.server_process = subprocess.Popen(
                cmd,
                stdout=open(log_file, 'w', encoding='gbk'),
                stderr=subprocess.STDOUT,
                cwd=os.path.dirname(self.exe_path),
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )

            for attempt in range(10):
                time.sleep(1)
                if self._check_server_status():
                    if self._check_camera_ready():
                        logger.info("佳能相机服务启动成功，相机已就绪")
                        return True
                    else:
                        logger.warning(f"服务已启动但相机未就绪，重试中 ({attempt + 1}/10)...")
                        continue

            logger.error("佳能相机服务启动超时（相机未就绪）")
            self.server_process = None
            return False

        except Exception as e:
            logger.error(f"启动佳能相机服务失败: {e}")
            return False

    def _start_save_thread(self):
        if self._save_running:
            return
        
        self._save_running = True
        self._save_thread = threading.Thread(target=self._save_worker, daemon=True)
        self._save_thread.start()
        logger.info("图像重命名线程已启动")

    def _save_worker(self):
        while self._save_running:
            try:
                item = self._image_queue.get(timeout=1)
                original_path, new_path = item
                
                try:
                    if os.path.exists(new_path):
                        os.remove(new_path)
                    shutil.move(original_path, new_path)
                    self.last_photo_path = new_path
                    logger.debug(f"图像重命名完成: {new_path}")
                except Exception as e:
                    logger.error(f"图像重命名失败: {e}")
                    
                self._image_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"保存线程异常: {e}")

    def initialize(self):
        if not os.path.exists(self.exe_path):
            logger.error(f"佳能相机控制程序不存在: {self.exe_path}")
            return False

        if self._start_server():
            self.use_server_mode = True
            self.initialized = True
            self._start_save_thread()
            logger.info("佳能相机服务模式初始化成功")
            return True

        logger.info("回退到单机模式")
        self.use_server_mode = False
        self.initialized = True
        logger.info("佳能相机单机模式初始化成功")
        return True

    def _update_config(self, save_path):
        config = {
            "downloadPath": save_path.replace("/", "\\"),
            "numberOfPhotos": 1,
            "delayBetweenPhotosMs": 2000
        }
        config_dir = os.path.dirname(self.config_path)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        logger.debug(f"更新佳能相机配置: {config}")

    def capture(self, save_path, photo_index=0):
        save_path = os.path.abspath(save_path)
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

        self._save_path = save_path
        self._photo_index = photo_index

        if self.use_server_mode:
            return self._capture_server_mode(save_path, photo_index)
        else:
            return self._capture_single_mode(save_path, photo_index)

    def capture_async(self, save_path, photo_index=0):
        if not self.use_server_mode:
            logger.warning("异步拍照仅支持服务模式")
            return self.capture(save_path, photo_index)

        save_path = os.path.abspath(save_path)
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

        self._save_path = save_path
        self._photo_index = photo_index

        response = self._send_command(f"set_path {save_path}")
        if not response.get("success"):
            logger.error(f"设置保存路径失败: {response.get('error')}")
            return None

        response = self._send_command("capture_async")
        if response.get("success"):
            logger.info(f"佳能相机异步拍照已启动")
            return True
        else:
            logger.error(f"佳能相机异步拍照失败: {response.get('error')}")
            return False

    def wait_for_capture(self, timeout=15):
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self._send_command("capture_status")
            if response.get("success") and not response.get("is_capturing"):
                return self._get_latest_image(self._save_path, self._photo_index)
            time.sleep(0.5)
        raise RuntimeError("等待拍照完成超时")

    def batch_capture(self, save_path, count, delay_ms=1000):
        if not self.use_server_mode:
            logger.warning("批量拍照仅支持服务模式")
            results = []
            for i in range(count):
                if i > 0:
                    time.sleep(delay_ms / 1000)
                result = self.capture(save_path, self._photo_index + i)
                results.append(result)
            return results

        save_path = os.path.abspath(save_path)
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

        response = self._send_command(f"set_path {save_path}")
        if not response.get("success"):
            logger.error(f"设置保存路径失败: {response.get('error')}")
            return []

        response = self._send_command(f"batch_capture {count} {delay_ms}")
        if response.get("success"):
            success_count = response.get("success_count", 0)
            logger.info(f"批量拍照完成: {success_count}/{count}")
            return self._get_recent_images(save_path, count)
        else:
            logger.error(f"批量拍照失败: {response.get('error')}")
            return []

    @staticmethod
    def _snapshot_image_files(save_path):
        if not os.path.exists(save_path):
            return set()
        return set(
            f for f in os.listdir(save_path)
            if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))
        )

    @staticmethod
    def _find_new_images(save_path, snapshot, timeout=20, poll_interval=0.3):
        """轮询收集快照之后新增的图片文件，返回按修改时间升序的 [(mtime, name), ...]"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            current = CanonCameraController._snapshot_image_files(save_path)
            new_files = current - snapshot
            if new_files:
                candidates = []
                for name in new_files:
                    fpath = os.path.join(save_path, name)
                    try:
                        mtime = os.path.getmtime(fpath)
                    except OSError:
                        continue
                    candidates.append((mtime, name))
                if candidates:
                    candidates.sort()
                    return candidates
            time.sleep(poll_interval)
        return []

    def _start_late_cleanup(self, save_path, snapshot, keep_name):
        """后台线程清理拍照后迟到落盘的多余照片(连拍模式)，不阻塞拍照流程"""
        def _sweep():
            deadline = time.time() + 1.5
            while time.time() < deadline:
                try:
                    current = CanonCameraController._snapshot_image_files(save_path)
                except OSError:
                    return
                for name in current - snapshot - {keep_name}:
                    try:
                        os.remove(os.path.join(save_path, name))
                        logger.info(f"清理连拍迟到的多余照片: {name}")
                    except OSError:
                        pass
                time.sleep(0.2)

        t = threading.Thread(target=_sweep, daemon=True)
        t.start()

    def capture_fast(self, save_path, photo_index=0):
        if not self.use_server_mode:
            logger.warning("快速拍照仅支持服务模式")
            return self.capture(save_path, photo_index)

        save_path = os.path.abspath(save_path)
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

        self._save_path = save_path
        self._photo_index = photo_index

        snapshot = self._snapshot_image_files(save_path)

        response = self._send_command(f"set_path {save_path}")
        if not response.get("success"):
            logger.error(f"设置保存路径失败: {response.get('error')}")
            return None

        response = self._send_command("fast_capture")
        if not response.get("success"):
            logger.error(f"快速拍照失败: {response.get('error')}")
            return None

        new_images = self._find_new_images(save_path, snapshot)
        if not new_images:
            logger.error("佳能相机拍照失败: 未在超时时间内检测到新图像文件")
            return None

        # 连拍模式下一次触发可能产生多张照片：第一张(最早)与触发时刻最对应，保留并重命名
        _, first_name = new_images[0]
        extras = [name for _, name in new_images[1:]]

        ext = os.path.splitext(first_name)[1]
        new_filename = f"IMG_{photo_index:03d}{ext}"
        original_path = os.path.join(save_path, first_name)
        new_path = os.path.join(save_path, new_filename)
        try:
            if os.path.exists(new_path):
                os.remove(new_path)
            shutil.move(original_path, new_path)
        except Exception as e:
            logger.error(f"图像重命名失败 ({first_name} -> {new_filename}): {e}")
            return None

        # 删除连拍产生的多余照片
        for name in extras:
            try:
                os.remove(os.path.join(save_path, name))
                logger.info(f"删除连拍产生的多余照片: {name}")
            except OSError as e:
                logger.warning(f"删除多余照片失败 ({name}): {e}")

        if extras:
            logger.warning(
                f"相机处于连拍模式: 本次触发共拍摄 {len(new_images)} 张, "
                f"已保留首张并删除其余 {len(extras)} 张"
            )

        # 后台清理迟到落盘的多余照片，避免残留到目录中
        self._start_late_cleanup(save_path, snapshot, new_filename)

        self.last_photo_path = new_path
        logger.info(f"佳能相机拍照成功(服务模式): {new_path}")
        return self.last_photo_path

    def get_camera_status(self):
        if not self.use_server_mode:
            return {"success": False, "error": "仅支持服务模式"}
        response = self._send_command("get_camera_param all")
        return response

    def _get_recent_images(self, save_path, count):
        all_files = os.listdir(save_path) if os.path.exists(save_path) else []
        image_files = sorted([f for f in all_files if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))])
        recent = image_files[-count:] if len(image_files) >= count else image_files
        
        results = []
        for i, filename in enumerate(recent):
            original_path = os.path.join(save_path, filename)
            ext = os.path.splitext(filename)[1]
            new_filename = f"IMG_{self._photo_index + i:03d}{ext}"
            new_path = os.path.join(save_path, new_filename)
            
            try:
                if os.path.exists(new_path):
                    os.remove(new_path)
                shutil.move(original_path, new_path)
                self.last_photo_path = new_path
                results.append(new_path)
                logger.info(f"图像重命名: {new_path}")
            except Exception as e:
                logger.error(f"图像重命名失败: {e}")
        
        return results

    def _get_latest_image(self, save_path, photo_index):
        all_files = os.listdir(save_path) if os.path.exists(save_path) else []
        image_files = [f for f in all_files if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))]
        
        if image_files:
            latest = sorted(image_files)[-1]
            original_path = os.path.join(save_path, latest)
            ext = os.path.splitext(original_path)[1]
            new_filename = f"IMG_{photo_index:03d}{ext}"
            new_path = os.path.join(save_path, new_filename)
            
            if os.path.exists(new_path):
                os.remove(new_path)
            shutil.move(original_path, new_path)
            self.last_photo_path = new_path
            logger.info(f"佳能相机拍照成功(服务模式): {new_path}")
            return self.last_photo_path

        raise RuntimeError("佳能相机拍照失败: 未找到新图像文件")

    def _capture_server_mode(self, save_path, photo_index=0):
        response = self._send_command(f"set_path {save_path}")
        if not response.get("success"):
            logger.error(f"设置保存路径失败: {response.get('error')}")
            raise RuntimeError(f"设置保存路径失败: {response.get('error')}")

        response = self._send_command("capture")
        if not response.get("success"):
            logger.error(f"佳能相机拍照失败: {response.get('error')}")
            raise RuntimeError(f"佳能相机拍照失败: {response.get('error')}")

        return self._get_latest_image(save_path, photo_index)

    def _capture_single_mode(self, save_path, photo_index=0):
        if not self.initialized:
            raise RuntimeError("佳能相机未初始化")

        self._update_config(save_path)

        max_retries = 3
        for retry in range(max_retries):
            existing_files = set(os.listdir(save_path)) if os.path.exists(save_path) else set()

            try:
                cmd = [self.exe_path, save_path, "1", "2000", "-nopause"]
                logger.info(f"调用佳能相机拍照 (尝试 {retry + 1}/{max_retries}): {' '.join(cmd)}")

                log_file = os.path.join(save_path, f"canon_camera_{retry+1}.log")
                logger.info(f"佳能相机日志文件: {log_file}")

                result = subprocess.run(
                    cmd,
                    stdout=open(log_file, 'w', encoding='gbk'),
                    stderr=subprocess.STDOUT,
                    timeout=self.timeout,
                    cwd=os.path.dirname(self.exe_path)
                )

                if os.path.exists(log_file):
                    with open(log_file, 'r', encoding='gbk', errors='replace') as f:
                        log_content = f.read()
                    if log_content:
                        logger.info(f"佳能相机程序输出:\n{log_content}")

                logger.info(f"佳能相机程序退出码: {result.returncode}")

                new_files = set(os.listdir(save_path)) - existing_files
                image_files = [f for f in new_files if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))]

                if image_files:
                    original_path = os.path.join(save_path, sorted(image_files)[-1])
                    ext = os.path.splitext(original_path)[1]
                    new_filename = f"IMG_{photo_index:03d}{ext}"
                    new_path = os.path.join(save_path, new_filename)
                    shutil.move(original_path, new_path)
                    self.last_photo_path = new_path
                    logger.info(f"佳能相机拍照成功(单机模式): {new_path}")
                    return self.last_photo_path
                else:
                    all_files = set(os.listdir(save_path))
                    image_files = [f for f in all_files if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))]
                    if image_files:
                        latest = sorted(image_files)[-1]
                        original_path = os.path.join(save_path, latest)
                        ext = os.path.splitext(original_path)[1]
                        new_filename = f"IMG_{photo_index:03d}{ext}"
                        new_path = os.path.join(save_path, new_filename)
                        shutil.move(original_path, new_path)
                        self.last_photo_path = new_path
                        logger.info(f"佳能相机拍照成功(已有文件): {new_path}")
                        return self.last_photo_path

                logger.error(f"佳能相机拍照失败: 未找到新图像文件。相机程序退出码: {result.returncode}")

            except subprocess.TimeoutExpired:
                logger.error(f"佳能相机拍照超时 ({self.timeout}秒)")
            except Exception as e:
                logger.error(f"佳能相机拍照失败: {e}")

            if retry < max_retries - 1:
                logger.info(f"等待2秒后重试...")
                time.sleep(2)

        raise RuntimeError(f"佳能相机拍照失败，已重试 {max_retries} 次")

    def reconnect(self):
        if self.use_server_mode:
            response = self._send_command("reconnect")
            if response.get("success"):
                logger.info("佳能相机重新连接成功")
                return True
            else:
                logger.error(f"佳能相机重新连接失败: {response.get('error')}")
                return False
        else:
            return self.reset()

    def reset(self):
        self.initialized = False
        self.last_photo_path = None
        logger.info("佳能相机已重置")
        return self.initialize()

    def stop(self):
        self._save_running = False
        
        if self.use_server_mode and self.server_process:
            try:
                self._send_command("shutdown")
                time.sleep(2)
                self.server_process.terminate()
                self.server_process.wait(timeout=5)
                logger.info("佳能相机服务已停止")
            except Exception as e:
                logger.error(f"停止佳能相机服务失败: {e}")
            self.server_process = None

        self.initialized = False
        self.last_photo_path = None
        self.use_server_mode = False
        logger.info("佳能相机已停止")