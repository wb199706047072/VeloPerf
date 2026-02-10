import asyncio
import time
import os
from typing import Dict, Any, Callable, List
from loguru import logger
from tidevice import Device
from tidevice._perf import Performance, DataType

class IOSCollector:
    def __init__(self, udid: str):
        self.udid = udid
        self.device = Device(udid)
        self.perf = None
        self.running = False
        self.target_bundle_id = None
        self._callback: Callable[[Dict[str, Any]], None] = None
        
        # 缓存最新的数据
        self._current_data = {
            "cpu": 0.0,
            "memory": 0.0,
            "fps": 0,
            "gpu": 0.0
        }
        
        # Prepare screenshot dir
        self.screenshot_dir = f"static/screenshots/{self.udid}"
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def set_callback(self, callback):
        self._callback = callback

    @staticmethod
    def get_installed_apps(udid: str) -> List[Dict[str, str]]:
        try:
            d = Device(udid)
            apps = []
            # tidevice app_list returns objects with bundle_id, name, type
            for app in d.app_list():
                if app.type == "User":
                    apps.append({"package": app.bundle_id, "name": app.name})
            return sorted(apps, key=lambda x: x['name'])
        except Exception as e:
            logger.error(f"Failed to list iOS apps: {e}")
            return []

    def set_target(self, bundle_id: str):
        self.target_bundle_id = bundle_id

    async def start(self):
        if not self.target_bundle_id:
            logger.error("iOS collection requires a target bundle ID")
            return

        self.running = True
        logger.info(f"Started iOS collection for {self.udid} on {self.target_bundle_id}")

        # tidevice Perf 是基于 callback 的，且运行在独立线程中
        # 我们需要适配它的 callback 到我们的 async loop
        try:
            self.perf = Performance(self.device, [DataType.CPU, DataType.MEMORY, DataType.FPS, DataType.GPU])
            
            def _tidevice_callback(datatype, value):
                # 更新缓存
                if datatype.name == "CPU":
                    self._current_data["cpu"] = value.get("value", 0)
                elif datatype.name == "MEMORY":
                    self._current_data["memory"] = value.get("value", 0)
                elif datatype.name == "FPS":
                    self._current_data["fps"] = value.get("value", 0)
                elif datatype.name == "GPU":
                    self._current_data["gpu"] = value.get("value", 0)
                    
            # 启动 tidevice 采集
            # start 是非阻塞的吗？通常 start(callback=...) 会启动线程
            # 经查 tidevice 源码，perf.start() 是非阻塞的，它会启动线程
            self.perf.start(self.target_bundle_id, callback=_tidevice_callback)
            
            # 启动一个定时器，定期将 _current_data 推送给前端
            asyncio.create_task(self._report_loop())
            # 启动截图循环
            asyncio.create_task(self._screenshot_loop())
            
        except Exception as e:
            logger.error(f"Failed to start iOS collection: {e}")
            self.running = False

    def stop(self):
        self.running = False
        if self.perf:
            try:
                self.perf.stop()
            except Exception:
                pass
        logger.info(f"Stopped iOS collection for {self.udid}")

    async def _report_loop(self):
        while self.running:
            try:
                timestamp = int(time.time() * 1000)
                
                # Get battery info (polling)
                battery_info = {"level": 0, "temp": 0}
                try:
                    # com.apple.mobile.battery
                    # Keys: BatteryCurrentCapacity, BatteryIsCharging, ExternalChargeCapable, BatteryTemperature (not always available)
                    # Note: get_value is blocking, might slow down loop?
                    # But loop is 1s, should be fine.
                    bat_data = self.device.get_value(domain="com.apple.mobile.battery")
                    if bat_data:
                        level = bat_data.get("BatteryCurrentCapacity", 0)
                        # BatteryTemperature is usually not exposed in standard battery domain on non-jailbroken, 
                        # but sometimes "Temperature" is in IOPower?
                        # Let's try basic level first.
                        battery_info["level"] = level
                except Exception:
                    pass

                data = {
                    "timestamp": timestamp,
                    "package": self.target_bundle_id,
                    "cpu": self._current_data["cpu"],
                    "memory": self._current_data["memory"],
                    "fps": self._current_data["fps"],
                    "gpu": self._current_data["gpu"],
                    "jank": 0,
                    "stutter": 0,
                    "battery": battery_info,
                    "network": {"rx": 0, "tx": 0}
                }
                
                if self._callback:
                    self._callback(data)
                    
            except Exception as e:
                logger.error(f"Report loop error: {e}")
            
            await asyncio.sleep(1)

    async def _screenshot_loop(self):
        while self.running:
            try:
                loop = asyncio.get_event_loop()
                timestamp = int(time.time() * 1000)
                filename = f"{timestamp}.jpg"
                filepath = f"{self.screenshot_dir}/{filename}"
                
                # tidevice screenshot
                await loop.run_in_executor(None, self._take_screenshot, filepath)
                
                if self._callback:
                    self._callback({
                        "type": "screenshot",
                        "timestamp": timestamp,
                        "url": f"/screenshots/{self.udid}/{filename}"
                    })
            except Exception as e:
                logger.error(f"iOS Screenshot loop error: {e}")
            
            await asyncio.sleep(2)

    def _take_screenshot(self, path: str):
        try:
            # tidevice screenshot saves to file
            self.device.screenshot(path)
        except Exception as e:
            logger.error(f"iOS Take screenshot failed: {e}")

    @staticmethod
    def get_devices():
        try:
            from tidevice import Usbmux
            return Usbmux().device_list()
        except Exception:
            return []
