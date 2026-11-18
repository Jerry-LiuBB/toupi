using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

namespace CanonCamera
{
    public class CameraManager : IDisposable
    {
        private IntPtr _cameraList;
        private List<CameraModel> _cameras;
        private bool _isDisposed;
        private GCHandle _thisHandle;
        private IntPtr _thisPtr;

        private EDSDK.EdsObjectEventHandler _objectEventHandler;
        private EDSDK.EdsPropertyEventHandler _propertyEventHandler;
        private EDSDK.EdsStateEventHandler _stateEventHandler;

        public event EventHandler<IntPtr> ObjectEventOccurred;
        public event EventHandler<uint> PropertyEventOccurred;
        public event EventHandler<uint> StateEventOccurred;

        public CameraManager()
        {
            _cameras = new List<CameraModel>();
            _isDisposed = false;
        }

        public uint Initialize()
        {
            Console.WriteLine("[DEBUG] Calling EdsInitializeSDK...");
            uint err = EDSDK.EdsInitializeSDK();
            Console.WriteLine($"[DEBUG] EdsInitializeSDK returned: 0x{err:X}");
            if (err != EDSDK.EDS_ERR_OK)
            {
                return err;
            }

            Console.WriteLine("[DEBUG] Calling EdsGetCameraList...");
            err = EDSDK.EdsGetCameraList(out _cameraList);
            Console.WriteLine($"[DEBUG] EdsGetCameraList returned: 0x{err:X}, handle: {_cameraList}");
            return err;
        }

        public uint Terminate()
        {
            uint err = EDSDK.EDS_ERR_OK;

            if (_cameraList != IntPtr.Zero)
            {
                Console.WriteLine("[DEBUG] Releasing camera list...");
                err = EDSDK.EdsRelease(_cameraList);
                _cameraList = IntPtr.Zero;
            }

            Console.WriteLine("[DEBUG] Calling EdsTerminateSDK...");
            uint termErr = EDSDK.EdsTerminateSDK();
            if (err == EDSDK.EDS_ERR_OK)
            {
                err = termErr;
            }

            return err;
        }

        public List<CameraModel> GetCameraList()
        {
            _cameras.Clear();

            Console.WriteLine($"[DEBUG] GetCameraList: _cameraList = {_cameraList}");

            if (_cameraList == IntPtr.Zero)
            {
                Console.WriteLine("[DEBUG] GetCameraList: cameraList is null, returning empty");
                return _cameras;
            }

            int count = 0;
            Console.WriteLine("[DEBUG] Calling EdsGetChildCount...");
            uint err = EDSDK.EdsGetChildCount(_cameraList, out count);
            Console.WriteLine($"[DEBUG] EdsGetChildCount returned: 0x{err:X}, count = {count}");

            if (err != EDSDK.EDS_ERR_OK)
            {
                Console.WriteLine($"[DEBUG] GetChildCount failed with error: 0x{err:X}");
                return _cameras;
            }

            if (count == 0)
            {
                Console.WriteLine("[DEBUG] No cameras found (count = 0)");
                return _cameras;
            }

            Console.WriteLine($"[DEBUG] Found {count} camera(s), enumerating...");

            for (int i = 0; i < count; i++)
            {
                IntPtr camera = IntPtr.Zero;
                err = EDSDK.EdsGetChildAtIndex(_cameraList, i, out camera);
                Console.WriteLine($"[DEBUG] EdsGetChildAtIndex({i}) returned: 0x{err:X}, camera = {camera}");

                if (err == EDSDK.EDS_ERR_OK && camera != IntPtr.Zero)
                {
                    try
                    {
                        Console.WriteLine($"[DEBUG] About to call EdsGetDeviceInfo for camera {camera}...");
                        EDSDK.EdsDeviceInfo deviceInfo = new EDSDK.EdsDeviceInfo();
                        err = EDSDK.EdsGetDeviceInfo(camera, out deviceInfo);
                        Console.WriteLine($"[DEBUG] EdsGetDeviceInfo returned: 0x{err:X}, name = {deviceInfo.szDeviceDescription}");
                        Console.WriteLine($"[DEBUG] DeviceSubType: 0x{deviceInfo.DeviceSubType:X}, PortName: {deviceInfo.szPortName}");
                        Console.WriteLine($"[DEBUG] Reserved: 0x{deviceInfo.reserved:X}");

                        if (err == EDSDK.EDS_ERR_OK)
                        {
                            CameraModel model = new CameraModel(camera);
                            model.ModelName = deviceInfo.szDeviceDescription;
                            model.DeviceSubType = deviceInfo.DeviceSubType;
                            model.PortName = deviceInfo.szPortName;
                            model.IsConnected = true;
                            _cameras.Add(model);
                            Console.WriteLine($"[DEBUG] Added camera: {model.ModelName}, SubType: 0x{deviceInfo.DeviceSubType:X}");
                        }
                    }
                    catch (Exception ex)
                    {
                        Console.WriteLine($"[ERROR] Exception in EdsGetDeviceInfo: {ex.GetType().Name}: {ex.Message}");
                        Console.WriteLine($"[ERROR] Stack trace: {ex.StackTrace}");
                    }
                }
            }

            Console.WriteLine($"[DEBUG] GetCameraList returning {_cameras.Count} camera(s)");
            return _cameras;
        }

        public uint SetEventHandlers(IntPtr camera)
        {
            _thisHandle = GCHandle.Alloc(this);
            _thisPtr = GCHandle.ToIntPtr(_thisHandle);

            _objectEventHandler = HandleObjectEvent;
            _propertyEventHandler = HandlePropertyEvent;
            _stateEventHandler = HandleStateEvent;

            uint err = EDSDK.EdsSetObjectEventHandler(
                camera,
                (uint)EDSDK.EdsObjectEvent.ObjectEvent_All,
                _objectEventHandler,
                _thisPtr
            );

            Console.WriteLine($"[DEBUG] EdsSetObjectEventHandler(ObjectEvent_All) returned: 0x{err:X}");

            if (err != EDSDK.EDS_ERR_OK)
            {
                Console.WriteLine($"[ERROR] Failed to set object event handler. Error: 0x{err:X}");
                return err;
            }

            err = EDSDK.EdsSetPropertyEventHandler(
                camera,
                (uint)EDSDK.EdsPropertyEvent.PropertyEvent_All,
                _propertyEventHandler,
                _thisPtr
            );

            Console.WriteLine($"[DEBUG] EdsSetPropertyEventHandler(PropertyEvent_All) returned: 0x{err:X}");

            if (err != EDSDK.EDS_ERR_OK)
            {
                Console.WriteLine($"[ERROR] Failed to set property event handler. Error: 0x{err:X}");
                return err;
            }

            err = EDSDK.EdsSetCameraStateEventHandler(
                camera,
                (uint)EDSDK.EdsStateEvent.StateEvent_All,
                _stateEventHandler,
                _thisPtr
            );

            Console.WriteLine($"[DEBUG] EdsSetCameraStateEventHandler(StateEvent_All) returned: 0x{err:X}");

            if (err != EDSDK.EDS_ERR_OK)
            {
                Console.WriteLine($"[ERROR] Failed to set state event handler. Error: 0x{err:X}");
            }

            return err;
        }

        private uint HandleObjectEvent(uint inEvent, IntPtr inRef, IntPtr inContext)
        {
            Console.WriteLine($"[DEBUG] ObjectEvent received: 0x{inEvent:X}, inRef: {inRef}");

            switch (inEvent)
            {
                case (uint)EDSDK.EdsObjectEvent.ObjectEvent_DirItemRequestTransfer:
                    Console.WriteLine("[DEBUG] DirItemRequestTransfer - image ready to download");
                    ObjectEventOccurred?.Invoke(this, inRef);
                    break;

                case (uint)EDSDK.EdsObjectEvent.ObjectEvent_DirItemCreated:
                    Console.WriteLine($"[DEBUG] DirItemCreated - new item on camera");
                    break;

                case (uint)EDSDK.EdsObjectEvent.ObjectEvent_DirItemRemoved:
                    Console.WriteLine("[DEBUG] DirItemRemoved");
                    if (inRef != IntPtr.Zero) EDSDK.EdsRelease(inRef);
                    break;

                case (uint)EDSDK.EdsObjectEvent.ObjectEvent_DirItemInfoChanged:
                    Console.WriteLine("[DEBUG] DirItemInfoChanged");
                    if (inRef != IntPtr.Zero) EDSDK.EdsRelease(inRef);
                    break;

                case (uint)EDSDK.EdsObjectEvent.ObjectEvent_DirItemContentChanged:
                    Console.WriteLine("[DEBUG] DirItemContentChanged");
                    if (inRef != IntPtr.Zero) EDSDK.EdsRelease(inRef);
                    break;

                case (uint)EDSDK.EdsObjectEvent.ObjectEvent_VolumeAdded:
                    Console.WriteLine("[DEBUG] VolumeAdded");
                    if (inRef != IntPtr.Zero) EDSDK.EdsRelease(inRef);
                    break;

                case (uint)EDSDK.EdsObjectEvent.ObjectEvent_VolumeRemoved:
                    Console.WriteLine("[DEBUG] VolumeRemoved");
                    if (inRef != IntPtr.Zero) EDSDK.EdsRelease(inRef);
                    break;

                default:
                    Console.WriteLine($"[DEBUG] Unknown ObjectEvent: 0x{inEvent:X}");
                    if (inRef != IntPtr.Zero) EDSDK.EdsRelease(inRef);
                    break;
            }

            return EDSDK.EDS_ERR_OK;
        }

        private uint HandlePropertyEvent(uint inEvent, uint inPropertyID, uint inParam, IntPtr inContext)
        {
            Console.WriteLine($"[DEBUG] PropertyEvent: 0x{inEvent:X}, propertyID: 0x{inPropertyID:X}");
            PropertyEventOccurred?.Invoke(this, inPropertyID);
            return EDSDK.EDS_ERR_OK;
        }

        private uint HandleStateEvent(uint inEvent, uint inParameter, IntPtr inContext)
        {
            Console.WriteLine($"[DEBUG] StateEvent: 0x{inEvent:X}, parameter: {inParameter}");
            if (inEvent == (uint)EDSDK.EdsStateEvent.StateEvent_Shutdown)
            {
                Console.WriteLine("[DEBUG] Camera shutdown event received");
                StateEventOccurred?.Invoke(this, inEvent);
            }
            return EDSDK.EDS_ERR_OK;
        }

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (!_isDisposed)
            {
                if (_thisHandle.IsAllocated)
                {
                    _thisHandle.Free();
                }
                _isDisposed = true;
            }
        }

        ~CameraManager()
        {
            Dispose(false);
        }
    }
}
