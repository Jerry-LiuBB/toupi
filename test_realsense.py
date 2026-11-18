#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
except ImportError:
    logger.error("pyrealsense2未安装，请先安装: pip install pyrealsense2")
    sys.exit(1)

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("opencv未安装")

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL未安装")


def test_realsense_depth(output_dir="test_output"):
    os.makedirs(output_dir, exist_ok=True)
    
    pipeline = None
    try:
        logger.info("=" * 60)
        logger.info("RealSense D435 深度图像测试")
        logger.info("=" * 60)

        logger.info("[1] 创建并配置管线...")
        pipeline = rs.pipeline()
        config = rs.config()

        config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 30)
        config.enable_stream(rs.stream.color, 848, 480, rs.format.bgr8, 30)

        logger.info("[2] 启动相机...")
        profile = pipeline.start(config)

        depth_sensor = profile.get_device().first_depth_sensor()
        logger.info(f"深度传感器: {depth_sensor.get_info(rs.camera_info.name)}")

        depth_scale = depth_sensor.get_depth_scale()
        logger.info(f"深度比例因子: {depth_scale}")

        preset_range = depth_sensor.get_option_range(rs.option.visual_preset)
        for i in range(int(preset_range.max)):
            preset_name = depth_sensor.get_option_value_description(rs.option.visual_preset, i)
            if preset_name == "HighDensity":
                depth_sensor.set_option(rs.option.visual_preset, i)
                logger.info(f"设置深度预设: {preset_name} (value={i})")
                break

        align = rs.align(rs.stream.color)

        logger.info("[3] 等待相机稳定...")
        for _ in range(10):
            pipeline.wait_for_frames()

        logger.info("[4] 获取帧数据...")
        frames = pipeline.wait_for_frames()
        aligned_frames = align.process(frames)

        depth_frame = aligned_frames.get_depth_frame()
        color_frame = aligned_frames.get_color_frame()

        if not depth_frame or not color_frame:
            raise RuntimeError("获取帧数据失败")

        depth_image = np.asanyarray(depth_frame.get_data())
        color_image = np.asanyarray(color_frame.get_data())

        logger.info(f"深度图像尺寸: {depth_image.shape}, 数据类型: {depth_image.dtype}")
        logger.info(f"彩色图像尺寸: {color_image.shape}, 数据类型: {color_image.dtype}")
        logger.info(f"深度图像最小值: {depth_image.min()}, 最大值: {depth_image.max()}")

        valid_depth = depth_image[depth_image > 0]
        if len(valid_depth) > 0:
            logger.info(f"有效深度值数量: {len(valid_depth)}")
            logger.info(f"有效深度平均值: {valid_depth.mean():.2f} (mm)")
            logger.info(f"有效深度中位数: {np.median(valid_depth):.2f} (mm)")

        logger.info("[5] 使用colorizer生成彩色深度图...")
        colorizer = rs.colorizer()
        colorizer.set_option(rs.option.color_scheme, 9)
        colorizer.set_option(rs.option.min_distance, 0.2)
        colorizer.set_option(rs.option.max_distance, 1.73)
        
        colored_depth_frame = colorizer.colorize(depth_frame)
        colored_depth_image = np.asanyarray(colored_depth_frame.get_data())
        logger.info(f"彩色深度图像尺寸: {colored_depth_image.shape}, 数据类型: {colored_depth_image.dtype}")

        logger.info("[6] 保存深度图像...")
        depth_filename = os.path.join(output_dir, "DEPTH_000000.zip.tiff")
        
        if PIL_AVAILABLE:
            logger.info("使用PIL保存深度图像...")
            depth_pil = Image.fromarray(colored_depth_image)
            depth_pil.save(depth_filename, format='TIFF')
        elif CV2_AVAILABLE:
            logger.info("使用OpenCV保存深度图像...")
            success, depth_encoded = cv2.imencode('.tiff', colored_depth_image)
            if not success:
                raise RuntimeError("无法编码深度图")
            with open(depth_filename, 'wb') as f:
                f.write(depth_encoded.tobytes())
        else:
            raise RuntimeError("PIL和OpenCV都未安装，无法保存图像")

        file_size = os.path.getsize(depth_filename)
        logger.info(f"深度图像已保存: {depth_filename}")
        logger.info(f"文件大小: {file_size} 字节")

        logger.info("[7] 验证保存的深度图像...")
        if PIL_AVAILABLE:
            loaded_depth = np.array(Image.open(depth_filename))
            logger.info(f"加载的深度图像尺寸: {loaded_depth.shape}, 数据类型: {loaded_depth.dtype}")
            logger.info(f"加载的深度图像最小值: {loaded_depth.min()}, 最大值: {loaded_depth.max()}")
            
            if np.array_equal(colored_depth_image, loaded_depth):
                logger.info("✓ 深度图像保存和加载验证成功！")
            else:
                diff_count = np.sum(colored_depth_image != loaded_depth)
                logger.warning(f"✗ 深度图像保存和加载有差异: {diff_count} 像素不同")

        logger.info("[8] 保存彩色图像...")
        color_filename = os.path.join(output_dir, "RS_color_000000.png")
        if CV2_AVAILABLE:
            cv2.imwrite(color_filename, color_image)
            logger.info(f"彩色图像已保存: {color_filename}")
        elif PIL_AVAILABLE:
            Image.fromarray(cv2.cvtColor(color_image, cv2.COLOR_BGR2RGB) if CV2_AVAILABLE else color_image).save(color_filename)
            logger.info(f"彩色图像已保存: {color_filename}")

        logger.info("=" * 60)
        logger.info("测试完成！")
        logger.info(f"输出目录: {os.path.abspath(output_dir)}")
        logger.info("=" * 60)

        return True

    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if pipeline:
            try:
                pipeline.stop()
                logger.info("相机已停止")
            except Exception as e:
                logger.warning(f"停止相机时出错: {e}")


if __name__ == "__main__":
    success = test_realsense_depth()
    sys.exit(0 if success else 1)