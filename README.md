# VeloPerf 🚀

VeloPerf 🚀 是一个开源、免费的移动端性能测试工具，它支持 Android 和 iOS设备，提供实时的性能数据采集与可视化。

## 特性

- 🆓 **完全免费**：无任何收费项，源码开放。
- 🔒 **数据私有**：数据完全在本地处理，不上传云端。
- ⚡ **实时监控**：毫秒级采集 CPU、内存、FPS 等指标。
- 📱 **跨平台**：
  - Android: 支持 5.0+ (无需 ROOT)
  - iOS: 计划集成 tidevice 实现无越狱支持

## 项目结构

- `backend/`: Python (FastAPI) 后端，负责设备通信与数据采集。
- `frontend/`: Vue3 + Vite 前端，负责数据展示。
- `.github/workflows/ci.yml`: GitHub Actions 流水线配置

## 快速开始

### 前置要求

- Python 3.8+
- Node.js 16+
- ADB (Android Debug Bridge)

### 安装与运行

1. **安装后端依赖**

```bash
cd backend
pip install -r requirements.txt
```

2. **安装前端依赖**

```bash
cd frontend
npm install
```

3. **一键启动**

```bash
# 根目录下运行
./run.sh
```

或者分别启动：

- 后端: `cd backend && python main.py`
- 前端: `cd frontend && npm run dev`

## 本地部署（macOS）
 
 ### 环境准备
 
 - 安装 ADB（Android 调试桥）
 
   ```bash
   brew install android-platform-tools
   ```
 
 - 确保系统具备：
   - Python（自动创建 venv 并安装依赖）
   - Node.js（前端开发服务器）
   - 可选：iOS 支持由 `tidevice` 提供，已在后端 requirements 中包含
 
 ### 启动步骤
 
 1. 连接设备并打开调试：
    - Android：USB 连接 → 打开开发者选项 → 打开 USB 调试
    - iOS：USB 连接（如用 iOS，建议先信任此电脑）
 2. 在项目根目录执行：
 
    ```bash
    ./run.sh
    ```
 
 3. 打开浏览器访问：
    - 前端：`http://localhost:3000/`
    - 后端：`http://localhost:8000/`
 
 4. 在前端页面：
    - 下拉选择设备（显示厂商+型号，如 HUAWEI REA-AN00）
    - 选择/输入目标应用包名（iOS 需输入 Bundle ID）
    - 点击“开始测试”即可实时采集
 
 ### 热插拔与自动刷新
 
 - 系统每 3 秒自动刷新设备列表
 - 当前设备断开会自动停止测试并提醒
 - 插入新设备时如未选择，会自动选中第一台设备
 
 ### 端口说明
 
 - 前端开发端口：`3000`
 - 后端服务端口：`8000`
 - 若端口占用，`run.sh` 会尝试清理同端口的旧进程
 
 ### 常见问题排查
 
- pip 报 PEP 668 “externally-managed-environment”：
  - 使用项目根目录 `./run.sh`，脚本已内置兼容策略（优先 venv，其次用户目录安装）
  - 或使用 `pyenv` 安装 Python 3.11 并在 `backend` 中重新创建 venv
 - “device not found”：
   - 检查 USB 线与接口是否稳定
   - Android 重新拔插并确认 USB 调试已开启
   - 执行 `adb devices` 看是否能识别设备
 - iOS 应用列表为空：
   - 需要在输入框中手动填写 Bundle ID
   - tidevice 需设备“信任此电脑”
 - 前端打不开或白屏：
   - 确认前端地址 `http://localhost:3000/` 正常
   - 终端检查 Vite 是否已启动
 - 后端报错：
   - 查看终端日志是否有权限或设备连接错误
   - 重新执行 `./run.sh` 完整启动
 
 ### 停止服务
 
 - 在运行终端按 `Ctrl + C` 即可停止前后端
 - 或使用下述指令清理端口占用：
 
   ```bash
   lsof -ti:8000 | xargs kill -9
   lsof -ti:3000 | xargs kill -9
   ```
 
### 使用说明

1. 使用 USB 连接 Android 手机，确认为“调试模式”。
2. 打开浏览器访问 `http://localhost:3000`。
3. 选择设备，点击 **Start** 开始采集。

## 核心实现原理

- **Android**: 使用纯 Python 实现的 `adbutils` 库与手机通信，通过 `dumpsys` 命令获取性能数据。
- **WebSocket**: 前后端通过 WebSocket 实时推送数据流。

## 交互与使用提示

- 应用包名自动填充：开始测试后若输入框为空，系统会自动填入当前前台应用包名（Android），也可手动覆盖。
- 曲线标签显示：仅在鼠标悬停或点击某一曲线时显示该曲线末端标签，避免重叠。
- 包名优先级：后端在收到前端发送的 `start` 指令并附带包名/Bundle ID 后才启动采集，确保按指定目标采集。

## 数据录制与导出

系统会自动将每次测试的性能数据录制为 CSV 文件（可直接用 Excel 打开）。

- **自动录制**：点击“开始测试”后，后端会自动在 `backend/static/records/<设备序列号>/` 目录下创建 CSV 文件。
- **文件命名**：`时间戳_包名.csv` (例如 `1739180000000_com.example.app.csv`)
- **数据下载**：
  - 可以通过浏览器直接访问 `http://localhost:8000/records` 查看并下载录制文件。
  - 文件包含时间戳、CPU、内存、FPS、Jank、Stutter、GPU、电池、网络等全量指标。


