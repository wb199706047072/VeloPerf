import asyncio
import time
import os
import re
from typing import Dict, Any, Callable, List
from loguru import logger
from adbutils import adb
from PIL import Image

class AndroidCollector:
    def __init__(self, serial: str):
        self.serial = serial
        self.device = adb.device(serial=serial)
        self.running = False
        self.target_package = None
        self._callback: Callable[[Dict[str, Any]], None] = None
        self._last_gpu_data = None
        self._last_fps_time = 0
        self._last_present_time = 0
        self._layer_name = None
        self.current_pids = set()
        
        # Prepare screenshot dir
        self.screenshot_dir = f"static/screenshots/{self.serial}"
        os.makedirs(self.screenshot_dir, exist_ok=True)

    def set_callback(self, callback):
        self._callback = callback

    @staticmethod
    def get_installed_apps(serial: str) -> List[Dict[str, str]]:
        try:
            d = adb.device(serial=serial)
            # List 3rd party packages
            output = d.shell("pm list packages -3")
            apps = []
            if output:
                for line in output.splitlines():
                    if line.startswith("package:"):
                        pkg = line.replace("package:", "").strip()
                        apps.append({"package": pkg, "name": pkg})
            return sorted(apps, key=lambda x: x['package'])
        except Exception as e:
            logger.error(f"Failed to list Android apps: {e}")
            return []

    def set_target(self, package_name: str):
        self.target_package = package_name

    async def start(self):
        self.running = True
        logger.info(f"Started collection for {self.serial}")
        
        # 启动采集循环
        asyncio.create_task(self._collect_loop())
        # 启动截图循环
        asyncio.create_task(self._screenshot_loop())
        # 启动日志采集循环
        asyncio.create_task(self._logcat_loop())

    def stop(self):
        self.running = False
        logger.info(f"Stopped collection for {self.serial}")

    async def _collect_loop(self):
        fail_count = 0
        while self.running:
            try:
                # Check if device is still connected
                if fail_count > 3:
                     # Try to reconnect
                     try:
                         logger.info(f"Attempting to reconnect to {self.serial}...")
                         self.device = adb.device(serial=self.serial)
                         # Check if alive
                         self.device.shell("ls")
                         fail_count = 0
                         logger.info(f"Reconnected to {self.serial}")
                     except Exception:
                         await asyncio.sleep(2)
                         continue

                data = self._collect_once()
                
                # Debug log to verify data
                logger.info(f"Sending data: {data}")
                
                if self._callback:
                    self._callback(data)
                
                fail_count = 0 # Reset on success (assuming no exception raised inside)
                
            except Exception as e:
                fail_count += 1
                logger.error(f"Collection error (count={fail_count}): {e}")
                if "not found" in str(e) or "offline" in str(e):
                    # Force reconnect next time
                    fail_count = 10 
            
            await asyncio.sleep(1)  # 1秒采集一次

    async def _screenshot_loop(self):
        """
        Periodically take screenshots (e.g. every 2 seconds)
        Runs in a separate loop to avoid blocking metrics.
        """
        while self.running:
            try:
                loop = asyncio.get_event_loop()
                timestamp = int(time.time() * 1000)
                filename = f"{timestamp}.jpg"
                filepath = f"{self.screenshot_dir}/{filename}"
                
                # Run blocking screenshot in executor
                await loop.run_in_executor(None, self._take_screenshot, filepath)
                
                if self._callback:
                    self._callback({
                        "type": "screenshot",
                        "timestamp": timestamp,
                        "url": f"/screenshots/{self.serial}/{filename}"
                    })
            except Exception as e:
                logger.error(f"Screenshot loop error: {e}")
            
            await asyncio.sleep(2) # 2秒一次，避免性能影响

    async def _logcat_loop(self):
        """
        Collects logs (Crash, ANR) from logcat.
        Filters for *:E to capture errors and crashes.
        """
        process = None
        try:
            # Clear logcat buffer (ignore errors if fails)
            try:
                self.device.shell("logcat -c")
            except Exception:
                pass

            # Use asyncio subprocess to read stream
            # adb logcat -v threadtime *:V
            process = await asyncio.create_subprocess_exec(
                "adb", "-s", self.serial, "logcat", "-v", "threadtime", "*:V",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            logger.info(f"Logcat monitoring started for {self.serial}")

            while self.running:
                if process.stdout.at_eof():
                    break
                    
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                    
                line = line_bytes.decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                
                # Parse log level
                level = "info" # Default
                parts = line.split()
                if len(parts) >= 5:
                    # threadtime format: Date Time PID TID Level Tag...
                    # Example: 02-09 14:54:50.447 18791 19854 E [PreloadLog]: ...
                    lvl_char = parts[4]
                    if lvl_char == 'E': level = "error"
                    elif lvl_char == 'W': level = "warn"
                    elif lvl_char == 'D': level = "debug"
                    elif lvl_char == 'I': level = "info"
                    elif lvl_char == 'V': level = "verbose"
                
                # Check for crash keywords
                is_crash = "FATAL EXCEPTION" in line or "ANR in" in line or "AndroidRuntime" in line
                
                # --- Filter Logic Start ---
                # User request: "Only print test program's error logs and crash logs"
                
                # 1. Level Filter: Must be Error or Crash
                if level != "error" and not is_crash:
                    continue

                # 2. PID Filter: Must belong to target package
                if self.target_package:
                    log_pid = parts[2] if len(parts) >= 3 and parts[2].isdigit() else None
                    
                    if self.current_pids:
                        # Case A: We have known PIDs -> Filter by PID
                        if log_pid and log_pid not in self.current_pids:
                            # Allow crashes that mention the package name explicitly
                            if is_crash and self.target_package in line:
                                pass
                            else:
                                continue
                    else:
                        # Case B: No PIDs yet (startup or detection failed) -> Strict text filter
                        # Only allow logs that contain the package name to avoid system noise
                        if self.target_package not in line:
                            continue
                # --- Filter Logic End ---
                
                timestamp = int(time.time() * 1000)
                
                if self._callback:
                    self._callback({
                        "type": "log",
                        "timestamp": timestamp,
                        "level": level,
                        "message": line,
                        "is_crash": is_crash
                    })
                    
        except Exception as e:
            logger.error(f"Logcat loop error: {e}")
        finally:
            if process:
                try:
                    process.terminate()
                    await process.wait()
                except Exception:
                    pass

    def _take_screenshot(self, path: str):
        try:
            # adbutils screenshot returns PIL Image
            img = self.device.screenshot()
            if img:
                img = img.convert("RGB")
                img.save(path, "JPEG", quality=40) # Compress heavily for speed/size
        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            logger.error(f"Take screenshot failed: {e}")

    def _collect_once(self) -> Dict[str, Any]:
        timestamp = int(time.time() * 1000)
        
        # 1. 获取当前顶层应用 (如果未指定)
        if not self.target_package:
            self.target_package = self._get_top_package()

        cpu_usage = 0.0
        mem_usage = 0
        fps = 0
        jank = 0
        stutter = 0.0
        gpu_usage = 0.0
        battery_info = {"level": 0, "voltage": 0, "temp": 0.0, "current": 0}
        network_info = {"rx": 0, "tx": 0}
        
        if self.target_package:
            # CPU
            cpu_usage = self._get_cpu_usage(self.target_package)
            # Memory
            mem_data = self._get_memory_usage(self.target_package)
            mem_usage = mem_data.get("total", 0.0)
            
            # FPS & Jank
            fps_data = self._get_fps_and_jank(self.target_package)
            fps = fps_data["fps"]
            jank = fps_data["jank"]
            stutter = fps_data["stutter"]
            # GPU
            gpu_usage = self._get_gpu_usage()
            # Battery
            battery_info = self._get_battery_info()
            # Network
            network_info = self._get_network_usage(self.target_package)
            
            # Debug log
            # logger.info(f"Collected: CPU={cpu_usage:.1f}% FPS={fps} GPU={gpu_usage:.1f}%")

        return {
            "type": "monitor",
            "timestamp": timestamp,
            "package": self.target_package,
            "cpu": cpu_usage,
            "memory": mem_usage,
            "memory_detail": mem_data if self.target_package else {},
            "fps": fps,
            "jank": jank,
            "stutter": stutter,
            "gpu": gpu_usage,
            "battery": battery_info,
            "network": network_info
        }

    def _get_top_package(self):
        try:
            # 1. Try dumpsys window (More reliable on newer Androids)
            output = self.device.shell("dumpsys window | grep mCurrentFocus")
            if output:
                # Output example: mCurrentFocus=Window{... u0 com.example.app/com.example.app.MainActivity}
                # Regex to find package name
                match = re.search(r"u0\s+([a-zA-Z0-9.]+)/", output)
                if match:
                    return match.group(1)

            # 2. Fallback to dumpsys activity (Older Androids)
            output = self.device.shell("dumpsys activity activities | grep mResumedActivity")
            if output:
                parts = output.split()
                for part in parts:
                    if "/" in part and "u0" in output: # Ensure it's user 0
                         # part like com.example.app/.MainActivity
                         pkg = part.split("/")[0]
                         if "." in pkg:
                             return pkg
        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            logger.error(f"Failed to get top package: {e}")
        return None

    def _refresh_pids(self, package: str):
        try:
            # pgrep -f matches the full command line
            pids_output = self.device.shell(f"pgrep -f {package}")
            
            if not pids_output:
                self.current_pids = set()
                return
            
            self.current_pids = {p.strip() for p in pids_output.splitlines() if p.strip().isdigit()}
        except Exception:
            self.current_pids = set()

    def _get_cpu_usage(self, package: str) -> float:
        try:
            # 1. Refresh PIDs
            self._refresh_pids(package)
            
            if not self.current_pids:
                # logger.warning(f"No PIDs found for package: {package}")
                return 0.0
            
            pid_str = ",".join(self.current_pids)

            # 2. Use top -p to filter by PIDs
            cmd = f"top -b -n 1 -p {pid_str}"
            output = self.device.shell(cmd)

            if not output: return 0.0

            return _parse_cpu_from_top(output)
        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            logger.error(f"CPU collection error: {e}")
            pass
        return 0.0

    def _get_memory_usage(self, package: str) -> Dict[str, float]:
        try:
            # dumpsys meminfo returns KB
            output = self.device.shell(f"dumpsys meminfo {package}")
            
            total_pss = 0
            java_heap = 0
            native_heap = 0
            code = 0
            stack = 0
            graphics = 0
            private_other = 0
            system = 0
            
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("TOTAL") and "PSS:" not in line: # Avoid "TOTAL PSS:" header
                    # TOTAL    123456    ...
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        total_pss = int(parts[1])
                elif "Java Heap:" in line:
                    parts = line.split()
                    if len(parts) >= 3: java_heap = int(parts[2])
                elif "Native Heap:" in line:
                    parts = line.split()
                    if len(parts) >= 3: native_heap = int(parts[2])
                elif "Code:" in line:
                    parts = line.split()
                    if len(parts) >= 2: code = int(parts[1])
                elif "Stack:" in line:
                    parts = line.split()
                    if len(parts) >= 2: stack = int(parts[1])
                elif "Graphics:" in line:
                    parts = line.split()
                    if len(parts) >= 2: graphics = int(parts[1])
                elif "Private Other:" in line:
                    parts = line.split()
                    if len(parts) >= 3: private_other = int(parts[2])
                elif "System:" in line:
                    parts = line.split()
                    if len(parts) >= 2: system = int(parts[1])

            return {
                "total": round(total_pss / 1024, 1), # MB
                "java": round(java_heap / 1024, 1),
                "native": round(native_heap / 1024, 1),
                "graphics": round(graphics / 1024, 1),
                "code": round(code / 1024, 1),
                "other": round((private_other + stack + system) / 1024, 1)
            }
        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            logger.error(f"Memory collection error: {e}")
            pass
        return {}

    def _get_fps_and_jank(self, package: str) -> Dict[str, Any]:
        """
        通过 dumpsys SurfaceFlinger --latency 计算 FPS, Jank, Stutter
        自动选择最活跃的图层 (Max Last Timestamp)
        """
        result = {"fps": 0, "jank": 0, "stutter": 0.0}
        try:
            # 1. 动态确定 Layer Name (如果尚未确定或之前的 layer 失效)
            # 我们引入定期检查机制 (例如每 10 次调用或 FPS=0 时) 来重新选择 active layer
            should_scan = False
            if not self._layer_name or package not in self._layer_name:
                should_scan = True
            
            # 如果当前 layer 数据为空 (FPS=0)，也尝试重新扫描
            # 但为了避免每帧都扫描导致性能问题，可以使用计数器或时间间隔
            # 这里简化处理: 如果 _layer_name 为空才扫描，或者外部重置
            
            if should_scan:
                self._layer_name = self._find_active_layer(package)
            
            if not self._layer_name:
                return result
            
            # 2. 获取 Latency 数据
            # 注意: SurfaceView 名称可能包含特殊字符，需转义传给 shell
            # 但 adbutils.shell 会处理一部分，或者我们需要用引号包裹
            # 为了安全，我们手动包裹引号
            safe_layer_name = f"'{self._layer_name}'"
            cmd = f"dumpsys SurfaceFlinger --latency {safe_layer_name}"
            output = self.device.shell(cmd)
            lines = output.strip().splitlines()
            
            # 如果当前 layer 数据失效 (len < 2)，清除并返回 (下次会重新扫描)
            if len(lines) < 2:
                self._layer_name = None
                return result

            # Line 0: Refresh Period in ns
            try:
                refresh_period = int(lines[0])
                if refresh_period <= 0: refresh_period = 16666666
            except:
                refresh_period = 16666666

            # Jank Threshold
            jank_threshold = refresh_period * 2

            # 3. 解析 Frame Times
            valid_lines = []
            for line in lines[1:]:
                parts = line.split()
                if len(parts) == 3:
                    present_time = int(parts[2])
                    # 9223372036854775807 is INT64_MAX (Pending)
                    if present_time > 0 and present_time < 9223372036854775807: 
                        valid_lines.append(present_time)

            if not valid_lines:
                # 只有 Pending 帧或无有效帧，可能刚开始渲染
                return result

            last_frame_time = valid_lines[-1]
            
            # 检查是否 stale (如果最后更新时间距离现在太久，比如 > 2秒? )
            # 难点: 无法简单获取 device monotonic time.
            # 方案: 比较这次和上次的 last_frame_time? 
            # 如果 last_frame_time 一直不变，说明画面静止 -> FPS 0. Correct.
            
            # 计算最近 1 秒内的帧
            threshold = 1_000_000_000 # 1 second in ns
            
            frames_in_window = []
            for t in reversed(valid_lines):
                if last_frame_time - t < threshold:
                    frames_in_window.insert(0, t)
                else:
                    break
            
            # 如果总帧数太少，可能无法计算准确 FPS
            if len(frames_in_window) < 1:
                return result

            # FPS = 帧数
            # 如果画面静止，valid_lines 不变，last_frame_time 不变
            # 但我们每次都取最后1秒窗口。
            # 如果 last_frame_time 是 10秒前的，frames_in_window 还是有数据 (当时的数据)。
            # 这会导致 FPS 虚高 (显示的是 10秒前的 FPS)。
            # 修正: 我们需要判断 last_frame_time 是否"新鲜"。
            # Hack: 记录 self._last_frame_timestamp_global。
            # 如果当前的 last_frame_time == self._last_frame_timestamp_global，说明没更新。
            # 此时 FPS = 0.
            
            if hasattr(self, '_last_seen_frame_time') and self._last_seen_frame_time == last_frame_time:
                # 画面未更新
                result["fps"] = 0
                result["jank"] = 0
                result["stutter"] = 0.0
                
                # Watchdog: 如果连续多次 FPS 为 0，可能锁定了错误的 Layer
                if not hasattr(self, '_zero_fps_count'):
                    self._zero_fps_count = 0
                self._zero_fps_count += 1
                
                if self._zero_fps_count >= 5: # 5 seconds of zero FPS
                    logger.warning(f"FPS is 0 for 5s, resetting layer from {self._layer_name}")
                    self._layer_name = None
                    self._zero_fps_count = 0
                
                # Return early to avoid calculating jank on old frames
                return result
            else:
                result["fps"] = len(frames_in_window)
                self._zero_fps_count = 0 # Reset counter on activity
            
            self._last_seen_frame_time = last_frame_time

            # Jank & Stutter
            jank_count = 0
            excess_time = 0
            total_duration_sum = 0
            
            for i in range(1, len(frames_in_window)):
                duration = frames_in_window[i] - frames_in_window[i-1]
                total_duration_sum += duration
                
                # Jank: Frame duration > 2 * refresh_period
                if duration > jank_threshold:
                    jank_count += 1
                
                # Stutter calculation: Sum of time exceeding refresh_period
                # Use a small buffer (e.g. + 1ms or 1.1x) to avoid noise? 
                # Strict definition: duration > refresh_period
                if duration > refresh_period:
                    excess_time += (duration - refresh_period)
            
            result["jank"] = jank_count
            
            # Stutter Rate = (Excess Time / Total Duration) * 100
            if total_duration_sum > 0:
                stutter_rate = (excess_time / total_duration_sum) * 100.0
                result["stutter"] = round(min(stutter_rate, 100.0), 1)
            else:
                result["stutter"] = 0.0

        except Exception as e:
            logger.error(f"FPS/Jank error: {e}")
            self._layer_name = None # Reset on error
        
        return result

    def _find_active_layer(self, package: str) -> str:
        """
        扫描所有相关图层，找到最后更新时间最大的那个 (Active Layer)
        """
        try:
            layers = self.device.shell("dumpsys SurfaceFlinger --list").splitlines()
            candidates = []
            for layer in layers:
                # 宽松匹配: 只要包含包名
                if package in layer:
                     # 提取真实 Layer 名 (去除 RequestedLayerState 等包裹)
                    clean_name = layer.strip()
                    if "RequestedLayerState{" in layer:
                        import re
                        match = re.search(r"RequestedLayerState\{(.+?)\}", layer)
                        if match:
                            content = match.group(1)
                            # 尝试提取中间的关键部分，但也保留原始完整性以便 dumpsys 识别
                            # 这里的逻辑需要与 dumpsys 输出匹配
                            # 通常 dumpsys --list 输出的 clean name 可以直接用于 --latency
                            # 但 RequestedLayerState 包裹的内容通常包含 parentId 等，需要清理
                            # 策略: 优先找包含 # 的部分
                            parts = content.split()
                            for part in parts:
                                if "#" in part:
                                    clean_name = part
                                    break
                            else:
                                clean_name = content # Fallback
                    
                    candidates.append(clean_name)
            
            if not candidates:
                return None

            # 筛选出可能的 candidates (包含 SurfaceView 或 Activity)
            valid_candidates = [c for c in candidates if "Splash Screen" not in c and "Background for" not in c]
            
            # 为了性能，限制检测数量。优先检测 "看起来像" 主窗口的
            # 排序: SurfaceView 优先? Activity 优先?
            # 这里的策略是: 全部检测 (Top 10)，谁新谁赢。
            
            # 优先把含有 / 或 SurfaceView 的排前面
            valid_candidates.sort(key=lambda x: 1 if "SurfaceView" in x or "/" in x else 0, reverse=True)
            
            best_layer = None
            max_timestamp = -1
            
            # Check top 10 candidates
            for layer in valid_candidates[:10]:
                # Skip obviously bad ones if needed
                
                # Check latency
                try:
                    safe_name = f"'{layer}'"
                    # Limit output to save bandwidth
                    cmd = f"dumpsys SurfaceFlinger --latency {safe_name} | tail -n 5"
                    output = self.device.shell(cmd)
                    lines = output.strip().splitlines()
                    
                    if len(lines) < 2: continue
                    
                    last_ts = 0
                    for line in lines:
                        parts = line.split()
                        if len(parts) == 3:
                            ts = int(parts[1]) # Start time? Or Present time (2)?
                            # Use Present Time (2)
                            present = int(parts[2])
                            # Handle MAX_INT (Pending) -> treat as VERY NEW
                            if present == 9223372036854775807:
                                # Use timestamp from column 1 (vsync) as proxy?
                                # Or just treat as current max
                                ts = int(parts[1]) 
                            else:
                                ts = present
                            
                            if ts > last_ts:
                                last_ts = ts
                    
                    if last_ts > max_timestamp:
                        max_timestamp = last_ts
                        best_layer = layer
                        
                except Exception as e:
                    if "not found" in str(e) or "offline" in str(e):
                        raise e
                    continue
            
            if best_layer:
                logger.info(f"Selected active layer: {best_layer} (TS: {max_timestamp})")
                return best_layer
                
        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            logger.error(f"Find active layer error: {e}")
        
        return None

    def _get_fps(self, package: str) -> int:
        # Legacy support if needed, but we use _get_fps_and_jank now
        return self._get_fps_and_jank(package)["fps"]

    def _get_battery_info(self) -> Dict[str, Any]:
        """
        获取电池信息: Level, Voltage, Temp, Current
        """
        info = {"level": 0, "voltage": 0, "temp": 0.0, "current": 0}
        try:
            output = self.device.shell("dumpsys battery")
            for line in output.splitlines():
                line = line.strip()
                if line.startswith("level:"):
                    info["level"] = int(line.split(":")[1])
                elif line.startswith("voltage:"):
                    info["voltage"] = int(line.split(":")[1]) # mV
                elif line.startswith("temperature:"):
                    info["temp"] = int(line.split(":")[1]) / 10.0 # 0.1 C -> C
            
            # 获取电流 (Current) - 这是一个难点，因为不同厂商节点不同
            # 尝试常见路径
            current_paths = [
                "/sys/class/power_supply/battery/current_now",
                "/sys/class/power_supply/bms/current_now",
                "/sys/class/power_supply/main/current_now"
            ]
            for path in current_paths:
                try:
                    val = self.device.shell(f"cat {path}").strip()
                    if val and val.lstrip('-').isdigit():
                        # 通常单位是 uA (微安) -> 转换为 mA
                        # 有些设备是负数表示放电
                        current_ua = int(val)
                        info["current"] = abs(current_ua) // 1000
                        break
                except:
                    pass
                    
        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            pass
        return info

    def _get_network_usage(self, package: str) -> Dict[str, float]:
        """
        获取网络流量速率 (KB/s)
        支持单应用 (UID) 和整机 (System Global) 两种模式
        """
        info = {"rx": 0.0, "tx": 0.0}
        current_rx = 0
        current_tx = 0
        found_data = False
        
        try:
            # 1. 尝试获取 UID 流量 (单应用精准流量)
            # 优先尝试 Android 9- 的 proc 方式，或者 dumpsys (如果已实现)
            uid = None
            if package:
                try:
                    uid_output = self.device.shell(f"dumpsys package {package} | grep userId=")
                    if uid_output:
                        uid = uid_output.strip().split("userId=")[1].split()[0]
                except:
                    pass
            
            if uid:
                # 方法 A: /proc/uid_stat/{uid} (Android 9 及以下)
                try:
                    rx = self.device.shell(f"cat /proc/uid_stat/{uid}/tcp_rcv").strip()
                    tx = self.device.shell(f"cat /proc/uid_stat/{uid}/tcp_snd").strip()
                    if rx.isdigit() and tx.isdigit():
                        current_rx = int(rx)
                        current_tx = int(tx)
                        found_data = True
                except:
                    pass
                
                # 方法 B: /proc/net/xt_qtaguid/stats (Android 9 及以下)
                if not found_data:
                    try:
                        output = self.device.shell(f"cat /proc/net/xt_qtaguid/stats | grep {uid}")
                        if output:
                            total_rx = 0
                            total_tx = 0
                            for line in output.splitlines():
                                parts = line.split()
                                # idx iface acct_tag_hex uid_tag_int cnt_set rx_bytes rx_packets tx_bytes ...
                                if len(parts) > 8 and parts[3] == uid:
                                    total_rx += int(parts[5])
                                    total_tx += int(parts[7])
                            current_rx = total_rx
                            current_tx = total_tx
                            found_data = True
                    except:
                        pass

            # 2. Fallback: 获取整机流量 (Android 10+ 无法获取 UID 流量时的兜底方案)
            # /proc/net/dev 是大多数 Android 版本都可读的
            if not found_data:
                try:
                    output = self.device.shell("cat /proc/net/dev")
                    # Inter-|   Receive                                                |  Transmit
                    #  face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets ...
                    # wlan0: 12345 ...
                    if output:
                        lines = output.splitlines()
                        for line in lines:
                            # 过滤掉 lo (本地环回) 和 tun (VPN)
                            if "wlan" in line or "rmnet" in line or "eth" in line:
                                parts = line.split(":")
                                if len(parts) > 1:
                                    # 注意：部分设备可能没有空格，需要仔细 split
                                    data_parts = parts[1].split()
                                    if len(data_parts) >= 9:
                                        current_rx += int(data_parts[0]) # Receive bytes
                                        current_tx += int(data_parts[8]) # Transmit bytes
                                        found_data = True
                except:
                    pass

            # 3. 计算差分 (Rate Calculation)
            # 只有当获取到有效数据时才计算
            if found_data:
                if hasattr(self, '_last_network_data') and self._last_network_data:
                    last_rx, last_tx, last_time = self._last_network_data
                    current_time = time.time()
                    time_diff = current_time - last_time
                    
                    if time_diff > 0:
                        diff_rx = current_rx - last_rx
                        diff_tx = current_tx - last_tx
                        
                        # 处理计数器溢出或重启的情况
                        if diff_rx < 0: diff_rx = 0
                        if diff_tx < 0: diff_tx = 0
                        
                        # 转换为 KB/s
                        info["rx"] = round(diff_rx / 1024 / time_diff, 1)
                        info["tx"] = round(diff_tx / 1024 / time_diff, 1)
                
                # 更新 Last Data
                self._last_network_data = (current_rx, current_tx, time.time())
            else:
                # 如果完全获取不到数据，重置
                self._last_network_data = None

        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            pass
            
        return info

    def _get_gpu_usage(self) -> float:
        """
        尝试获取 GPU 使用率 (适配 Adreno, Mali, Pixel)
        """
        gpu_paths = [
            "/sys/class/kgsl/kgsl-3d0/gpubusy", # Adreno
            "/sys/class/misc/mali0/device/utilization", # Mali Common
            "/sys/kernel/debug/mali0/ctx/utilization_gp_pp", # Mali Debug
            "/sys/devices/platform/google,mali/gpu_utilization" # Pixel / Some Google chips
        ]
        
        try:
            for path in gpu_paths:
                # Need to check existence first? cat will fail if not exist, that's fine.
                # Just try shell cat
                # Optimize: Cache the valid path after first success
                if hasattr(self, '_valid_gpu_path') and self._valid_gpu_path != path:
                    continue

                output = self.device.shell(f"cat {path} 2>/dev/null").strip()
                if not output: continue
                
                val = _parse_gpu_from_content(output, path)
                if val is not None:
                     self._valid_gpu_path = path
                     return val

        except Exception as e:
            if "not found" in str(e) or "offline" in str(e):
                raise e
            pass
            
        return 0.0

def _parse_cpu_from_top(output: str) -> float:
    lines = output.strip().splitlines()
    total_cpu = 0.0
    
    for line in lines:
        parts = line.split()
        if len(parts) < 5: continue
        
        # Skip headers (PID USER ...)
        if "PID" in parts and "USER" in parts:
            continue
        
        # Heuristic CPU parsing
        found_cpu = False
        for i, part in enumerate(parts):
            if part in ['R', 'S', 'I', 'D', 'Z', 'T'] and i < len(parts) - 1:
                # Check next column for CPU
                next_part = parts[i+1]
                try:
                    val = float(next_part.replace('%', ''))
                    total_cpu += val
                    found_cpu = True
                    break
                except ValueError:
                    continue
        
        if not found_cpu:
            # Fallback 1: look for % column
            for part in parts:
                if "%" in part:
                    try:
                        total_cpu += float(part.replace("%", ""))
                        found_cpu = True
                        break
                    except: pass
        
        if not found_cpu:
                # Fallback 2: Fixed column index (usually 9th column, index 8)
                # PID USER PR NI VIRT RES SHR S %CPU
                if len(parts) >= 10:
                    try:
                        val = float(parts[8]) # Index 8 is 9th column? No.
                        # PID(0) USER(1) PR(2) NI(3) VIRT(4) RES(5) SHR(6) S(7) %CPU(8)
                        # In the log: 13737 ... 146M S 25.9
                        # Let's try index 8 or 9
                        if parts[7] in ['R', 'S', 'I', 'D', 'Z', 'T']:
                            val = float(parts[8])
                            total_cpu += val
                    except: pass

    return total_cpu

def _parse_gpu_from_content(output: str, path: str) -> float:
    # Adreno Format: <used_cycles> <total_cycles>
    if "kgsl" in path:
        parts = output.split()
        if len(parts) == 2:
            try:
                used = int(parts[0])
                total = int(parts[1])
                
                if total > 0:
                    val = round((used / total) * 100, 1)
                    if val > 100.0: val = 100.0
                    return val
                else:
                    return 0.0
            except:
                pass

    # Mali Format: Often just a number (0-100) or utilization
    else:
        # Try to parse as single integer
        if output.isdigit():
             return float(output)
    
    return None
