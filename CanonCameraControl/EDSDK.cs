using System;
using System.Runtime.InteropServices;

namespace CanonCamera
{
    public class EDSDK
    {
        #region Error Codes
        public const uint EDS_ERR_OK = 0x00000000;
        public const uint EDS_ERR_NOT_IMPLEMENTED = 0x00000001;
        public const uint EDS_ERR_INTERNAL_ERROR = 0x00000002;
        public const uint EDS_ERR_MEM_ALLOC_FAILED = 0x00000003;
        public const uint EDS_ERR_MEM_FREE_FAILED = 0x00000004;
        public const uint EDS_ERR_NO_CAMERA_FOUND = 0x00000101;
        public const uint EDS_ERR_DEVICE_NOT_FOUND = 0x00000102;
        public const uint EDS_ERR_DEVICE_BUSY = 0x00008D01;
        public const uint EDS_ERR_DEVICE_EMERGENCY = 0x00000104;
        public const uint EDS_ERR_DEVICE_MEMORY_FULL = 0x00000105;
        public const uint EDS_ERR_DEVICE_FILE_MINIMUM = 0x00000106;
        public const uint EDS_ERR_DEVICE_POWER_OFF = 0x00000107;
        public const uint EDS_ERR_DEVICE_FILE_OR_FOLD_MINIMUM = 0x00000108;
        public const uint EDS_ERR_NO_IMAGED_IN_CARD = 0x00000109;
        public const uint EDS_ERR_CARD_MINIMUM = 0x0000010A;
        public const uint EDS_ERR_CARD_MISSING = 0x0000010B;
        public const uint EDS_ERR_CARD_MINIMUM2 = 0x0000010C;
        public const uint EDS_ERR_FILE_MINIMUM = 0x0000010D;
        public const uint EDS_ERR_CARD_WRITE_PROTECT = 0x0000010E;
        public const uint EDS_ERR_FILE_WRITE_PROTECTED = 0x0000010F;
        public const uint EDS_ERR_FILE_FORMAT_UNMATCH = 0x00000110;
        public const uint EDS_ERR_FILE_DATA_CORRUPT = 0x00000111;
        public const uint EDS_ERR_FILE_GENERATION = 0x00000112;
        public const uint EDS_ERR_FILE_UNSUPPORTED = 0x00000113;
        public const uint EDS_ERR_FILE_NOT_FOUND = 0x00000114;
        public const uint EDS_ERR_DIR_NOT_FOUND = 0x00000115;
        public const uint EDS_ERR_PROPERTIES_UNMATCH = 0x00000117;
        public const uint EDS_ERR_PROPERTIES_INVALID = 0x00000118;
        public const uint EDS_ERR_INVALID_PARAMETER = 0x00000119;
        public const uint EDS_ERR_INVALID_HANDLE = 0x0000011A;
        public const uint EDS_ERR_INVALID_POINTER = 0x0000011B;
        public const uint EDS_ERR_INVALID_INDEX = 0x0000011C;
        public const uint EDS_ERR_INVALID_LENGTH = 0x0000011D;
        public const uint EDS_ERR_INVALID_ALIGN = 0x0000011E;
        public const uint EDS_ERR_INVALID_FLAG = 0x00000120;
        public const uint EDS_ERR_INVALID_ITEMS = 0x00000121;
        public const uint EDS_ERR_INVALID_TYPE = 0x00000122;
        public const uint EDS_ERR_INVALID_PROPERTY = 0x00000123;
        #endregion

        #region Callback Delegates
        public delegate uint EdsProgressCallback(uint inPercent, IntPtr inContext, ref bool outCancel);
        public delegate uint EdsCameraAddedHandler(IntPtr inContext);
        public delegate uint EdsPropertyEventHandler(uint inEvent, uint inPropertyID, uint inParam, IntPtr inContext);
        public delegate uint EdsObjectEventHandler(uint inEvent, IntPtr inRef, IntPtr inContext);
        public delegate uint EdsStateEventHandler(uint inEvent, uint inParameter, IntPtr inContext);
        #endregion

        #region Data Types
        public enum EdsDataType : uint
        {
            Unknown = 0,
            Bool = 1,
            String = 2,
            Int8 = 3,
            UInt8 = 6,
            Int16 = 4,
            UInt16 = 7,
            Int32 = 8,
            UInt32 = 9,
            Int64 = 10,
            UInt64 = 11,
            Float = 12,
            Double = 13,
            ByteBlock = 14,
            Rational = 20,
            Point = 21,
            Rect = 22,
            Time = 23,
        }

        public enum EdsObjectEvent : uint
        {
            ObjectEvent_All = 0x00000200,
            ObjectEvent_DirItemCreated = 0x00000204,
            ObjectEvent_DirItemRemoved = 0x00000205,
            ObjectEvent_DirItemInfoChanged = 0x00000206,
            ObjectEvent_DirItemContentChanged = 0x00000207,
            ObjectEvent_DirItemRequestTransfer = 0x00000208,
            ObjectEvent_DirItemRequestTransferDT = 0x00000209,
            ObjectEvent_DirItemCancelTransferDT = 0x0000020a,
            ObjectEvent_VolumeAdded = 0x0000020c,
            ObjectEvent_VolumeRemoved = 0x0000020d,
        }

        public enum EdsPropertyEvent : uint
        {
            PropertyEvent_All = 0x00000100,
            PropertyEvent_PropertyChanged = 0x00000101,
            PropertyEvent_PropertyDescChanged = 0x00000102,
            PropertyEvent_PropertyDescExChanged = 0x00000110,
        }

        public enum EdsStateEvent : uint
        {
            StateEvent_All = 0x00000300,
            StateEvent_Shutdown = 0x00000301,
            StateEvent_JobStatusChanged = 0x00000302,
            StateEvent_WillSoonShutDown = 0x00000303,
            StateEvent_ShutDownTimerUpdate = 0x00000304,
            StateEvent_CaptureError = 0x00000305,
            StateEvent_InternalError = 0x00000306,
            StateEvent_AfResult = 0x00000309,
        }

        public enum EdsShutterButton : uint
        {
            CameraCommand_ShutterButton_Off = 0x00000000,
            CameraCommand_ShutterButton_Halfway = 0x00000001,
            CameraCommand_ShutterButton_Completely = 0x00000003,
        }

        public enum EdsSaveTo : uint
        {
            SaveTo_Camera = 0x00000001,
            SaveTo_Host = 0x00000002,
            SaveTo_Both = 0x00000003,
        }

        public enum EdsFileCreateDisposition : uint
        {
            CreateNew = 0,
            CreateAlways = 1,
            OpenExisting = 2,
            OpenAlways = 3,
            TruncateExsisting = 4,
        }

        public enum EdsAccess : uint
        {
            Read = 0,
            Write = 1,
            ReadWrite = 2,
            Error = 0xFFFFFFFF,
        }

        public enum EdsProgressOption : uint
        {
            NoReport = 0,
            Done = 1,
            Periodically = 2,
        }
        #endregion

        #region Property IDs
        public const uint PropID_Unknown = 0x0000ffff;
        public const uint PropID_ProductName = 0x00000002;
        public const uint PropID_BodyIDEx = 0x00000015;
        public const uint PropID_OwnerName = 0x00000004;
        public const uint PropID_MakerName = 0x00000005;
        public const uint PropID_DateTime = 0x00000006;
        public const uint PropID_FirmwareVersion = 0x00000007;
        public const uint PropID_BatteryLevel = 0x00000008;
        public const uint PropID_SaveTo = 0x0000000b;
        public const uint PropID_CurrentStorage = 0x0000000c;
        public const uint PropID_ImageQuality = 0x00000100;
        public const uint PropID_FixedMovie = 0x01000422;
        public const uint PropID_WhiteBalance = 0x00000106;
        public const uint PropID_ColorTemperature = 0x00000107;
        public const uint PropID_WhiteBalanceShift = 0x00000108;
        public const uint PropID_ColorSpace = 0x0000010d;
        public const uint PropID_PictureStyle = 0x00000114;
        public const uint PropID_AEMode = 0x00000400;
        public const uint PropID_AEModeSelect = 0x00000404;
        public const uint PropID_DriveMode = 0x00000401;
        public const uint PropID_ISOSpeed = 0x00000402;
        public const uint PropID_MeteringMode = 0x00000403;
        public const uint PropID_AFMode = 0x00000404;
        public const uint PropID_Av = 0x00000405;
        public const uint PropID_Tv = 0x00000406;
        public const uint PropID_ExposureCompensation = 0x00000407;
        public const uint PropID_FocalLength = 0x00000409;
        public const uint PropID_AvailableShots = 0x0000040a;
        public const uint PropID_Bracket = 0x0000040b;
        public const uint PropID_WhiteBalanceBracket = 0x0000040c;
        public const uint PropID_LensName = 0x0000040d;
        public const uint PropID_AEBracket = 0x0000040e;
        public const uint PropID_FEBracket = 0x0000040f;
        public const uint PropID_ISOBracket = 0x00000410;
        public const uint PropID_DC_Zoom = 0x00000507;
        public const uint PropID_DC_Strobe = 0x00000414;
        public const uint PropID_MovieParam = 0x00000510;
        public const uint PropID_MovieHFRSetting = 0x00000511;
        public const uint PropID_Aspect = 0x00000520;
        #endregion

        #region Camera Commands
        public const uint CameraCommand_TakePicture = 0x00000000;
        public const uint CameraCommand_ExtendShutDownTimer = 0x00000001;
        public const uint CameraCommand_BulbStart = 0x00000002;
        public const uint CameraCommand_BulbEnd = 0x00000003;
        public const uint CameraCommand_PressShutterButton = 0x00000004;
        public const uint CameraCommand_RequestRollPitchLevel = 0x00000501;
        #endregion

        #region SDK Functions
        [DllImport("EDSDK.dll")]
        public static extern uint EdsInitializeSDK();

        [DllImport("EDSDK.dll")]
        public static extern uint EdsTerminateSDK();

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetCameraList(out IntPtr outCameraList);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetChildCount(IntPtr inRef, out int outCount);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetChildAtIndex(IntPtr inCameraList, int inIndex, out IntPtr outCamera);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetDeviceInfo(IntPtr inCamera, out EdsDeviceInfo outDeviceInfo);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsRelease(IntPtr inRef);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsOpenSession(IntPtr inCamera);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsCloseSession(IntPtr inCamera);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSetPropertyData(IntPtr inRef, uint inPropertyID,
             int inParam, int inPropertySize, IntPtr inPropertyData);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetPropertyData(IntPtr inRef, uint inPropertyID,
             int inParam, int inPropertySize, IntPtr outPropertyData);

        public static uint EdsGetPropertyData(IntPtr inRef, uint inPropertyID, int inParam, out uint outPropertyData)
        {
            int size = Marshal.SizeOf(typeof(uint));
            IntPtr ptr = Marshal.AllocHGlobal(size);
            uint err = EdsGetPropertyData(inRef, inPropertyID, inParam, size, ptr);

            if (err == EDS_ERR_OK)
            {
                outPropertyData = (uint)Marshal.PtrToStructure(ptr, typeof(uint));
            }
            else
            {
                outPropertyData = 0;
            }
            Marshal.FreeHGlobal(ptr);
            return err;
        }

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSendCommand(IntPtr inCamera, uint inCommand, int inParam);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSendStatusCommand(IntPtr inCamera, uint inStatusCommand, uint inParam);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSetCapacity(IntPtr inCamera, EdsCapacity inCapacity);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetDirectoryItemInfo(IntPtr inDirItem, out EdsDirectoryItemInfo outDirItemInfo);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsDownload(IntPtr inDirItem, uint inDownloadSize, IntPtr inStream);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsDownloadComplete(IntPtr inDirItem);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsCreateFileStream([MarshalAs(UnmanagedType.LPStr)] string inFileName, EdsFileCreateDisposition inCreateDisposition, EdsAccess inAccess, out IntPtr outStream);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsCreateMemoryStream(uint inBufferSize, out IntPtr outStream);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetPointer(IntPtr inStream, out IntPtr outPointer);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetLength(IntPtr inStream, out uint outLength);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSetProgressCallback(IntPtr inStream, EdsProgressCallback inProgressFunc, EdsProgressOption inProgressOption, IntPtr inContext);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSetCameraAddedHandler(EdsCameraAddedHandler inHandler, IntPtr inContext);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSetObjectEventHandler(IntPtr inCamera, uint inEvent, EdsObjectEventHandler inHandler, IntPtr inContext);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSetPropertyEventHandler(IntPtr inCamera, uint inEvent, EdsPropertyEventHandler inHandler, IntPtr inContext);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsSetCameraStateEventHandler(IntPtr inCamera, uint inEvent, EdsStateEventHandler inHandler, IntPtr inContext);

        [DllImport("EDSDK.dll")]
        public static extern uint EdsGetVolumeInfo(IntPtr inVolume, out EdsVolumeInfo outVolumeInfo);
        #endregion

        #region Data Structures
        public const int EDS_MAX_NAME = 256;

        [StructLayout(LayoutKind.Sequential)]
        public struct EdsDeviceInfo
        {
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = EDS_MAX_NAME)]
            public string szPortName;

            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = EDS_MAX_NAME)]
            public string szDeviceDescription;

            public uint DeviceSubType;

            public uint reserved;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct EdsDirectoryItemInfo
        {
            public UInt64 Size;
            public int isFolder;
            public uint GroupID;
            public uint Option;

            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = EDS_MAX_NAME)]
            public string szFileName;

            public uint format;
            public uint dateTime;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct EdsCapacity
        {
            public int NumberOfFreeClusters;
            public int BytesPerSector;
            public int Reset;
        }

        [StructLayout(LayoutKind.Sequential)]
        public struct EdsVolumeInfo
        {
            public uint StorageType;
            public uint Access;
            public ulong MaxCapacity;
            public ulong FreeSpaceInBytes;

            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = EDS_MAX_NAME)]
            public string szVolumeLabel;
        }
        #endregion
    }
}
