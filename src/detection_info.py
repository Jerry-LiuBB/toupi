#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import xml.etree.ElementTree as ET
import logging

logger = logging.getLogger(__name__)


class DetectionInfoWriter:
    def __init__(self, output_dir, task_id):
        self.output_dir = output_dir
        self.task_id = task_id
        self.views = []
        self._batch_size = 100

    def add_view(self, view_id, scan_angle, canon_image_name, rs_image_name):
        view_data = {
            "id": view_id,
            "ScanAngle": scan_angle,
            "canonimagename": canon_image_name or "",
            "rsimagename": rs_image_name or ""
        }
        self.views.append(view_data)
        logger.debug(f"添加视图 {view_id}: angle={scan_angle}, canon={canon_image_name}, rs={rs_image_name}")

    def add_views_batch(self, views_data):
        for view_data in views_data:
            safe = dict(view_data)
            safe["canonimagename"] = safe.get("canonimagename") or ""
            safe["rsimagename"] = safe.get("rsimagename") or ""
            self.views.append(safe)
        logger.debug(f"批量添加 {len(views_data)} 个视图")

    def write_xml(self, xml_filename="scanangles.xml"):
        xml_path = os.path.join(self.output_dir, xml_filename)

        root = ET.Element("opencv_storage")
        views_el = ET.SubElement(root, "views")

        for view in self.views:
            view_el = ET.SubElement(views_el, "_")
            id_el = ET.SubElement(view_el, "id")
            id_el.text = str(view["id"])
            angle_el = ET.SubElement(view_el, "ScanAngle")
            angle_el.text = f"{view['ScanAngle']:.16e}"
            canon_el = ET.SubElement(view_el, "canonimagename")
            canon_el.text = str(view["canonimagename"])
            rs_el = ET.SubElement(view_el, "rsimagename")
            rs_el.text = str(view["rsimagename"])

        ET.indent(root, space="    ")
        body = ET.tostring(root, encoding="unicode")

        with open(xml_path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n')
            f.write(body)
            if not body.endswith("\n"):
                f.write("\n")

        logger.info(f"XML文件已保存: {xml_path}")
        return xml_path

    def write_summary(self):
        summary_path = os.path.join(self.output_dir, "detection_summary.txt")

        lines = []
        lines.append(f"任务ID: {self.task_id}")
        lines.append(f"总视图数: {len(self.views)}")
        lines.append("=" * 50)

        for view in self.views:
            lines.append(f"视图 {view['id']}:")
            lines.append(f"  扫描角度: {view['ScanAngle']:.4f}°")
            lines.append(f"  佳能图像: {view['canonimagename']}")
            lines.append(f"  深度图像: {view['rsimagename']}")
            lines.append("-" * 50)

        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"摘要文件已保存: {summary_path}")
        return summary_path