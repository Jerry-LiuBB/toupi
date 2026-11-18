using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

namespace CanonCamera
{
    public class CameraController
    {
        private CameraModel _model;
        private IntPtr _camera;
        private string _downloadPath;
        private bool _isDownloading;
        private object _downloadLock = new object();

        public event EventHandler<string> StatusChanged;
        public event EventHandler<string> ErrorOccurred;

        public CameraController(CameraModel model, string downloadPath)
        {
            _model = model;
            _camera = model.Camera;

            try
            {
                if (!Directory.Exists(downloadPath))
                {
                    Directory.CreateDirectory(downloadPath);
                }
                _downloadPath = downloadPath;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[WARN] Cannot use download path '{downloadPath}': {ex.Message}");
                Console.WriteLine("[WARN] Falling back to system temp directory.");
                _downloadPath = Path.Combine(Path.GetTempPath(), "CanonCameraPhotos");
                if (!Directory.Exists(_downloadPath))
                {
                    Directory.CreateDirectory(_downloadPath);
                }
            }
        }

        public uint OpenSession()
        {
            Console.WriteLine($"[DEBUG] OpenSession: camera handle = {_camera}, IsSessionOpen = {_model.IsSessionOpen}");

            if (_camera == IntPtr.Zero)
            {
                Console.WriteLine("[DEBUG] OpenSession: camera handle is null!");
                OnErrorOccurred("Camera handle is invalid (null)");
                return EDSDK.EDS_ERR_INVALID_HANDLE;
            }

            for (int attempt = 1; attempt <= 5; attempt++)
            {
                uint err = EDSDK.EdsOpenSession(_camera);
                Console.WriteLine($"[DEBUG] EdsOpenSession attempt {attempt}: returned 0x{err:X}");

                if (err == EDSDK.EDS_ERR_OK)
                {
                    _model.IsSessionOpen = true;
                    OnStatusChanged("Session opened");
                    return err;
                }

                OnStatusChanged($"OpenSession attempt {attempt} failed with error 0x{err:X}");

                if (err == 0x80 || err == EDSDK.EDS_ERR_INVALID_HANDLE || err == EDSDK.EDS_ERR_DEVICE_BUSY)
                {
                    Console.WriteLine("[DEBUG] Attempting to release and re-acquire camera handle...");
                    EDSDK.EdsRelease(_camera);
                    _camera = IntPtr.Zero;
                    Thread.Sleep(1000);
                    
                    uint getListErr = EDSDK.EdsGetCameraList(out IntPtr newCameraList);
                    Console.WriteLine($"[DEBUG] EdsGetCameraList: 0x{getListErr:X}");
                    if (getListErr == EDSDK.EDS_ERR_OK)
                    {
                        int cameraCount = 0;
                        EDSDK.EdsGetChildCount(newCameraList, out cameraCount);
                        Console.WriteLine($"[DEBUG] Found {cameraCount} cameras after re-scan");
                        
                        if (cameraCount > 0)
                        {
                            EDSDK.EdsGetChildAtIndex(newCameraList, 0, out _camera);
                            Console.WriteLine($"[DEBUG] Re-acquired camera handle: {_camera}");
                        }
                        EDSDK.EdsRelease(newCameraList);
                    }
                }
                
                if (attempt < 5)
                {
                    int delay = attempt * 2000;
                    Console.WriteLine($"[DEBUG] Waiting {delay}ms before retry {attempt + 1}...");
                    Thread.Sleep(delay);
                    OnStatusChanged($"Retrying attempt {attempt + 1}...");
                }
            }

            OnErrorOccurred("Failed to open session after 5 attempts");
            return EDSDK.EDS_ERR_DEVICE_NOT_FOUND;
        }

        public uint CloseSession()
        {
            uint err = EDSDK.EDS_ERR_OK;
            if (_model.IsSessionOpen && _camera != IntPtr.Zero)
            {
                err = EDSDK.EdsCloseSession(_camera);
                if (err == EDSDK.EDS_ERR_OK)
                {
                    _model.IsSessionOpen = false;
                    OnStatusChanged("Session closed");
                }
                else
                {
                    OnErrorOccurred($"Failed to close session. Error code: 0x{err:X}");
                }
            }
            return err;
        }

        public uint SetSaveToHost()
        {
            uint err = EDSDK.EDS_ERR_OK;

            IntPtr propData = Marshal.AllocHGlobal(4);
            try
            {
                Marshal.WriteInt32(propData, 0, (int)EDSDK.EdsSaveTo.SaveTo_Host);
                err = EDSDK.EdsSetPropertyData(_camera, EDSDK.PropID_SaveTo, 0, 4, propData);
            }
            finally
            {
                Marshal.FreeHGlobal(propData);
            }

            if (err == EDSDK.EDS_ERR_OK)
            {
                EDSDK.EdsCapacity capacity = new EDSDK.EdsCapacity();
                capacity.NumberOfFreeClusters = 0x7FFFFFFF;
                capacity.BytesPerSector = 0x1000;
                capacity.Reset = 1;
                err = EDSDK.EdsSetCapacity(_camera, capacity);

                if (err == EDSDK.EDS_ERR_OK)
                {
                    int currentSaveTo = GetSaveTo();
                    Console.WriteLine($"[DEBUG] Current SaveTo value: {currentSaveTo}");
                    if (currentSaveTo == (int)EDSDK.EdsSaveTo.SaveTo_Host)
                    {
                        OnStatusChanged("Set to save to host (computer)");
                    }
                    else
                    {
                        OnStatusChanged($"WARNING: SaveTo is {currentSaveTo}, expected {(int)EDSDK.EdsSaveTo.SaveTo_Host}");
                    }
                }
                else
                {
                    OnErrorOccurred($"Failed to set capacity. Error code: 0x{err:X}");
                }
            }
            else
            {
                OnErrorOccurred($"Failed to set save location. Error code: 0x{err:X}");
            }
            return err;
        }

        public uint SetDriveModeSingleShot()
        {
            // DriveMode = 0 为单张拍摄。相机若处于连拍模式, 快门保持期间会连拍多张,
            // 导致一次 fast_capture 下载两张照片。此设置尽力而为, 失败不阻断初始化。
            IntPtr propData = Marshal.AllocHGlobal(4);
            try
            {
                Marshal.WriteInt32(propData, 0, 0);
                uint err = EDSDK.EdsSetPropertyData(_camera, EDSDK.PropID_DriveMode, 0, 4, propData);
                if (err == EDSDK.EDS_ERR_OK)
                {
                    OnStatusChanged("Drive mode set to single shot");
                }
                else
                {
                    OnStatusChanged($"WARNING: Failed to set drive mode (0x{err:X}). Camera may stay in continuous shooting mode.");
                }
                return err;
            }
            finally
            {
                Marshal.FreeHGlobal(propData);
            }
        }

        private int GetSaveTo()
        {
            uint outPropertyData = 0;
            uint err = EDSDK.EdsGetPropertyData(_camera, EDSDK.PropID_SaveTo, 0, out outPropertyData);
            if (err != EDSDK.EDS_ERR_OK)
            {
                Console.WriteLine($"[DEBUG] Failed to get SaveTo property. Error: 0x{err:X}");
            }
            return (int)outPropertyData;
        }

        public uint TakePicture()
        {
            uint err = EDSDK.EDS_ERR_OK;

            OnStatusChanged("Pressing shutter (halfway)...");

            err = SendShutterCommandWithBusyRetry(
                (int)EDSDK.EdsShutterButton.CameraCommand_ShutterButton_Halfway,
                "press shutter halfway");
            if (err != EDSDK.EDS_ERR_OK)
            {
                OnErrorOccurred($"Failed to press shutter halfway. Error code: 0x{err:X}");
                return err;
            }

            Thread.Sleep(500);

            OnStatusChanged("Pressing shutter (completely)...");

            err = SendShutterCommandWithBusyRetry(
                (int)EDSDK.EdsShutterButton.CameraCommand_ShutterButton_Completely,
                "take picture");
            if (err != EDSDK.EDS_ERR_OK)
            {
                OnErrorOccurred($"Failed to take picture. Error code: 0x{err:X}");
                EDSDK.EdsSendCommand(_camera, EDSDK.CameraCommand_PressShutterButton, (int)EDSDK.EdsShutterButton.CameraCommand_ShutterButton_Off);
                return err;
            }

            Thread.Sleep(100);

            err = EDSDK.EdsSendCommand(_camera, EDSDK.CameraCommand_PressShutterButton, (int)EDSDK.EdsShutterButton.CameraCommand_ShutterButton_Off);
            if (err != EDSDK.EDS_ERR_OK)
            {
                OnErrorOccurred($"Failed to release shutter. Error code: 0x{err:X}");
            }
            else
            {
                OnStatusChanged("Picture taken successfully");
                OnStatusChanged("Waiting for image transfer event...");
            }

            return err;
        }

        /// <summary>
        /// 发送快门指令, 遇到 EDS_ERR_DEVICE_BUSY(0x8D01)自动重试。
        /// 相机刚完成一次拍摄/下载后内部缓冲尚未就绪时会返回 busy,
        /// 连续拍摄模式下两次触发间隔较短, 必须重试而不是直接报失败。
        /// busy 表示指令被相机拒绝、尚未拍照, 重试不会造成重复拍照。
        /// </summary>
        private uint SendShutterCommandWithBusyRetry(int shutterCommand, string action,
            int maxRetries = 10, int retryDelayMs = 500)
        {
            uint err;
            for (int attempt = 0; ; attempt++)
            {
                err = EDSDK.EdsSendCommand(_camera, EDSDK.CameraCommand_PressShutterButton, shutterCommand);
                if (err == EDSDK.EDS_ERR_OK || err != EDSDK.EDS_ERR_DEVICE_BUSY)
                {
                    return err;
                }
                if (attempt >= maxRetries)
                {
                    OnStatusChanged($"Camera still busy after {maxRetries} retries while trying to {action}.");
                    return err;
                }
                OnStatusChanged($"Camera busy while trying to {action}, retry {attempt + 1}/{maxRetries} in {retryDelayMs}ms...");
                Thread.Sleep(retryDelayMs);
            }
        }

        public uint DownloadImage(IntPtr directoryItem, string savePath)
        {
            lock (_downloadLock)
            {
                if (_isDownloading)
                {
                    OnErrorOccurred("Another download is in progress");
                    return EDSDK.EDS_ERR_DEVICE_BUSY;
                }
                _isDownloading = true;
            }

            try
            {
                uint err = EDSDK.EDS_ERR_OK;
                EDSDK.EdsDirectoryItemInfo dirItemInfo;
                err = EDSDK.EdsGetDirectoryItemInfo(directoryItem, out dirItemInfo);
                if (err != EDSDK.EDS_ERR_OK)
                {
                    OnErrorOccurred($"Failed to get directory item info. Error code: 0x{err:X}");
                    return err;
                }

                string fileName = dirItemInfo.szFileName;
                if (string.IsNullOrEmpty(fileName))
                {
                    OnErrorOccurred("File name is empty");
                    return EDSDK.EDS_ERR_INVALID_PARAMETER;
                }

                string fullSavePath = Path.Combine(savePath, fileName);

                OnStatusChanged($"Downloading {fileName} (size: {dirItemInfo.Size})...");

                IntPtr stream = IntPtr.Zero;
                err = EDSDK.EdsCreateFileStream(fullSavePath, EDSDK.EdsFileCreateDisposition.CreateAlways, EDSDK.EdsAccess.ReadWrite, out stream);
                if (err != EDSDK.EDS_ERR_OK)
                {
                    OnErrorOccurred($"Failed to create file stream. Error code: 0x{err:X}");
                    return err;
                }

                uint downloadSize = (uint)dirItemInfo.Size;
                err = EDSDK.EdsDownload(directoryItem, downloadSize, stream);
                if (err != EDSDK.EDS_ERR_OK)
                {
                    OnErrorOccurred($"Failed to download image. Error code: 0x{err:X}");
                    EDSDK.EdsRelease(stream);
                    return err;
                }

                err = EDSDK.EdsDownloadComplete(directoryItem);
                if (err != EDSDK.EDS_ERR_OK)
                {
                    OnErrorOccurred($"Failed to complete download. Error code: 0x{err:X}");
                    EDSDK.EdsRelease(stream);
                    return err;
                }

                EDSDK.EdsRelease(stream);

                OnStatusChanged($"Downloaded: {fileName}");

                return err;
            }
            finally
            {
                _isDownloading = false;
            }
        }

        public uint DownloadLatestImage(string savePath)
        {
            Console.WriteLine("[DEBUG] DownloadLatestImage: scanning camera storage for latest image...");

            IntPtr volumeItems = IntPtr.Zero;
            uint err = EDSDK.EdsGetChildCount(_camera, out int volumeCount);
            Console.WriteLine($"[DEBUG] Camera has {volumeCount} volume(s), err=0x{err:X}");

            if (err != EDSDK.EDS_ERR_OK || volumeCount == 0)
            {
                Console.WriteLine("[DEBUG] No volumes found on camera");
                return EDSDK.EDS_ERR_NO_IMAGED_IN_CARD;
            }

            IntPtr latestDirItem = IntPtr.Zero;
            EDSDK.EdsDirectoryItemInfo latestInfo = new EDSDK.EdsDirectoryItemInfo();
            uint latestDateTime = 0;

            for (int v = 0; v < volumeCount; v++)
            {
                IntPtr volume = IntPtr.Zero;
                err = EDSDK.EdsGetChildAtIndex(_camera, v, out volume);
                if (err != EDSDK.EDS_ERR_OK || volume == IntPtr.Zero)
                {
                    Console.WriteLine($"[DEBUG] Failed to get volume {v}, err=0x{err:X}");
                    continue;
                }

                try
                {
                    err = EDSDK.EdsGetChildCount(volume, out int dcimCount);
                    Console.WriteLine($"[DEBUG] Volume {v} has {dcimCount} DCIM folder(s), err=0x{err:X}");
                    if (err != EDSDK.EDS_ERR_OK) continue;

                    for (int d = 0; d < dcimCount; d++)
                    {
                        IntPtr dcim = IntPtr.Zero;
                        err = EDSDK.EdsGetChildAtIndex(volume, d, out dcim);
                        if (err != EDSDK.EDS_ERR_OK || dcim == IntPtr.Zero) continue;

                        try
                        {
                            err = EDSDK.EdsGetChildCount(dcim, out int folderCount);
                            if (err != EDSDK.EDS_ERR_OK) continue;

                            for (int f = 0; f < folderCount; f++)
                            {
                                IntPtr folder = IntPtr.Zero;
                                err = EDSDK.EdsGetChildAtIndex(dcim, f, out folder);
                                if (err != EDSDK.EDS_ERR_OK || folder == IntPtr.Zero) continue;

                                try
                                {
                                    err = EDSDK.EdsGetChildCount(folder, out int fileCount);
                                    if (err != EDSDK.EDS_ERR_OK) continue;

                                    for (int fi = 0; fi < fileCount; fi++)
                                    {
                                        IntPtr fileItem = IntPtr.Zero;
                                        err = EDSDK.EdsGetChildAtIndex(folder, fi, out fileItem);
                                        if (err != EDSDK.EDS_ERR_OK || fileItem == IntPtr.Zero) continue;

                                        try
                                        {
                                            EDSDK.EdsDirectoryItemInfo itemInfo;
                                            err = EDSDK.EdsGetDirectoryItemInfo(fileItem, out itemInfo);
                                            if (err != EDSDK.EDS_ERR_OK) continue;

                                            if (itemInfo.isFolder == 0 && itemInfo.dateTime > latestDateTime)
                                            {
                                                if (latestDirItem != IntPtr.Zero)
                                                {
                                                    EDSDK.EdsRelease(latestDirItem);
                                                }
                                                latestDirItem = fileItem;
                                                latestInfo = itemInfo;
                                                latestDateTime = itemInfo.dateTime;
                                                fileItem = IntPtr.Zero;
                                            }
                                        }
                                        finally
                                        {
                                            if (fileItem != IntPtr.Zero)
                                                EDSDK.EdsRelease(fileItem);
                                        }
                                    }
                                }
                                finally
                                {
                                    EDSDK.EdsRelease(folder);
                                }
                            }
                        }
                        finally
                        {
                            EDSDK.EdsRelease(dcim);
                        }
                    }
                }
                finally
                {
                    EDSDK.EdsRelease(volume);
                }
            }

            if (latestDirItem == IntPtr.Zero)
            {
                Console.WriteLine("[DEBUG] No image files found on camera");
                return EDSDK.EDS_ERR_NO_IMAGED_IN_CARD;
            }

            try
            {
                Console.WriteLine($"[DEBUG] Latest image: {latestInfo.szFileName}, size={latestInfo.Size}, dateTime={latestInfo.dateTime}");
                return DownloadImage(latestDirItem, savePath);
            }
            finally
            {
                EDSDK.EdsRelease(latestDirItem);
            }
        }

        public uint GetAvailableShots()
        {
            uint shots = 0;
            uint err = EDSDK.EdsGetPropertyData(_camera, EDSDK.PropID_AvailableShots, 0, out shots);
            if (err != EDSDK.EDS_ERR_OK)
            {
                OnErrorOccurred($"Failed to get available shots. Error code: 0x{err:X}");
            }
            return shots;
        }

        public uint GetBatteryLevel()
        {
            uint battery = 0;
            uint err = EDSDK.EdsGetPropertyData(_camera, EDSDK.PropID_BatteryLevel, 0, out battery);
            if (err != EDSDK.EDS_ERR_OK)
            {
                OnErrorOccurred($"Failed to get battery level. Error code: 0x{err:X}");
            }
            return battery;
        }

        // 保活探测: 直接返回SDK错误码(不吞错), 供服务端判定USB会话是否存活
        public uint CheckAlive()
        {
            uint battery = 0;
            return EDSDK.EdsGetPropertyData(_camera, EDSDK.PropID_BatteryLevel, 0, out battery);
        }

        protected virtual void OnStatusChanged(string status)
        {
            StatusChanged?.Invoke(this, status);
        }

        protected virtual void OnErrorOccurred(string error)
        {
            ErrorOccurred?.Invoke(this, error);
        }
    }
}
