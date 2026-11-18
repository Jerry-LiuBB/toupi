# 头皮检测系统 (Scalp Testing)

基于机械臂轨迹控制的头皮扫描检测系统，支持自动轨迹执行、双相机同步拍摄、检测信息生成，以及与外部软件的控制权交接。

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    外部控制软件                           │
│  (监听 trigger.json / TCP Socket 客户端)                 │
└──────────┬──────────────────────────┬───────────────────┘
           │ trigger.json             │ TCP Socket
           │ (文件监听)               │ (命令控制)
           ▼                          ▼
┌─────────────────────────────────────────────────────────┐
│              头皮检测系统 (服务模式)                       │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 机械臂控制    │  │ 佳能相机控制  │  │ RealSense    │  │
│  │ RobotController│ │ CanonCamera  │  │ D435 控制    │  │
│  │ (Socket)     │  │ (子进程)      │  │ (pyrealsense2)│  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ 轨迹读取      │  │ 检测信息生成  │  │ TCP 服务端   │  │
│  │ TrajectoryReader│ │ DetectionInfo│  │ Server      │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 项目结构

```
Scalp_testing/
├── config/
│   └── config.json              # 全局配置文件
├── src/
│   ├── scalp_detection.py       # 核心系统逻辑与状态机
│   ├── scalp_detection_server.py # TCP Socket 服务端/客户端
│   ├── robot_controller.py      # 机械臂 Socket 通信控制
│   ├── canon_camera.py          # 佳能相机子进程控制
│   ├── realsense_camera.py      # RealSense D435 深度相机控制
│   ├── trajectory_reader.py     # 轨迹文件读取与解析
│   ├── detection_info.py        # 检测信息 XML/TXT 生成
│   ├── web_ui.py                # Web 控制界面（Flask）
│   └── utils.py                 # 工具函数（日志、原子写入等）
├── trajectories/
│   └── trajectory.txt           # 机械臂轨迹文件
├── CanonCameraControl/          # 佳能相机 C# 控制程序
├── data/                        # 检测输出目录（运行时自动生成）
├── requirements.txt             # Python 依赖
├── setup_env.bat                # 一键环境配置脚本
├── run_server.bat               # 一键启动脚本
└── test_realsense.py            # RealSense 相机测试脚本
```

## 一键环境配置

### 在新电脑上快速配置

1. **双击运行** `setup_env.bat`
   - 自动检查 Python 安装
   - 创建虚拟环境
   - 安装所有依赖
   - 验证依赖安装成功

2. **双击运行** `run_server.bat`
   - 启动服务端
   - 打开浏览器访问：http://127.0.0.1:8080

### 手动安装方式

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

依赖包：
- `numpy` - 数值计算
- `opencv-python` - 图像读写
- `pyrealsense2` - RealSense D435 SDK
- `flask` - Web 控制界面
- `Pillow` - 图像保存（支持中文路径）

## 环境要求

- Python 3.8+
- Windows 操作系统
- 机械臂：睿尔曼（RealMan），通过 TCP Socket 通信（默认 192.168.1.18:8080）
- 佳能相机：通过 CanonCameraControl.exe 子进程控制
- RealSense D435：通过 pyrealsense2 SDK 控制

## 配置说明

所有参数在 `config/config.json` 中配置：

```json
{
    "robot": {
        "ip": "192.168.1.18",
        "port": 8080,
        "timeout": 30,
        "velocity": 50,
        "acceleration": 0,
        "trajectory_connect": 0
    },
    "canon_camera": {
        "exe_path": "CanonCameraControl/bin/Release/net8.0/CanonCameraControl.exe",
        "config_path": "CanonCameraControl/config.json",
        "timeout": 60
    },
    "realsense": {
        "width": 848,
        "height": 480,
        "fps": 30,
        "depth_format": "tiff",
        "align_depth_to_color": true,
        "colorizer_scheme": 9,
        "min_distance": 0.2,
        "max_distance": 1.73,
        "preset_profile": "HighDensity"
    },
    "trajectory": {
        "file_path": "trajectories/trajectory.txt",
        "angle_unit": "degree",
        "angle_scale": 1000
    },
    "output": {
        "base_path": "data",
        "images_subdir": "images",
        "logs_subdir": "logs",
        "xml_filename": "scanangles.xml"
    },
    "system": {
        "log_level": "INFO",
        "retry_count": 3,
        "retry_delay": 1.0
    },
    "server": {
        "host": "0.0.0.0",
        "port": 9999,
        "buffer_size": 4096,
        "timeout": 300
    },
    "web_ui": {
        "host": "0.0.0.0",
        "port": 8080
    }
}
```

### 配置项说明

| 分组 | 参数 | 说明 |
|------|------|------|
| robot | ip / port | 机械臂 Socket 地址 |
| robot | velocity | 运动速度（0-100） |
| robot | angle_scale | 角度转整数倍率（默认 1000，即 10.1° → 10100） |
| canon_camera | exe_path | 佳能相机控制程序路径 |
| realsense | width / height / fps | D435 分辨率与帧率（推荐 848×480） |
| realsense | colorizer_scheme | 深度图颜色方案（默认 9） |
| realsense | min_distance / max_distance | 深度测量范围（默认 0.2m - 1.73m） |
| realsense | preset_profile | 深度预设（默认 HighDensity） |
| trajectory | file_path | 默认轨迹文件路径 |
| output | base_path | 输出根目录（可自定义） |
| server | host / port | TCP 服务监听地址 |
| web_ui | host / port | Web 控制界面地址 |

## 轨迹文件格式

轨迹文件为纯文本格式，每行一个轨迹点，6 个关节角度（度）逗号分隔：

```
# 注释行以 # 开头
# 格式: j1,j2,j3,j4,j5,j6
10.1,0.2,20.3,30.4,0.5,20.6
15.2,5.1,25.4,35.6,2.3,25.8
20.3,10.0,30.5,40.8,4.1,30.9
```

第一个轨迹点作为起始点（复位目标位）。

## 运行模式

### 模式一：一键启动（推荐）

双击运行 `run_server.bat`，启动服务模式和 Web 控制界面。

### 模式二：单次运行模式

执行一次完整检测后退出：

```bash
python src/scalp_detection.py
```

流程：初始化 → 执行轨迹 → 拍照 → 生成文件 → 退出

### 模式三：服务模式

启动 TCP 服务端，常驻运行，等待外部命令触发：

```bash
python src/scalp_detection_server.py
```

服务启动后监听 `0.0.0.0:9999`，等待客户端连接发送命令。

### 模式四：Web 控制界面

服务模式启动时自动启动 Web 控制界面，通过浏览器访问：

启动后在浏览器中打开：`http://localhost:8080`

**界面功能：**

| 功能 | 说明 |
|------|------|
| 系统状态面板 | 实时显示当前状态、当前点位/总点位、输出路径 |
| 开始检测 | 触发一次完整检测流程 |
| 停止检测 | 停止当前正在执行的检测 |
| 复位系统 | 将机械臂复位到起始点，重新初始化相机 |
| 关闭系统 | 安全关闭服务 |
| 实时日志 | 显示系统运行日志，支持自动滚动 |

**Web UI API：**

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 控制界面首页 |
| `/api/status` | GET | 获取系统状态 |
| `/api/start_detection` | POST | 启动检测 |
| `/api/stop` | POST | 停止检测 |
| `/api/reset` | POST | 复位系统 |
| `/api/shutdown` | POST | 关闭系统 |
| `/api/logs` | GET | SSE 实时日志流 |

## 检测流程

```
开始信号触发
    │
    ▼
读取轨迹文件
    │
    ▼
移动机械臂到起始点
    │
    ▼
┌─────────────────────────────┐
│  循环执行每个轨迹点:          │
│                             │
│  1. 移动机械臂到轨迹点        │
│  2. 佳能相机拍摄 RGB 图像     │
│  3. D435 拍摄彩色深度图像     │
│  4. 记录角度/位姿/时间戳      │
│                             │
└─────────────────────────────┘
    │
    ▼
生成 scanangles.xml
生成 detection_summary.txt
原子写入 trigger.json
    │
    ▼
回到 IDLE 状态，等待下次触发
```

## 输出文件结构

每次检测生成一个以任务 ID 命名的会话目录：

```
data/
└── 20260701_213000/           # 会话目录（任务ID = 时间戳）
    ├── images/                # 图像目录
    │   ├── IMG_000.JPG        # 佳能相机 RGB 图像
    │   ├── DEPTH_000000.zip.tiff # D435 彩色深度图像
    │   ├── IMG_001.JPG
    │   ├── DEPTH_000001.zip.tiff
    │   └── ...
    ├── logs/
    │   └── 20260701_213000.log # 运行日志
    ├── scanangles.xml          # 检测信息（角度、图像映射）
    ├── detection_summary.txt   # 检测摘要
    └── trigger.json            # 完成触发文件（原子写入）
```

### 图像文件命名格式

| 相机 | 文件名格式 | 示例 |
|------|-----------|------|
| 佳能 | `IMG_{序号}.JPG` | `IMG_000.JPG` |
| RealSense 深度图 | `DEPTH_{序号}.zip.tiff` | `DEPTH_000000.zip.tiff` |

### scanangles.xml 格式

兼容 OpenCV storage 格式，与土耳其头皮扫描项目一致：

```xml
<?xml version="1.0"?>
<opencv_storage>
<views>
  <_>
    <id>0</id>
    <ScanAngle>0.0000000000000000e+00</ScanAngle>
    <canonimagename>IMG_000.JPG</canonimagename>
    <rsimagename>DEPTH_000000.zip.tiff</rsimagename>
    <joint_pose>10.1000,0.2000,20.3000,30.4000,0.5000,20.6000</joint_pose>
    <timestamp>20260701_213000_123456</timestamp>
  </_>
  <_>
    <id>1</id>
    <ScanAngle>5.1000000000000000e+00</ScanAngle>
    <canonimagename>IMG_001.JPG</canonimagename>
    <rsimagename>DEPTH_000001.zip.tiff</rsimagename>
    <joint_pose>15.2000,5.1000,25.4000,35.6000,2.3000,25.8000</joint_pose>
    <timestamp>20260701_213001_234567</timestamp>
  </_>
</views>
</opencv_storage>
```

## 控制权交接机制

### 方式一：trigger.json 文件监听（推荐）

检测完成、所有文件落盘后，系统在会话目录下**原子生成** `trigger.json`。外部软件监听该文件创建事件即可。

**扫描成功时 trigger.json 内容：**

```json
{
  "event": "scan_completed",
  "task_id": "20260701_213000",
  "out_dir": "D:\\data\\20260701_213000",
  "poses_file": "D:\\data\\20260701_213000\\scanangles.xml",
  "total_points": 5
}
```

**扫描失败时 trigger.json 内容：**

```json
{
  "event": "scan_failed",
  "task_id": "20260701_213000",
  "out_dir": "D:\\data\\20260701_213000",
  "error": "机械臂移动失败: 轨迹点 3",
  "current_point": 3,
  "total_points": 5
}
```

### 方式二：TCP Socket 命令控制

通过 TCP Socket 发送 JSON 命令控制系统，实时获取响应。

**支持的命令：**

| 命令 | 说明 | 参数 |
|------|------|------|
| `start_detection` | 触发一次检测 | `trajectory_file`（可选）：指定轨迹文件 |
| `get_status` | 查询系统状态 | 无 |
| `reset` | 复位系统（错误后恢复） | 无 |
| `reload_trajectory` | 重新加载轨迹文件 | `trajectory_file`：轨迹文件路径 |
| `shutdown` | 关闭服务 | 无 |

**命令行客户端：**

```bash
# 查询状态
python src/scalp_detection_server.py client --command get_status

# 触发检测
python src/scalp_detection_server.py client --command start_detection

# 复位系统
python src/scalp_detection_server.py client --command reset

# 关闭服务
python src/scalp_detection_server.py client --command shutdown
```

## 机械臂通信协议

系统通过 TCP Socket 与机械臂通信，发送 JSON 命令：

**运动命令：**

```json
{"command":"movej","joint":[10100,200,20300,30400,500,20600],"v":50,"r":0,"trajectory_connect":0}
```

- `joint`：6 个关节角度 × 1000 取整（如 10.1° → 10100）
- `v`：运动速度
- `r`：加速度
- `trajectory_connect`：轨迹连接标志

## 错误处理

系统在检测过程中发生任何错误时：

1. 立即停止当前所有动作（紧急停止机械臂、停止相机）
2. 生成 `scan_failed` 类型的 `trigger.json`
3. 进入 ERROR 状态
4. 通过 `reset` 命令可复位系统（机械臂回起始点、相机重新初始化）

## 系统状态

| 状态 | 说明 |
|------|------|
| idle | 空闲，可接受检测命令 |
| initializing | 初始化中 |
| running | 检测执行中 |
| stopping | 停止中 |
| error | 错误状态，需复位 |
| completed | 检测完成 |

## 测试工具

### RealSense 相机测试

```bash
python test_realsense.py
```

测试 RealSense D435 相机的连接、数据获取和图像保存功能，生成测试图像到 `test_output/` 目录。

## 注意事项

- **首次运行需要网络**：需要下载 Python 依赖包
- **RealSense SDK**：确保已安装 Intel RealSense SDK
  - 下载地址：https://dev.intelrealsense.com/docs/deployment
- **硬件连接**：确保 RealSense D435、Canon 相机、机械臂已连接并开机
- **中文路径支持**：系统已支持中文路径，可将项目放在任意中文目录下