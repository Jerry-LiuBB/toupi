#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from xml.dom import minidom
from datetime import datetime

logger = logging.getLogger(__name__)


class DetectionInfoWriter:
    def __init__(self, output_path, task_id):
        self.output_path = output_path
        self.task_id = task_id
        self.views = []
        self.start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def add_view(self, view_id, scan_angle, canon_image_name, rs_image_name,
                 joint_pose=None, timestamp=None):
        view_data = {
            "id": view_id,
            "ScanAngle": scan_angle,
            "canonimagename": canon_image_name,
            "rsimagename": rs_image_name,
            "joint_pose": joint_pose,
            "timestamp": timestamp
        }
        self.views.append(view_data)
        logger.debug(f"添加视图: id={view_id}, angle={scan_angle}, "
                     f"canon={canon_image_name}, rs={rs_image_name}")

    def write_xml(self, filename="scanangles.xml"):
        filepath = os.path.join(self.output_path, filename)

        doc = minidom.Document()

        root = doc.createElement('opencv_storage')
        doc.appendChild(root)

        views_element = doc.createElement('views')
        root.appendChild(views_element)

        for view in self.views:
            view_element = doc.createElement('_')

            id_elem = doc.createElement('id')
            id_elem.appendChild(doc.createTextNode(str(view["id"])))
            view_element.appendChild(id_elem)

            angle_elem = doc.createElement('ScanAngle')
            angle_text = f"{view['ScanAngle']:.16e}"
            angle_elem.appendChild(doc.createTextNode(angle_text))
            view_element.appendChild(angle_elem)

            canon_elem = doc.createElement('canonimagename')
            canon_elem.appendChild(doc.createTextNode(view["canonimagename"]))
            view_element.appendChild(canon_elem)

            rs_elem = doc.createElement('rsimagename')
            rs_elem.appendChild(doc.createTextNode(view["rsimagename"]))
            view_element.appendChild(rs_elem)

            if view.get("joint_pose") is not None:
                pose_elem = doc.createElement('joint_pose')
                pose_str = ",".join([f"{p:.4f}" for p in view["joint_pose"]])
                pose_elem.appendChild(doc.createTextNode(pose_str))
                view_element.appendChild(pose_elem)

            if view.get("timestamp") is not None:
                ts_elem = doc.createElement('timestamp')
                ts_elem.appendChild(doc.createTextNode(view["timestamp"]))
                view_element.appendChild(ts_elem)

            views_element.appendChild(view_element)

        xml_str = doc.toprettyxml(indent='  ', encoding=None)

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(xml_str)

        logger.info(f"检测信息XML文件已生成: {filepath}")
        return filepath

    def write_summary(self, filename="detection_summary.txt"):
        filepath = os.path.join(self.output_path, filename)

        end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"任务ID: {self.task_id}\n")
            f.write(f"开始时间: {self.start_time}\n")
            f.write(f"结束时间: {end_time}\n")
            f.write(f"总轨迹点数量: {len(self.views)}\n")
            f.write(f"{'='*60}\n")
            f.write(f"{'索引':<6}{'相对角度':<15}{'位姿':<45}{'时间戳':<28}{'佳能图像':<20}{'深度图像':<25}\n")
            f.write(f"{'='*60}\n")

            for view in self.views:
                pose_str = ",".join([f"{p:.3f}" for p in view["joint_pose"]]) if view.get("joint_pose") else "N/A"
                f.write(f"{view['id']:<6}{view['ScanAngle']:<15.4f}{pose_str:<45}"
                        f"{view.get('timestamp', 'N/A'):<28}"
                        f"{view['canonimagename']:<20}{view['rsimagename']:<25}\n")

        logger.info(f"检测摘要文件已生成: {filepath}")
        return filepath
