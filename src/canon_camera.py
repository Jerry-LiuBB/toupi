#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import time
import json
import logging
import shutil

logger = logging.getLogger(__name__)


class CanonCameraController:
    def __init__(self, exe_path, config_path, timeout=15):
        self.exe_path = os.path.abspath(exe_path)
        self.config_path = os.path.abspath(config_path)
        self.timeout = timeout
        self.initialized = False
        self.last_photo_path = None

    def initialize(self):
        if not os.path.exists(self.exe_path):
            logger.error(f"佳能相机控制程序不存在: {self.exe_path}")
            return False
        self.initialized = True
        logger.info("佳能相机初始化成功")
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

    def capture(self, save_path):
        if not self.initialized:
            raise RuntimeError("佳能相机未初始化")

        save_path = os.path.abspath(save_path)
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

        self._update_config(save_path)

        max_retries = 3
        for retry in range(max_retries):
            existing_files = set(os.listdir(save_path)) if os.path.exists(save_path) else set()

            try:
                cmd = f'"{self.exe_path}" "{save_path}" 1 2000 -nopause'
                logger.info(f"调用佳能相机拍照 (尝试 {retry + 1}/{max_retries}): {cmd}")

                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=self.timeout,
                    cwd=os.path.dirname(self.exe_path),
                    shell=True,
                    text=True,
                    encoding='utf-8'
                )

                logger.info(f"佳能相机程序退出码: {result.returncode}")
                if result.stdout:
                    logger.info(f"相机程序输出:\n{result.stdout}")

                new_files = set(os.listdir(save_path)) - existing_files
                image_files = [f for f in new_files if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))]

                if image_files:
                    self.last_photo_path = os.path.join(save_path, sorted(image_files)[-1])
                    logger.info(f"佳能相机拍照成功: {self.last_photo_path}")
                    return self.last_photo_path
                else:
                    all_files = set(os.listdir(save_path))
                    image_files = [f for f in all_files if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))]
                    if image_files:
                        latest = sorted(image_files)[-1]
                        self.last_photo_path = os.path.join(save_path, latest)
                        logger.info(f"佳能相机拍照成功(已有文件): {self.last_photo_path}")
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

    def reset(self):
        self.initialized = False
        self.last_photo_path = None
        logger.info("佳能相机已重置")
        return self.initialize()
