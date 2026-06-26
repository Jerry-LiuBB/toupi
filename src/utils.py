#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import tempfile
from datetime import datetime

logger = logging.getLogger(__name__)


def setup_logging(log_level="INFO", log_file=None):
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    handlers = [logging.StreamHandler()]
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format=log_format,
        datefmt=date_format,
        handlers=handlers
    )


def ensure_directory(directory):
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    return directory


def get_current_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def get_task_id():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def format_pose(pose):
    if pose is None:
        return "N/A"
    return "(" + ",".join([f"{p:.3f}" for p in pose]) + ")"


def load_config(config_path):
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    logger.info(f"配置文件加载成功: {config_path}")
    return config


def atomic_write_json(filepath, data):
    dir_path = os.path.dirname(filepath)
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=".trigger_",
        dir=dir_path
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, filepath)
        logger.info(f"原子写入JSON文件: {filepath}")
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
