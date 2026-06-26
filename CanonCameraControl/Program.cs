using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading;

namespace CanonCamera
{
    class CameraConfig
    {
        public string downloadPath { get; set; } = @"C:\Users\dell\Downloads\CanonCameraPhotos";
        public int numberOfPhotos { get; set; } = 1;
        public int delayBetweenPhotosMs { get; set; } = 2000;
    }

    class Program
    {
        private const string CONFIG_FILE = "config.json";

        [STAThread]
        static void Main(string[] args)
        {
            Console.WriteLine("========================================");
            Console.WriteLine("Canon Camera Remote Control Program");
            Console.WriteLine("========================================");
            Console.WriteLine();

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
                    downloadPath = @"C:\Users\dell\Downloads\CanonCameraPhotos";
                    numberOfPhotos = 1;
                    delayBetweenPhotos = 2000;
                }
            }
            else
            {
                downloadPath = @"C:\Users\dell\Downloads\CanonCameraPhotos";
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
                    Console.WriteLine("Attempting full SDK restart...");
                    
                    if (manager != null)
                    {
                        manager.Terminate();
                        Thread.Sleep(2000);
                        
                        Console.WriteLine("[DEBUG] Re-initializing SDK...");
                        err = manager.Initialize();
                        if (err == EDSDK.EDS_ERR_OK)
                        {
                            Console.WriteLine("[DEBUG] SDK re-initialized successfully");
                            Thread.Sleep(3000);
                            
                            Console.WriteLine("[DEBUG] Re-searching for cameras...");
                            List<CameraModel> newCameras = manager.GetCameraList();
                            if (newCameras.Count > 0)
                            {
                                Console.WriteLine($"[DEBUG] Found {newCameras.Count} camera(s)");
                                CameraModel newCameraModel = newCameras[0];
                                Console.WriteLine($"[DEBUG] Re-acquired camera: {newCameraModel.ModelName}");
                                
                                controller = new CameraController(newCameraModel, downloadPath);
                                
                                controller.StatusChanged += (sender, status) =>
                                {
                                    Console.WriteLine($"[Status] {status}");
                                };
                                controller.ErrorOccurred += (sender, error) =>
                                {
                                    Console.WriteLine($"[Error] {error}");
                                };
                                
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
                                
                                uint setErr = manager.SetEventHandlers(newCameraModel.Camera);
                                if (setErr == EDSDK.EDS_ERR_OK)
                                {
                                    Console.WriteLine("[DEBUG] Re-trying to open session...");
                                    err = controller.OpenSession();
                                    if (err == EDSDK.EDS_ERR_OK)
                                    {
                                        Console.WriteLine("[DEBUG] Session opened after restart!");
                                    }
                                    else
                                    {
                                        Console.WriteLine($"Failed to open session after restart. Error code: 0x{err:X}");
                                        return;
                                    }
                                }
                                else
                                {
                                    Console.WriteLine($"Failed to set event handlers after restart. Error: 0x{setErr:X}");
                                    return;
                                }
                            }
                            else
                            {
                                Console.WriteLine("[DEBUG] No cameras found after restart");
                                return;
                            }
                        }
                        else
                        {
                            Console.WriteLine($"Failed to re-initialize SDK. Error: 0x{err:X}");
                            return;
                        }
                    }
                    else
                    {
                        return;
                    }
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
