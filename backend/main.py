from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
import json
import asyncio
import os
import shutil
import csv
import time
from adbutils import adb
from core.android_collector import AndroidCollector
from core.ios_collector import IOSCollector
from loguru import logger
from typing import Union

app = FastAPI(title="VeloPerf Server")

# Ensure static/screenshots exists
SCREENSHOT_DIR = "static/screenshots"
if os.path.exists(SCREENSHOT_DIR):
    # Clean up old screenshots on restart
    shutil.rmtree(SCREENSHOT_DIR)
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

app.mount("/screenshots", StaticFiles(directory=SCREENSHOT_DIR), name="screenshots")

# Ensure static/records exists and mount
RECORD_DIR = "static/records"
os.makedirs(RECORD_DIR, exist_ok=True)
app.mount("/records", StaticFiles(directory=RECORD_DIR), name="records")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 存储活跃的采集器实例
collectors: Dict[str, Union[AndroidCollector, IOSCollector]] = {}

@app.get("/api/devices")
async def get_devices():
    """获取连接的设备列表"""
    devices = []
    
    # Android Devices
    try:
        for d in adb.device_list():
            manufacturer = d.prop.get("ro.product.manufacturer", "")
            model = d.prop.model
            name = f"{manufacturer} {model}".strip()
            
            devices.append({
                "serial": d.serial,
                "model": name,
                "platform": "android",
                "status": "online"
            })
    except Exception as e:
        logger.error(f"Failed to list Android devices: {e}")

    # iOS Devices
    try:
        ios_devices = IOSCollector.get_devices()
        for d in ios_devices:
            model_name = "iOS Device"
            try:
                from tidevice import Device
                dev = Device(d.udid)
                # Try to get user defined name first
                model_name = dev.name or "iOS Device"
            except Exception:
                pass
                
            devices.append({
                "serial": d.udid,
                "model": model_name,
                "platform": "ios",
                "status": "online"
            })
    except Exception as e:
        logger.error(f"Failed to list iOS devices: {e}")
        
    return {"devices": devices}

@app.get("/api/apps/{serial}")
async def get_apps(serial: str, platform: str = "android"):
    """获取设备上安装的应用列表"""
    if platform == "ios" or (len(serial) > 20 or "-" in serial):
        apps = IOSCollector.get_installed_apps(serial)
    else:
        apps = AndroidCollector.get_installed_apps(serial)
    return {"apps": apps}

@app.get("/api/records/{serial}")
async def list_records(serial: str):
    """获取设备的录制文件列表"""
    record_dir_serial = os.path.join(RECORD_DIR, serial)
    if not os.path.exists(record_dir_serial):
        return {"files": []}
    
    files = []
    try:
        for f in os.listdir(record_dir_serial):
            if f.endswith(".csv"):
                fp = os.path.join(record_dir_serial, f)
                stat = os.stat(fp)
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "url": f"/records/{serial}/{f}"
                })
        # Sort by mtime desc
        files.sort(key=lambda x: x["mtime"], reverse=True)
    except Exception as e:
        logger.error(f"List records error: {e}")
        
    return {"files": files}

@app.websocket("/ws/monitor/{serial}")
async def websocket_endpoint(websocket: WebSocket, serial: str):
    await websocket.accept()
    # Check platform from query param or just try to find device
    # Or frontend sends platform?
    # For simplicity, we can detect by serial format or check if exists in lists
    
    platform = "android"
    if len(serial) > 20 or "-" in serial: # Simple heuristic for iOS UDID
        platform = "ios"
        
    logger.info(f"WebSocket connected for device: {serial} ({platform})")

    if platform == "android":
        collector = AndroidCollector(serial)
    else:
        collector = IOSCollector(serial)
        # For iOS, we need to know the bundle_id to start
        # Wait for client to send start message with bundle_id
    
    collectors[serial] = collector

    # 定义回调函数，当采集到数据时通过 WebSocket 发送
    def on_data(data):
        try:
            # WebSocket 发送必须在事件循环中
            # 由于 callback 是同步调用，我们需要用到 run_coroutine_threadsafe 或者简单的 asyncio.run (不推荐)
            # 更好的方式是 collector 本身支持 async callback 或者我们在 loop 中 run
            # 这里简化处理：我们不通过 callback，而是让 loop 直接 await send
            pass 
        except Exception as e:
            logger.error(f"Send error: {e}")

    # 修改 collector 逻辑：直接传入 websocket 引用可能不解耦，
    # 但为了 MVP 快速实现，我们重写一个 async generator 或者在 collector 内部通过 queue 传递数据
    
    # 采用 Queue 模式解耦
    data_queue = asyncio.Queue()
    
    def queue_callback(data):
        # 这里的 loop 是主线程 loop
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(data_queue.put_nowait, data)
        except RuntimeError:
             # 如果在其他线程且没有 loop，可能需要 new_event_loop (不应发生)
             pass

    collector.set_callback(queue_callback)
    
    # Defer start until receiving 'start' message to allow target package/bundle id to be set
    # Prepare recording resources
    record_dir_serial = os.path.join(RECORD_DIR, serial)
    os.makedirs(record_dir_serial, exist_ok=True)
    record_fp = None
    record_writer = None

    try:
        while True:
            # 使用 asyncio.gather 同时等待 队列数据 和 WS 消息
            # 但为了简化，我们可以用 wait task
            
            # 创建读取 WS 的 task
            recv_task = asyncio.create_task(websocket.receive_json())
            # 创建读取 Queue 的 task
            queue_task = asyncio.create_task(data_queue.get())
            
            done, pending = await asyncio.wait(
                [recv_task, queue_task], 
                return_when=asyncio.FIRST_COMPLETED
            )
            
            for task in done:
                if task == queue_task:
                    # 发送采集数据
                    data = task.result()
                    await websocket.send_json(data)
                    # Write CSV when recording and monitor payload
                    if record_writer and isinstance(data, dict) and data.get("type") == "monitor":
                        row = [
                            data.get("timestamp"),
                            data.get("package"),
                            data.get("cpu"),
                            data.get("memory"),
                            data.get("fps"),
                            data.get("jank"),
                            data.get("stutter"),
                            data.get("gpu"),
                            data.get("battery", {}).get("level"),
                            data.get("battery", {}).get("voltage"),
                            data.get("battery", {}).get("temp"),
                            data.get("battery", {}).get("current"),
                            data.get("network", {}).get("rx"),
                            data.get("network", {}).get("tx"),
                        ]
                        try:
                            record_writer.writerow(row)
                            if record_fp:
                                record_fp.flush()
                        except Exception as e:
                            logger.error(f"Record write error: {e}")
                elif task == recv_task:
                    # 处理客户端指令
                    msg = task.result()
                    # 比如 {"type": "start", "target": "com.example"}
                    if msg.get("type") == "start":
                        target = msg.get("target")
                        collector.set_target(target)
                        if not collector.running:
                            await collector.start()
                        # initialize CSV recorder
                        try:
                            ts_name = str(int(time.time() * 1000))
                            base_name = f"{ts_name}_{target or 'unknown'}.csv"
                            file_path = os.path.join(record_dir_serial, base_name)
                            record_fp = open(file_path, "w", newline="", encoding="utf-8")
                            record_writer = csv.writer(record_fp)
                            record_writer.writerow([
                                "timestamp","package","cpu(%)","memory(MB)","fps","jank","stutter(%)",
                                "gpu(%)","battery.level","battery.voltage(mV)","battery.temp(C)",
                                "battery.current(mA)","network.rx(KB/s)","network.tx(KB/s)"
                            ])
                            logger.info(f"Recording to {file_path}")
                        except Exception as e:
                            logger.error(f"Failed to init recording: {e}")
                    elif msg.get("type") == "stop":
                        collector.stop()
                        # finalize CSV
                        try:
                            if record_fp:
                                record_fp.flush()
                                record_fp.close()
                        except Exception:
                            pass
                        record_fp = None
                        record_writer = None

            # 取消未完成的任务
            for task in pending:
                task.cancel()

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {serial}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        collector.stop()
        try:
            if record_fp:
                record_fp.flush()
                record_fp.close()
        except Exception:
            pass
        if serial in collectors:
            del collectors[serial]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
