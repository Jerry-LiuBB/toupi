#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import time
import json
import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def test_canon_camera(exe_path, save_path, num_photos=1, delay_ms=2000):
    """单独测试佳能相机拍照"""
    
    exe_path = os.path.abspath(exe_path)
    save_path = os.path.abspath(save_path)
    
    logger.info(f"佳能相机测试")
    logger.info(f"程序路径: {exe_path}")
    logger.info(f"保存路径: {save_path}")
    logger.info(f"照片数量: {num_photos}")
    logger.info(f"间隔时间: {delay_ms}ms")
    
    if not os.path.exists(exe_path):
        logger.error(f"错误: 佳能相机程序不存在: {exe_path}")
        return False
    
    if not os.path.exists(save_path):
        logger.info(f"创建保存目录: {save_path}")
        os.makedirs(save_path, exist_ok=True)
    
    existing_files = set(os.listdir(save_path)) if os.path.exists(save_path) else set()
    logger.info(f"保存目录现有文件数量: {len(existing_files)}")
    
    cmd = [exe_path, save_path, str(num_photos), str(delay_ms), "-nopause"]
    logger.info(f"\n执行命令: {' '.join(cmd)}")
    logger.info("=" * 60)
    
    try:
        start_time = time.time()
        
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            cwd=os.path.dirname(exe_path),
            encoding='gbk',
            errors='replace'
        )
        
        elapsed = time.time() - start_time
        logger.info(f"\n命令执行完成，耗时: {elapsed:.2f}秒")
        logger.info(f"退出码: {result.returncode}")
        
        if result.stdout:
            logger.info(f"\n标准输出:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"\n错误输出:\n{result.stderr}")
        
        new_files = set(os.listdir(save_path)) - existing_files
        image_files = [f for f in new_files if f.upper().endswith(('.JPG', '.JPEG', '.PNG', '.CR2', '.CR3'))]
        
        if image_files:
            logger.info(f"\n✅ 拍照成功！")
            logger.info(f"新增图片文件:")
            for img in sorted(image_files):
                img_path = os.path.join(save_path, img)
                size = os.path.getsize(img_path) / 1024 / 1024
                logger.info(f"  - {img} ({size:.2f} MB)")
            return True
        else:
            logger.error(f"\n❌ 拍照失败：未生成新的图片文件")
            all_files = set(os.listdir(save_path))
            logger.info(f"保存目录所有文件: {all_files}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error(f"\n❌ 拍照超时 (120秒)")
        return False
    except Exception as e:
        logger.error(f"\n❌ 拍照异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == "__main__":
    config_path = "config/config.json"
    
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        canon_cfg = config.get("canon_camera", {})
        exe_path = canon_cfg.get("exe_path", "CanonCameraControl/bin/Release/net8.0/CanonCameraControl.exe")
    else:
        exe_path = "CanonCameraControl/bin/Release/net8.0/CanonCameraControl.exe"
    
    test_save_path = os.path.join("data", "test_canon", time.strftime("%Y%m%d_%H%M%S"))
    
    logger.info("=" * 60)
    logger.info("佳能相机独立测试")
    logger.info("=" * 60)
    
    success = test_canon_camera(exe_path, test_save_path)
    
    logger.info("=" * 60)
    if success:
        logger.info("测试结果: ✅ 成功")
    else:
        logger.info("测试结果: ❌ 失败")
    logger.info("=" * 60)
    
    sys.exit(0 if success else 1)