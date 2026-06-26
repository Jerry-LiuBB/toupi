# 佳能相机远程控制程序

## 概述

这是一个C#应用程序，允许你通过USB连接从Windows电脑控制佳能相机。它使用佳能EOS数码SDK (EDSDK) 实现以下功能：

- 连接佳能相机
- 触发相机拍照
- 将拍摄的图片直接下载到电脑
- 保存图片到指定文件夹

## 系统要求

### 硬件
- 支持PTP协议的佳能EOS数码相机
- USB数据线连接相机和电脑
- 相机上的USB Type-C接口（使用USB-A转Type-C转接线/适配器）

### 软件
- Windows 10/11 (x86/32位)
- .NET Framework 4.8
- 佳能EOS数码SDK（已包含在项目中）

## 项目结构

```
CanonCameraControl/
├── EDSDK.cs              # 佳能EDSDK的P/Invoke封装
├── CameraModel.cs        # 相机模型类
├── CameraController.cs   # 相机控制逻辑
├── CameraManager.cs      # 相机发现和事件管理
├── Program.cs            # 主程序入口
├── CanonCameraControl.csproj  # 项目文件
├── EDSDK.dll             # 佳能SDK动态链接库
├── EdsImage.dll          # 佳能图像处理库
├── Build.bat             # 构建脚本
├── Run.bat               # 运行脚本
└── README.md             # 本文件
```

## 安装说明

### 第一步：构建项目

1. 打开命令提示符或PowerShell
2. 进入 `CanonCameraControl` 文件夹
3. 运行 `Build.bat` 或执行：
   ```
   dotnet restore CanonCameraControl.csproj
   dotnet build CanonCameraControl.csproj -c Release
   ```

### 第二步：配置相机设置

运行程序前，请先配置相机：

1. 打开佳能相机电源
2. 进入菜单 > 设置（扳手图标）
3. 找到"USB"或"通信"设置
4. 将USB连接模式设置为 **"PC"** 或 **"EOS Utility"**
5. 如果有"保存到"选项，设置为 **"PC"** 或 **"电脑"**
6. 建议将自动关机设置为 **关闭**（防止相机进入休眠）

### 第三步：连接相机

1. 使用USB数据线将相机连接到电脑
2. 确保相机电源已开启
3. 在设备管理器中应能看到已连接的相机

## 使用方法

### 基本用法

1. 进入 `CanonCameraControl` 文件夹
2. 双击运行 `Run.bat`
3. 程序将：
   - 初始化佳能SDK
   - 检测已连接的相机
   - 默认拍摄1张照片
   - 保存到 `C:\Users\dell\Downloads\CanonCameraPhotos`

### 自定义用法

可以通过命令行参数自定义程序行为：

```
CanonCameraControl.exe [下载路径] [照片数量] [间隔毫秒]
```

参数说明：
- **下载路径**: 照片保存的完整路径（默认：C:\Users\dell\Downloads\CanonCameraPhotos）
- **照片数量**: 要拍摄的照片数量（默认：1）
- **间隔毫秒**: 每次拍摄之间的延迟，单位毫秒（默认：2000）

使用示例：

```bash
# 拍摄5张照片并保存到 D:\MyPhotos，间隔3秒
CanonCameraControl.exe "D:\MyPhotos" 5 3000

# 拍摄1张照片到自定义路径
CanonCameraControl.exe "E:\Canon\Session1" 1 2000

# 拍摄10张照片，间隔5秒
CanonCameraControl.exe "C:\Photos\Event2024" 10 5000
```

## 故障排除

### 相机未检测到

1. **检查USB连接**：尝试更换USB端口或数据线
2. **检查相机模式**：确保相机设置为PC/EOS Utility模式
3. **重启相机**：关闭相机后再重新开启
4. **检查设备管理器**：确保没有驱动程序冲突

### SDK初始化失败

错误代码 `0xXXXXXXXX`：
- 确保 EDSDK.dll 在可执行文件同一目录下
- 确保使用的是x86（32位）版本应用程序
- 尝试以管理员身份运行

### 下载失败

1. 确保下载文件夹存在且有写入权限
2. 检查电脑可用空间
3. 确保相机电池电量充足

### 相机断开连接

1. 在相机设置中禁用自动关机
2. 禁用休眠模式
3. 使用充满电的电池
4. 使用直接USB连接（不要通过Hub）

## 工作原理

### 连接流程

1. **初始化SDK**：`EdsInitializeSDK()`
2. **获取相机列表**：`EdsGetCameraList()`
3. **打开会话**：`EdsOpenSession()`
4. **设置保存位置**：将 `PropID_SaveTo` 设置为 `SaveTo_Host`
5. **设置容量**：配置下载容量

### 拍照流程

1. **按下快门**：`EdsSendCommand(CameraCommand_PressShutterButton, ShutterButton_Completely)`
2. **释放快门**：`EdsSendCommand(CameraCommand_PressShutterButton, ShutterButton_Off)`

### 下载图片流程

1. **事件触发**：相机发送 `ObjectEvent_DirItemRequestTransfer` 事件
2. **获取信息**：`EdsGetDirectoryItemInfo()`
3. **创建流**：`EdsCreateFileStream()`
4. **下载**：`EdsDownload()`
5. **完成**：`EdsDownloadComplete()`

## 重要提示

- 相机必须处于 **PC/EOS Utility模式** 才能进行远程拍摄
- 图片将使用相机原始文件名保存
- 程序自动处理RAW和JPEG文件
- 相机必须支持PTP（图片传输协议）
- 部分相机设置可能需要在相机本身上配置

## 支持的相机

通常支持满足以下条件的佳能EOS相机：
- 支持EOS Utility模式
- 支持PTP协议
- 未被锁定或限制

## 许可证

本代码使用佳能EOS数码SDK，须遵守佳能的许可协议。有关许可条款请参阅SDK文档。

## 技术支持

如遇到以下问题：
- **相机兼容性**：查看佳能EOS Utility兼容性列表
- **SDK错误**：参阅SDK文档中的 EDSDK_API_EN.pdf
- **代码问题**：查看提供的错误代码和消息
