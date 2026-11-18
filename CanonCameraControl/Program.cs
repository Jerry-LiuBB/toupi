using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace CanonCamera
{
    class CameraConfig
    {
        public string downloadPath { get; set; } = Path.Combine(Path.GetTempPath(), "CanonCameraPhotos");
        public int numberOfPhotos { get; set; } = 1;
        public int delayBetweenPhotosMs { get; set; } = 2000;
        public bool serverMode { get; set; } = false;
        public int serverPort { get; set; } = 8765;
    }

    class Program
    {
        private const string CONFIG_FILE = "config.json";

        private static CameraManager _manager;
        private static CameraController _controller;
        private static string _downloadPath = Path.Combine(Path.GetTempPath(), "CanonCameraPhotos");
        private static ManualResetEvent _downloadEvent = new ManualResetEvent(false);
        private static int _downloadCount = 0;
        private static bool _serverRunning = false;
        private static TcpListener _tcpListener;
        private static bool _isCapturing = false;
        private static int _pendingPhotos = 0;
        private static int _capturedPhotos = 0;
        private static object _captureLock = new object();

        // 保活相关: 周期性查询相机保持USB会话活跃, 失联后自动重连
        private static DateTime _lastKeepAliveUtc = DateTime.MinValue;
        private static int _keepAliveFailures = 0;
        private const int KEEP_ALIVE_INTERVAL_SEC = 20;
        private const int KEEP_ALIVE_MAX_FAILURES = 2;

        private static BlockingCollection<CommandTask> _commandQueue = new BlockingCollection<CommandTask>();

        private class CommandTask
        {
            public string Command;
            public ManualResetEventSlim Completed = new ManualResetEventSlim(false);
            public string Response = "";
        }

        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("========================================");
            Console.WriteLine("Canon Camera Remote Control Program");
            Console.WriteLine("========================================");
            Console.WriteLine();

            bool serverMode = args.Length > 0 && args[0].Equals("-server", StringComparison.OrdinalIgnoreCase);
            int serverPort = 8765;
            
            if (serverMode && args.Length > 1)
            {
                if (int.TryParse(args[1], out int p))
                {
                    serverPort = p;
                }
            }

            if (serverMode)
            {
                RunServerMode(serverPort);
            }
            else
            {
                RunSingleShotMode(args);
            }
        }

        static void RunSingleShotMode(string[] args)
        {
            string downloadPath;
            int numberOfPhotos;
            int delayBetweenPhotos;

            if (File.Exists(CONFIG_FILE))
            {
                try
                {
                    string json = File.ReadAllText(CONFIG_FILE);
                    var config = JsonSerializer.Deserialize<CameraConfig>(json);
                    downloadPath = config.downloadPath;
                    numberOfPhotos = config.numberOfPhotos;
                    delayBetweenPhotos = config.delayBetweenPhotosMs;
                    Console.WriteLine($"[Config] Loaded settings from {CONFIG_FILE}");
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[Config] Failed to load {CONFIG_FILE}: {ex.Message}");
                    Console.WriteLine("[Config] Using default settings");
                    downloadPath = Path.Combine(Path.GetTempPath(), "CanonCameraPhotos");
                    numberOfPhotos = 1;
                    delayBetweenPhotos = 2000;
                }
            }
            else
            {
                downloadPath = Path.Combine(Path.GetTempPath(), "CanonCameraPhotos");
                numberOfPhotos = 1;
                delayBetweenPhotos = 2000;
                Console.WriteLine($"[Config] {CONFIG_FILE} not found, using default settings");
            }

            if (args.Length > 0)
            {
                downloadPath = args[0];
                Console.WriteLine($"[Config] Override: download path = {downloadPath}");
            }
            if (args.Length > 1)
            {
                if (int.TryParse(args[1], out int n) && n > 0)
                {
                    numberOfPhotos = n;
                    Console.WriteLine($"[Config] Override: number of photos = {numberOfPhotos}");
                }
            }
            if (args.Length > 2)
            {
                if (int.TryParse(args[2], out int d) && d >= 0)
                {
                    delayBetweenPhotos = d;
                    Console.WriteLine($"[Config] Override: delay = {delayBetweenPhotos}ms");
                }
            }

            Console.WriteLine($"Download Path: {downloadPath}");
            Console.WriteLine($"Number of Photos: {numberOfPhotos}");
            Console.WriteLine($"Delay between photos: {delayBetweenPhotos}ms");
            Console.WriteLine();

            CameraManager manager = null;
            CameraController controller = null;
            ManualResetEvent downloadEvent = new ManualResetEvent(false);
            int downloadCount = 0;

            try
            {
                manager = new CameraManager();

                Console.WriteLine("[1] Initializing SDK...");
                uint err = manager.Initialize();
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"Failed to initialize SDK. Error code: 0x{err:X}");
                    return;
                }
                Console.WriteLine("SDK initialized successfully");

                Console.WriteLine("[1.5] Waiting for camera USB enumeration...");
                Thread.Sleep(3000);

                Console.WriteLine("\n[2] Searching for cameras...");
                List<CameraModel> cameras = manager.GetCameraList();
                if (cameras.Count == 0)
                {
                    Console.WriteLine("No cameras found. Please check:");
                    Console.WriteLine("  - Camera is powered on");
                    Console.WriteLine("  - USB cable is connected");
                    Console.WriteLine("  - Camera is not in use by another application");
                    return;
                }

                CameraModel cameraModel = cameras[0];
                Console.WriteLine($"Found camera: {cameraModel.ModelName}");

                controller = new CameraController(cameraModel, downloadPath);

                controller.StatusChanged += (sender, status) =>
                {
                    Console.WriteLine($"[Status] {status}");
                };

                controller.ErrorOccurred += (sender, error) =>
                {
                    Console.WriteLine($"[Error] {error}");
                };

                Console.WriteLine("\n[3] Setting up event handlers...");
                manager.ObjectEventOccurred += (sender, directoryItem) =>
                {
                    Console.WriteLine("\n[Event] DirItemRequestTransfer - downloading image...");
                    uint dlErr = controller.DownloadImage(directoryItem, downloadPath);
                    if (dlErr == EDSDK.EDS_ERR_OK)
                    {
                        Interlocked.Increment(ref downloadCount);
                        downloadEvent.Set();
                    }
                    else
                    {
                        Console.WriteLine($"[Event] Download failed with error: 0x{dlErr:X}");
                    }
                };

                err = manager.SetEventHandlers(cameraModel.Camera);
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"Failed to set event handlers. Error code: 0x{err:X}");
                    return;
                }
                Console.WriteLine("Event handlers registered successfully");

                Console.WriteLine("\n[4] Waiting 2 seconds before opening session...");
                Thread.Sleep(2000);

                Console.WriteLine("\n[5] Opening camera session...");
                err = controller.OpenSession();
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"Failed to open session. Error code: 0x{err:X}");
                    return;
                }

                Console.WriteLine("\n[6] Configuring camera to save to computer...");
                err = controller.SetSaveToHost();
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"Failed to set save location. Error code: 0x{err:X}");
                    return;
                }

                uint shotsBefore = controller.GetAvailableShots();
                Console.WriteLine($"Available shots before photo: {shotsBefore}");

                Console.WriteLine($"\n[7] Taking {numberOfPhotos} photo(s)...");
                for (int i = 0; i < numberOfPhotos; i++)
                {
                    Console.WriteLine($"\n--- Photo {i + 1} of {numberOfPhotos} ---");

                    downloadEvent.Reset();

                    err = controller.TakePicture();

                    if (err != EDSDK.EDS_ERR_OK)
                    {
                        Console.WriteLine($"Failed to take picture. Error code: 0x{err:X}");
                        continue;
                    }

                    Console.WriteLine("Waiting for image download event (max 15 seconds)...");
                    int waitMs = 0;
                    bool received = false;
                    while (waitMs < 15000)
                    {
                        ProcessWindowsMessages();
                        if (downloadEvent.WaitOne(100))
                        {
                            received = true;
                            break;
                        }
                        waitMs += 100;
                    }

                    if (received)
                    {
                        Console.WriteLine("Image downloaded successfully via event!");
                    }
                    else
                    {
                        Console.WriteLine("[Warning] Timeout waiting for download event.");
                        Console.WriteLine("Attempting to find and download the latest image from camera...");
                        uint dlErr = controller.DownloadLatestImage(downloadPath);
                        if (dlErr == EDSDK.EDS_ERR_OK)
                        {
                            Console.WriteLine("Image downloaded successfully via manual scan!");
                            Interlocked.Increment(ref downloadCount);
                        }
                        else
                        {
                            Console.WriteLine($"Manual download also failed. Error: 0x{dlErr:X}");
                        }
                    }

                    if (i < numberOfPhotos - 1)
                    {
                        Thread.Sleep(delayBetweenPhotos);
                    }
                }

                uint shotsAfter = controller.GetAvailableShots();
                Console.WriteLine($"Available shots after photo: {shotsAfter}");

                Console.WriteLine("\n[7] Closing camera session...");
                controller.CloseSession();

                Console.WriteLine("\n========================================");
                Console.WriteLine("Operation completed!");
                Console.WriteLine($"Total images downloaded: {downloadCount}");
                Console.WriteLine($"Photos saved to: {downloadPath}");

                if (Directory.Exists(downloadPath))
                {
                    string[] files = Directory.GetFiles(downloadPath, "*.*", SearchOption.TopDirectoryOnly);
                    Console.WriteLine($"Files in download directory: {files.Length}");
                    foreach (string f in files)
                    {
                        Console.WriteLine($"  {Path.GetFileName(f)} ({new FileInfo(f).Length} bytes)");
                    }
                }

                Console.WriteLine("========================================");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"\nException occurred: {ex.Message}");
                Console.WriteLine($"Stack trace: {ex.StackTrace}");
            }
            finally
            {
                if (controller != null)
                {
                    controller.CloseSession();
                }

                if (manager != null)
                {
                    Console.WriteLine("\n[8] Terminating SDK...");
                    manager.Terminate();
                    manager.Dispose();
                }

                if (Array.IndexOf(args, "-nopause") == -1)
                {
                    Console.WriteLine("\nPress any key to exit...");
                    Console.ReadKey();
                }
            }
        }

        static void RunServerMode(int port)
        {
            Console.WriteLine($"[Server] Starting Canon Camera TCP Service on port {port}...");

            try
            {
                InitializeCamera();

                _tcpListener = new TcpListener(IPAddress.Loopback, port);
                _tcpListener.Start();
                Console.WriteLine($"[Server] TCP listener started on 127.0.0.1:{port}");
                Console.WriteLine("[Server] Waiting for commands...");

                _serverRunning = true;

                while (_serverRunning)
                {
                    try
                    {
                        _tcpListener.Server.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.ReceiveTimeout, 100);

                        if (_tcpListener.Server.Poll(100000, SelectMode.SelectRead))
                        {
                            TcpClient client = _tcpListener.AcceptTcpClient();
                            ThreadPool.QueueUserWorkItem(HandleClient, client);
                        }
                    }
                    catch (SocketException)
                    {
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"[Server] Error accepting client: {ex.Message}");
                    }

                    while (_commandQueue.TryTake(out CommandTask task, 0))
                    {
                        try
                        {
                            task.Response = ProcessCommand(task.Command);
                        }
                        catch (Exception ex)
                        {
                            task.Response = "{\"success\":false,\"error\":\"" + ex.Message.Replace("\"", "\\\"") + "\"}";
                        }
                        finally
                        {
                            task.Completed.Set();
                        }
                    }

                    // 保活: 空闲时周期查询相机, 防止USB会话被挂起; 失联自动重连
                    TryKeepAlive();
                }
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Server] Error: {ex.Message}");
            }
            finally
            {
                CleanupCamera();
                if (_tcpListener != null)
                {
                    _tcpListener.Stop();
                }
                Console.WriteLine("[Server] Service stopped.");
            }
        }

        static void HandleClient(object obj)
        {
            TcpClient client = (TcpClient)obj;
            try
            {
                NetworkStream stream = client.GetStream();
                byte[] buffer = new byte[4096];
                int bytesRead = stream.Read(buffer, 0, buffer.Length);

                string request = Encoding.UTF8.GetString(buffer, 0, bytesRead).Trim();
                Console.WriteLine($"[Server] Received command: {request}");

                var task = new CommandTask { Command = request };
                _commandQueue.Add(task);

                if (!task.Completed.Wait(TimeSpan.FromMinutes(2)))
                {
                    task.Response = "{\"success\":false,\"error\":\"Command processing timeout\"}";
                }

                byte[] responseBytes = Encoding.UTF8.GetBytes(task.Response + "\n");
                stream.Write(responseBytes, 0, responseBytes.Length);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Server] Client error: {ex.Message}");
            }
            finally
            {
                client.Close();
            }
        }

        static string ProcessCommand(string command)
        {
            try
            {
                string[] parts = command.Split(new[] { ' ' }, 2);
                string cmd = parts[0].ToLower();
                string args = parts.Length > 1 ? parts[1] : "";

                switch (cmd)
                {
                    case "status":
                        bool isCapturing = _isCapturing;
                        return "{\"success\":true,\"connected\":" + (_controller != null).ToString().ToLower() + ",\"download_count\":" + _downloadCount + ",\"is_capturing\":" + isCapturing.ToString().ToLower() + "}";

                    case "capture":
                        return CapturePhoto(args);

                    case "capture_async":
                        return CapturePhotoAsync(args);

                    case "capture_status":
                        return CaptureStatus();

                    case "batch_capture":
                        return BatchCapture(args);

                    case "fast_capture":
                        return FastCapture(args);

                    case "set_camera_param":
                        return SetCameraParam(args);

                    case "get_camera_param":
                        return GetCameraParam(args);

                    case "set_path":
                        _downloadPath = args;
                        if (!Directory.Exists(_downloadPath))
                        {
                            Directory.CreateDirectory(_downloadPath);
                        }
                        Console.WriteLine($"[Server] Download path set to: {_downloadPath}");
                        return "{\"success\":true,\"message\":\"Path updated\"}";

                    case "reconnect":
                        CleanupCamera();
                        Thread.Sleep(1000);
                        InitializeCamera();
                        return "{\"success\":true,\"message\":\"Camera reconnected\"}";

                    case "shutdown":
                        _serverRunning = false;
                        return "{\"success\":true,\"message\":\"Server shutting down\"}";

                    default:
                        return "{\"success\":false,\"error\":\"Unknown command: " + cmd + "\"}";
                }
            }
            catch (Exception ex)
            {
                return "{\"success\":false,\"error\":\"" + ex.Message.Replace("\"", "\\\"") + "\"}";
            }
        }

        static string CapturePhoto(string args)
        {
            if (_controller == null)
            {
                return "{\"success\":false,\"error\":\"Camera not initialized\"}";
            }

            _downloadEvent.Reset();
            uint err = _controller.TakePicture();

            if (err != EDSDK.EDS_ERR_OK)
            {
                Console.WriteLine($"[Server] Failed to take picture. Error: 0x{err:X}");
                return "{\"success\":false,\"error\":\"Failed to take picture. Error: 0x" + err.ToString("X") + "\"}";
            }

            Console.WriteLine("[Server] Waiting for download event (max 15 seconds)...");
            int waitMs = 0;
            bool received = false;
            while (waitMs < 15000)
            {
                ProcessWindowsMessages();
                if (_downloadEvent.WaitOne(100))
                {
                    received = true;
                    break;
                }
                waitMs += 100;
            }

            if (received)
            {
                Interlocked.Increment(ref _downloadCount);
                Console.WriteLine("[Server] Image downloaded successfully!");
                return "{\"success\":true,\"download_count\":" + _downloadCount + "}";
            }
            else
            {
                Console.WriteLine("[Server] Timeout waiting for download event.");
                uint dlErr = _controller.DownloadLatestImage(_downloadPath);
                if (dlErr == EDSDK.EDS_ERR_OK)
                {
                    Interlocked.Increment(ref _downloadCount);
                    Console.WriteLine("[Server] Image downloaded via manual scan!");
                    return "{\"success\":true,\"download_count\":" + _downloadCount + "}";
                }
                else
                {
                    Console.WriteLine($"[Server] Manual download failed. Error: 0x{dlErr:X}");
                    return "{\"success\":false,\"error\":\"Download failed. Error: 0x" + dlErr.ToString("X") + "\"}";
                }
            }
        }

        static string CapturePhotoAsync(string args)
        {
            if (_controller == null)
            {
                return "{\"success\":false,\"error\":\"Camera not initialized\"}";
            }

            if (_isCapturing)
            {
                return "{\"success\":false,\"error\":\"Camera is busy capturing\"}";
            }

            lock (_captureLock)
            {
                if (_isCapturing)
                {
                    return "{\"success\":false,\"error\":\"Camera is busy capturing\"}";
                }
                _isCapturing = true;
            }

            ThreadPool.QueueUserWorkItem(delegate
            {
                try
                {
                    _downloadEvent.Reset();
                    uint err = _controller.TakePicture();

                    if (err != EDSDK.EDS_ERR_OK)
                    {
                        Console.WriteLine($"[Server] Async capture failed. Error: 0x{err:X}");
                        return;
                    }

                    Console.WriteLine("[Server] Async waiting for download event...");
                    int waitMs = 0;
                    bool received = false;
                    while (waitMs < 15000)
                    {
                        ProcessWindowsMessages();
                        if (_downloadEvent.WaitOne(100))
                        {
                            received = true;
                            break;
                        }
                        waitMs += 100;
                    }

                    if (received)
                    {
                        Interlocked.Increment(ref _downloadCount);
                        Console.WriteLine("[Server] Async image downloaded successfully!");
                    }
                    else
                    {
                        Console.WriteLine("[Server] Async timeout waiting for download event.");
                        uint dlErr = _controller.DownloadLatestImage(_downloadPath);
                        if (dlErr == EDSDK.EDS_ERR_OK)
                        {
                            Interlocked.Increment(ref _downloadCount);
                            Console.WriteLine("[Server] Async image downloaded via manual scan!");
                        }
                        else
                        {
                            Console.WriteLine($"[Server] Async manual download failed. Error: 0x{dlErr:X}");
                        }
                    }
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[Server] Async capture exception: {ex.Message}");
                }
                finally
                {
                    _isCapturing = false;
                }
            });

            return "{\"success\":true,\"message\":\"Capture started asynchronously\"}";
        }

        static string CaptureStatus()
        {
            return "{\"success\":true,\"is_capturing\":" + _isCapturing.ToString().ToLower() + ",\"download_count\":" + _downloadCount + ",\"pending_photos\":" + _pendingPhotos + "}";
        }

        static string BatchCapture(string args)
        {
            if (_controller == null)
            {
                return "{\"success\":false,\"error\":\"Camera not initialized\"}";
            }

            string[] parts = args.Split(' ');
            int count = 1;
            int delayMs = 1000;

            if (parts.Length > 0 && int.TryParse(parts[0], out int c))
            {
                count = c;
            }
            if (parts.Length > 1 && int.TryParse(parts[1], out int d))
            {
                delayMs = d;
            }

            Console.WriteLine($"[Server] Starting batch capture of {count} photos with {delayMs}ms delay...");

            int successCount = 0;
            for (int i = 0; i < count; i++)
            {
                if (i > 0 && delayMs > 0)
                {
                    Thread.Sleep(delayMs);
                }

                _downloadEvent.Reset();
                uint err = _controller.TakePicture();

                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"[Server] Batch photo {i + 1} failed. Error: 0x{err:X}");
                    continue;
                }

                Console.WriteLine($"[Server] Batch photo {i + 1}: waiting for download...");
                int waitMs = 0;
                bool received = false;
                while (waitMs < 15000)
                {
                    ProcessWindowsMessages();
                    if (_downloadEvent.WaitOne(100))
                    {
                        received = true;
                        break;
                    }
                    waitMs += 100;
                }

                if (received)
                {
                    Interlocked.Increment(ref _downloadCount);
                    successCount++;
                    Console.WriteLine($"[Server] Batch photo {i + 1} downloaded successfully!");
                }
                else
                {
                    Console.WriteLine($"[Server] Batch photo {i + 1} timeout.");
                    uint dlErr = _controller.DownloadLatestImage(_downloadPath);
                    if (dlErr == EDSDK.EDS_ERR_OK)
                    {
                        Interlocked.Increment(ref _downloadCount);
                        successCount++;
                        Console.WriteLine($"[Server] Batch photo {i + 1} downloaded via manual scan!");
                    }
                    else
                    {
                        Console.WriteLine($"[Server] Batch photo {i + 1} download failed. Error: 0x{dlErr:X}");
                    }
                }
            }

            Console.WriteLine($"[Server] Batch capture completed. Success: {successCount}/{count}");
            return "{\"success\":true,\"batch_count\":" + count + ",\"success_count\":" + successCount + ",\"download_count\":" + _downloadCount + "}";
        }

        static bool InitializeCamera()
        {
            try
            {
                Console.WriteLine("[Server] Initializing camera...");

                _manager = new CameraManager();

                Console.WriteLine("[Server] [1] Initializing SDK...");
                uint err = _manager.Initialize();
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"[Server] Failed to initialize SDK. Error: 0x{err:X}");
                    return false;
                }
                Console.WriteLine("[Server] SDK initialized successfully");

                Console.WriteLine("[Server] [1.5] Waiting for camera USB enumeration...");
                Thread.Sleep(3000);

                Console.WriteLine("[Server] [2] Searching for cameras...");
                List<CameraModel> cameras = _manager.GetCameraList();
                if (cameras.Count == 0)
                {
                    Console.WriteLine("[Server] No cameras found");
                    return false;
                }

                CameraModel cameraModel = cameras[0];
                Console.WriteLine($"[Server] Found camera: {cameraModel.ModelName}");

                _controller = new CameraController(cameraModel, _downloadPath);

                _controller.StatusChanged += (sender, status) =>
                {
                    Console.WriteLine($"[Server][Status] {status}");
                };

                _controller.ErrorOccurred += (sender, error) =>
                {
                    Console.WriteLine($"[Server][Error] {error}");
                };

                Console.WriteLine("[Server] [3] Setting up event handlers...");
                _manager.ObjectEventOccurred += (sender, directoryItem) =>
                {
                    Console.WriteLine("[Server] [Event] DirItemRequestTransfer - downloading image...");
                    uint dlErr = _controller.DownloadImage(directoryItem, _downloadPath);
                    if (dlErr == EDSDK.EDS_ERR_OK)
                    {
                        _downloadEvent.Set();
                    }
                    else
                    {
                        Console.WriteLine($"[Server] [Event] Download failed: 0x{dlErr:X}");
                    }
                };

                err = _manager.SetEventHandlers(cameraModel.Camera);
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"[Server] Failed to set event handlers. Error: 0x{err:X}");
                    return false;
                }
                Console.WriteLine("[Server] Event handlers registered");

                Console.WriteLine("[Server] [4] Waiting 2 seconds before opening session...");
                Thread.Sleep(2000);

                Console.WriteLine("[Server] [5] Opening camera session...");
                err = _controller.OpenSession();
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"[Server] Failed to open session. Error: 0x{err:X}");
                    Console.WriteLine("[Server] Attempting full restart...");
                    
                    _manager.Terminate();
                    Thread.Sleep(2000);
                    
                    err = _manager.Initialize();
                    if (err != EDSDK.EDS_ERR_OK)
                    {
                        Console.WriteLine($"[Server] Failed to re-initialize SDK. Error: 0x{err:X}");
                        return false;
                    }
                    
                    Thread.Sleep(3000);
                    cameras = _manager.GetCameraList();
                    if (cameras.Count == 0)
                    {
                        Console.WriteLine("[Server] No cameras found after restart");
                        return false;
                    }
                    
                    cameraModel = cameras[0];
                    _controller = new CameraController(cameraModel, _downloadPath);
                    
                    _controller.StatusChanged += (sender, status) =>
                    {
                        Console.WriteLine($"[Server][Status] {status}");
                    };
                    _controller.ErrorOccurred += (sender, error) =>
                    {
                        Console.WriteLine($"[Server][Error] {error}");
                    };
                    
                    _manager.ObjectEventOccurred += (sender, directoryItem) =>
                    {
                        Console.WriteLine("[Server] [Event] DirItemRequestTransfer - downloading image...");
                        uint dlErr = _controller.DownloadImage(directoryItem, _downloadPath);
                        if (dlErr == EDSDK.EDS_ERR_OK)
                        {
                            _downloadEvent.Set();
                        }
                    };
                    
                    uint setErr = _manager.SetEventHandlers(cameraModel.Camera);
                    if (setErr != EDSDK.EDS_ERR_OK)
                    {
                        Console.WriteLine($"[Server] Failed to set event handlers after restart. Error: 0x{setErr:X}");
                        return false;
                    }
                    
                    err = _controller.OpenSession();
                    if (err != EDSDK.EDS_ERR_OK)
                    {
                        Console.WriteLine($"[Server] Failed to open session after restart. Error: 0x{err:X}");
                        return false;
                    }
                    Console.WriteLine("[Server] Session opened after restart!");
                }

                Console.WriteLine("[Server] Setting drive mode to single shot...");
                _controller.SetDriveModeSingleShot();

                Console.WriteLine("[Server] [6] Configuring camera to save to computer...");
                err = _controller.SetSaveToHost();
                if (err != EDSDK.EDS_ERR_OK)
                {
                    Console.WriteLine($"[Server] Failed to set save location. Error: 0x{err:X}");
                    return false;
                }

                Console.WriteLine("[Server] Camera initialized and ready!");
                return true;
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[Server] Initialization error: {ex.Message}");
                return false;
            }
        }

        // 保活逻辑(仅在服务模式主线程执行, 保证EDSDK线程安全):
        // 1. 相机连接正常时每20秒读一次电量, 保持USB/PTP会话活跃,
        //    防止相机空闲后被Windows或机身USB栈挂起导致连接失效
        // 2. 连续2次探测失败(排除DEVICE_BUSY)判定为失联:
        //    关闭旧会话并重新枚举相机(相当于软件层面的"重启相机"),
        //    期间收到的拍照命令会排队等待(客户端超时2分钟, 足够重连)
        private static void TryKeepAlive()
        {
            if (_isCapturing)
            {
                return;
            }

            double secSinceLast = (DateTime.UtcNow - _lastKeepAliveUtc).TotalSeconds;
            if (secSinceLast < KEEP_ALIVE_INTERVAL_SEC)
            {
                return;
            }
            _lastKeepAliveUtc = DateTime.UtcNow;

            if (_controller == null)
            {
                // 启动时相机未就绪: 不在此处后台重连。
                // Python端此时已回退单机模式(每次拍照启动独立exe进程),
                // 若本进程抢占会话会导致单机模式拍照失败。
                return;
            }

            try
            {
                uint err = _controller.CheckAlive();
                if (err == EDSDK.EDS_ERR_OK || err == EDSDK.EDS_ERR_DEVICE_BUSY)
                {
                    // DEVICE_BUSY = 相机忙(如缓存写入), 连接本身是健康的
                    if (_keepAliveFailures > 0)
                    {
                        Console.WriteLine($"[KeepAlive] 相机通信已恢复 (此前连续失败 {_keepAliveFailures} 次)");
                    }
                    _keepAliveFailures = 0;
                    return;
                }

                _keepAliveFailures++;
                Console.WriteLine($"[KeepAlive] 探测相机失败, 错误: 0x{err:X}, 连续失败 {_keepAliveFailures}/{KEEP_ALIVE_MAX_FAILURES}");
            }
            catch (Exception ex)
            {
                _keepAliveFailures++;
                Console.WriteLine($"[KeepAlive] 探测异常: {ex.Message}, 连续失败 {_keepAliveFailures}/{KEEP_ALIVE_MAX_FAILURES}");
            }

            if (_keepAliveFailures >= KEEP_ALIVE_MAX_FAILURES)
            {
                Console.WriteLine("[KeepAlive] 判定相机失联, 正在自动重新连接 (无需重启相机)...");
                CleanupCamera();
                Thread.Sleep(1000);
                if (InitializeCamera())
                {
                    Console.WriteLine("[KeepAlive] 相机自动重连成功!");
                    _keepAliveFailures = 0;
                }
                else
                {
                    Console.WriteLine("[KeepAlive] 自动重连失败, 将在下次保活周期重试");
                }
            }
        }

        static string FastCapture(string args)
        {
            if (_controller == null)
            {
                return "{\"success\":false,\"error\":\"Camera not initialized\"}";
            }

            _downloadEvent.Reset();
            uint err = _controller.TakePicture();

            if (err != EDSDK.EDS_ERR_OK)
            {
                Console.WriteLine($"[Server] Fast capture failed. Error: 0x{err:X}");
                return "{\"success\":false,\"error\":\"Failed to take picture. Error: 0x" + err.ToString("X") + "\"}";
            }

            Console.WriteLine("[Server] Fast capture: waiting for download (max 15 seconds)...");
            int waitMs = 0;
            bool received = false;
            while (waitMs < 15000)
            {
                ProcessWindowsMessages();
                if (_downloadEvent.WaitOne(100))
                {
                    received = true;
                    break;
                }
                waitMs += 100;
            }

            if (received)
            {
                Interlocked.Increment(ref _downloadCount);
                Console.WriteLine("[Server] Fast capture completed!");
                return "{\"success\":true,\"download_count\":" + _downloadCount + "}";
            }
            else
            {
                Console.WriteLine("[Server] Fast capture timeout, trying manual download...");
                uint dlErr = _controller.DownloadLatestImage(_downloadPath);
                if (dlErr == EDSDK.EDS_ERR_OK)
                {
                    Interlocked.Increment(ref _downloadCount);
                    return "{\"success\":true,\"download_count\":" + _downloadCount + "}";
                }
                else
                {
                    return "{\"success\":false,\"error\":\"Download failed. Error: 0x" + dlErr.ToString("X") + "\"}";
                }
            }
        }

        static string SetCameraParam(string args)
        {
            // 曝光参数不支持远程设置(EOS R100 实测无法通过SDK修改), 请在相机机身上手动设置
            return "{\"success\":false,\"error\":\"set_camera_param is not supported\"}";
        }

        static string GetCameraParam(string args)
        {
            if (_controller == null)
            {
                return "{\"success\":false,\"error\":\"Camera not initialized\"}";
            }

            try
            {
                string param = args.Trim().ToLower();

                switch (param)
                {
                    case "batterylevel":
                        uint battery = _controller.GetBatteryLevel();
                        return "{\"success\":true,\"battery_level\":" + battery + "}";
                    case "availableshots":
                        uint shots = _controller.GetAvailableShots();
                        return "{\"success\":true,\"available_shots\":" + shots + "}";
                    case "all":
                        uint bat = _controller.GetBatteryLevel();
                        uint sh = _controller.GetAvailableShots();
                        return "{\"success\":true,\"battery_level\":" + bat + ",\"available_shots\":" + sh + "}";
                    default:
                        return "{\"success\":false,\"error\":\"Unknown parameter: " + param + "\"}";
                }
            }
            catch (Exception ex)
            {
                return "{\"success\":false,\"error\":\"" + ex.Message.Replace("\"", "\\\"") + "\"}";
            }
        }

        static void CleanupCamera()
        {
            Console.WriteLine("[Server] Cleaning up camera resources...");
            
            if (_controller != null)
            {
                try
                {
                    _controller.CloseSession();
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[Server] Error closing session: {ex.Message}");
                }
                _controller = null;
            }

            if (_manager != null)
            {
                try
                {
                    _manager.Terminate();
                    _manager.Dispose();
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"[Server] Error terminating SDK: {ex.Message}");
                }
                _manager = null;
            }
        }

        [DllImport("user32.dll")]
        private static extern bool PeekMessage(out MSG lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax, uint wRemoveMsg);

        [DllImport("user32.dll")]
        private static extern bool TranslateMessage(ref MSG lpMsg);

        [DllImport("user32.dll")]
        private static extern IntPtr DispatchMessage(ref MSG lpMsg);

        [StructLayout(LayoutKind.Sequential)]
        private struct MSG
        {
            public IntPtr hwnd;
            public uint message;
            public IntPtr wParam;
            public IntPtr lParam;
            public uint time;
            public int pt_x;
            public int pt_y;
        }

        private const uint PM_REMOVE = 0x0001;

        private static void ProcessWindowsMessages()
        {
            MSG msg;
            while (PeekMessage(out msg, IntPtr.Zero, 0, 0, PM_REMOVE))
            {
                TranslateMessage(ref msg);
                DispatchMessage(ref msg);
            }
        }
    }
}