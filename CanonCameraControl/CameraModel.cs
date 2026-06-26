using System;
using System.Collections.Generic;

namespace CanonCamera
{
    public class CameraModel
    {
        public IntPtr Camera { get; set; }
        public string ModelName { get; set; }
        public uint AvailableShots { get; set; }
        public uint BatteryLevel { get; set; }
        public bool IsConnected { get; set; }
        public bool IsSessionOpen { get; set; }
        public uint DeviceSubType { get; set; }
        public string PortName { get; set; }

        public CameraModel(IntPtr camera)
        {
            this.Camera = camera;
            this.ModelName = "Unknown";
            this.AvailableShots = 0;
            this.BatteryLevel = 0;
            this.IsConnected = false;
            this.IsSessionOpen = false;
            this.DeviceSubType = 0;
            this.PortName = "";
        }

        public void SetProperty(uint propertyID, uint value)
        {
            switch (propertyID)
            {
                case EDSDK.PropID_ProductName:
                    break;
                case EDSDK.PropID_AvailableShots:
                    this.AvailableShots = value;
                    break;
                case EDSDK.PropID_BatteryLevel:
                    this.BatteryLevel = value;
                    break;
            }
        }
    }

    public class DownloadEventArgs : EventArgs
    {
        public string FileName { get; set; }
        public string SavePath { get; set; }
        public uint FileSize { get; set; }
        public bool Success { get; set; }
        public string ErrorMessage { get; set; }

        public DownloadEventArgs(string fileName, string savePath, uint fileSize)
        {
            this.FileName = fileName;
            this.SavePath = savePath;
            this.FileSize = fileSize;
            this.Success = true;
        }

        public DownloadEventArgs(string errorMessage)
        {
            this.Success = false;
            this.ErrorMessage = errorMessage;
        }
    }

    public class CameraEventHandler
    {
        private CameraController _controller;

        public event EventHandler<DownloadEventArgs> ImageDownloaded;
        public event EventHandler<string> StatusChanged;
        public event EventHandler<string> ErrorOccurred;

        public CameraEventHandler(CameraController controller)
        {
            _controller = controller;
        }

        public void OnImageDownloaded(DownloadEventArgs e)
        {
            ImageDownloaded?.Invoke(this, e);
        }

        public void OnStatusChanged(string status)
        {
            StatusChanged?.Invoke(this, status);
        }

        public void OnErrorOccurred(string error)
        {
            ErrorOccurred?.Invoke(this, error);
        }
    }
}
