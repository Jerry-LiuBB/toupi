#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import threading
import concurrent.futures
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

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logger.warning("PIL未安装，将使用opencv保存图像")


class RealSenseController:
    def __init__(self, width=848, height=480, fps=15, align_depth_to_color=True,
                 colorizer_scheme=9, min_distance=0.2, max_distance=1.73,
                 preset_profile="HighDensity", init_max_frames=30, init_min_valid_frames=3,
                 init_max_retries=2, init_retry_delay=0.5, hardware_reset_delay=1,
                 use_frame_buffer=True):
        self.width = width
        self.height = height
        self.fps = fps
        self.align_depth_to_color = align_depth_to_color
        self.colorizer_scheme = colorizer_scheme
        self.min_distance = min_distance
        self.max_distance = max_distance
        self.preset_profile = preset_profile
        self.init_max_frames = init_max_frames
        self.init_min_valid_frames = init_min_valid_frames
        self.init_max_retries = init_max_retries
        self.init_retry_delay = init_retry_delay
        self.hardware_reset_delay = hardware_reset_delay
        self.use_frame_buffer = use_frame_buffer

        self.pipeline = None
        self.align = None
        self.colorizer = None
        self.initialized = False
        self.depth_scale = None

        self._latest_frame = None
        self._frame_lock = threading.Lock()
        self._buffer_thread = None
        self._buffer_running = False

        self._save_executor = None
        self._save_threads = 2
        self._pending_futures = []

        # Web预览专用: 处理结果缓存(时间戳, 彩色, 伪彩), 双流共享避免重复colorize
        self._preview_lock = threading.Lock()
        self._preview_cache = None

    def initialize(self):
        if not REALSENSE_AVAILABLE:
            logger.error("pyrealsense2未安装，无法初始化RealSense相机")
            return False

        try:
            self.stop()

            ctx = rs.context()
            devices = ctx.query_devices()
            if len(devices) == 0:
                logger.error("未检测到RealSense设备")
                return False

            device = devices[0]
            device_name = device.get_info(rs.camera_info.name)
            serial = device.get_info(rs.camera_info.serial_number)
            logger.info(f"检测到RealSense设备: {device_name}, 序列号: {serial}")

            try:
                device.hardware_reset()
                logger.info("已执行设备硬件重置")
                time.sleep(self.hardware_reset_delay)
            except Exception as e:
                logger.warning(f"硬件重置失败，尝试继续: {e}")

            self.pipeline = rs.pipeline(ctx)
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

            try:
                # RS400 visual_preset 官方枚举 (rs_option.h):
                # 0=Custom 1=Default 2=Hand 3=HighAccuracy 4=HighDensity 5=MediumDensity
                preset_map = {
                    "Custom": 0,
                    "Default": 1,
                    "Hand": 2,
                    "HighAccuracy": 3,
                    "HighDensity": 4,
                    "MediumDensity": 5
                }
                preset_value = preset_map.get(self.preset_profile, 0)
                depth_sensor.set_option(rs.option.visual_preset, preset_value)
                applied = depth_sensor.get_option(rs.option.visual_preset)
                logger.info(f"设置深度预设: {self.preset_profile} (value={preset_value}, 相机回读={applied})")
            except Exception as e:
                logger.warning(f"设置深度预设失败: {e}")

            self.colorizer = rs.colorizer()
            self.colorizer.set_option(rs.option.color_scheme, self.colorizer_scheme)
            try:
                self.colorizer.set_option(rs.option.min_distance, self.min_distance)
                self.colorizer.set_option(rs.option.max_distance, self.max_distance)
                logger.info(f"设置色距编码范围: {self.min_distance}m - {self.max_distance}m")
            except Exception as e:
                logger.warning(f"设置色距编码范围失败: {e}")
            logger.info(f"设置色距编码方案: {self.colorizer_scheme}")

            if self.align_depth_to_color:
                self.align = rs.align(rs.stream.color)

            if self.use_frame_buffer:
                self._start_frame_buffer()
                logger.info("帧缓冲线程已启动")

            self._save_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self._save_threads,
                thread_name_prefix="RS_Save"
            )
            logger.info(f"图像保存线程池已启动: {self._save_threads} 个线程")

            logger.info("等待相机帧数据...")

            frame_count = 0
            max_frames = self.init_max_frames
            retry_count = 0
            max_retries = self.init_max_retries

            while retry_count < max_retries:
                for i in range(max_frames):
                    try:
                        frames = self.pipeline.wait_for_frames(timeout_ms=1000)
                        if frames:
                            color_frame = frames.get_color_frame()
                            depth_frame = frames.get_depth_frame()
                            if color_frame and depth_frame:
                                frame_count += 1
                                if frame_count >= self.init_min_valid_frames:
                                    logger.info(f"获取到 {frame_count} 帧有效数据")
                                    self.initialized = True
                                    logger.info(f"RealSense D430/D435初始化成功 ({self.width}x{self.height}, preset={self.preset_profile})")
                                    return True
                            else:
                                logger.debug(f"第 {i+1}/{max_frames} 次尝试: 缺少帧数据")
                        else:
                            logger.debug(f"第 {i+1}/{max_frames} 次尝试: 未获取到帧")
                    except Exception as e:
                        logger.debug(f"第 {i+1}/{max_frames} 次尝试失败: {e}")

                retry_count += 1
                logger.warning(f"第 {retry_count}/{max_retries} 次重试初始化RealSense...")
                self.pipeline.stop()
                time.sleep(self.init_retry_delay)
                self.pipeline.start(config)
                frame_count = 0

            raise RuntimeError(f"无法获取RealSense帧数据，已尝试 {max_retries} 轮，每轮 {max_frames} 次")

        except Exception as e:
            logger.error(f"RealSense初始化失败: {e}")
            self.stop()
            return False

    def capture(self, save_path, index, timestamp, async_save=False):
        if not self.initialized:
            raise RuntimeError("RealSense相机未初始化")

        save_path = os.path.abspath(save_path)
        if not os.path.exists(save_path):
            os.makedirs(save_path, exist_ok=True)

        try:
            if self.use_frame_buffer and self._latest_frame is not None:
                with self._frame_lock:
                    frames = self._latest_frame.as_frameset()
                logger.debug("使用帧缓冲中的最新帧")
            else:
                frames = self.pipeline.wait_for_frames(timeout_ms=500)

            if self.align:
                frames = self.align.process(frames)

            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()

            if not color_frame or not depth_frame:
                raise RuntimeError("获取帧数据失败")

            depth_image = np.asanyarray(depth_frame.get_data())

            colored_depth_frame = self.colorizer.colorize(depth_frame)
            colored_depth_image = np.asanyarray(colored_depth_frame.get_data())

            depth_tiff_name = f"DEPTH_{index:06d}.zip.tiff"
            depth_tiff_path = os.path.join(save_path, depth_tiff_name)

            # 预置None: 若线程池已被并发关闭(如点击停止检测), 会走同步保存分支,
            # 此时return处不能引用未赋值的future (UnboundLocalError)
            future = None
            if async_save and self._save_executor:
                future = self._save_executor.submit(
                    self._save_image_async,
                    colored_depth_image,
                    depth_tiff_path
                )
                self._pending_futures.append(future)
                logger.debug(f"RealSense深度图异步保存已提交: {depth_tiff_path}")
            else:
                self._save_image_sync(colored_depth_image, depth_tiff_path)
                logger.info(f"RealSense深度图保存: {depth_tiff_path}")

            return {
                "depth_tiff_path": depth_tiff_name,
                "depth_data": depth_image,
                "async_future": future
            }

        except Exception as e:
            logger.error(f"RealSense拍照失败: {e}")
            raise

    def get_preview_frames(self, max_age=0.08):
        """获取最新预览帧(彩色BGR + 深度伪彩BGR), 供Web UI实时画面使用。

        低延迟设计:
        - 不做align深度对齐(那是为拍照质量准备的重量级CPU运算, 单帧可达
          数十毫秒, 是预览延迟的主因)。预览深度伪彩与彩色画面存在轻微
          视场偏移, 不影响预览判断; capture()拍照路径仍走align不受影响
        - 双流共享缓存: 彩色/深度两个MJPEG生成器在max_age窗口内
          复用同一次处理结果, 避免重复colorize
        - 线程安全: _preview_lock序列化处理, _frame_lock内仅取帧引用
        未初始化或暂无帧时返回None, 由调用方决定占位显示。
        """
        if not self.initialized or self._latest_frame is None:
            return None
        now = time.monotonic()
        with self._preview_lock:
            cache = self._preview_cache
            if cache is not None and now - cache[0] <= max_age:
                return cache[1], cache[2]
            try:
                with self._frame_lock:
                    frames = self._latest_frame.as_frameset()
                color_frame = frames.get_color_frame()
                depth_frame = frames.get_depth_frame()
                if not color_frame or not depth_frame:
                    return None
                color_image = np.asanyarray(color_frame.get_data())
                colored_depth_frame = self.colorizer.colorize(depth_frame)
                depth_image = np.asanyarray(colored_depth_frame.get_data())
                # colorizer输出为RGB8, JPEG编码期望BGR, 必须转换否则红蓝颠倒
                if CV2_AVAILABLE:
                    depth_image = cv2.cvtColor(depth_image, cv2.COLOR_RGB2BGR)
                self._preview_cache = (now, color_image, depth_image)
                return color_image, depth_image
            except Exception as e:
                logger.debug(f"获取预览帧失败: {e}")
                return None

    def _save_image_sync(self, image_data, file_path):
        if PIL_AVAILABLE:
            depth_pil = Image.fromarray(image_data)
            depth_pil.save(file_path, format='TIFF')
        elif CV2_AVAILABLE:
            success, depth_encoded = cv2.imencode('.tiff', image_data)
            if not success:
                raise RuntimeError("无法编码深度图")
            with open(file_path, 'wb') as f:
                f.write(depth_encoded.tobytes())
        else:
            np.save(file_path.replace('.zip.tiff', '.npy'), image_data)

    def _save_image_async(self, image_data, file_path):
        try:
            self._save_image_sync(image_data, file_path)
            logger.debug(f"RealSense深度图异步保存完成: {file_path}")
        except Exception as e:
            logger.error(f"RealSense深度图异步保存失败: {e}")

    def wait_for_all_saves(self, timeout=30):
        # 等待所有已提交的保存任务完成, 但不关闭线程池
        # (线程池在下次扫描中继续复用; 若在此处shutdown,
        #  第二次扫描capture提交任务会抛
        #  "cannot schedule new futures after shutdown")
        futures = self._pending_futures
        self._pending_futures = []
        for f in futures:
            try:
                f.result(timeout=timeout)
            except Exception as e:
                logger.warning(f"等待深度图异步保存任务失败: {e}")

    def _start_frame_buffer(self):
        self._buffer_running = True
        self._buffer_thread = threading.Thread(target=self._frame_buffer_loop, daemon=True)
        self._buffer_thread.start()

    def _frame_buffer_loop(self):
        while self._buffer_running and self.pipeline:
            try:
                frames = self.pipeline.wait_for_frames(timeout_ms=100)
                if frames:
                    with self._frame_lock:
                        self._latest_frame = rs.composite_frame(frames)
            except Exception as e:
                logger.debug(f"帧缓冲读取异常: {e}")
                time.sleep(0.01)

    def stop(self):
        self._buffer_running = False
        self._preview_cache = None
        if self._buffer_thread:
            try:
                self._buffer_thread.join(timeout=1)
            except Exception:
                pass
            self._buffer_thread = None
        
        self._pending_futures = []
        if self._save_executor:
            try:
                self._save_executor.shutdown(wait=True, cancel_futures=False)
            except Exception:
                pass
            self._save_executor = None
        
        if self.pipeline:
            try:
                self.pipeline.stop()
            except Exception as e:
                logger.warning(f"RealSense停止时出错: {e}")
            self.pipeline = None
        self.initialized = False
        self.align = None
        self.colorizer = None
        self._latest_frame = None
        logger.info("RealSense相机已停止")

    def reset(self):
        self.stop()
        time.sleep(1)
        return self.initialize()