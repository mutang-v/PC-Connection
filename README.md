# PC Connection 电脑伴侣

让手机远程监控和控制你的 Windows 电脑的轻量级工具。电脑端运行一个 Python 后端服务，手机通过 **配对码 / 扫码** 安全连接后，即可在局域网内随时随地查看电脑状态并执行控制操作。

- **后端**：Python 标准库 + psutil，零框架
- **手机端**：原生 Android App 或 网页控制台
- **在线概览**：任一支持浏览器的设备（含 Android / iOS）访问网页控制台即可使用

![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ 功能总览

### 📊 电脑监控
- CPU / 内存 / 系统盘使用率、网络上下行实时速率、开机时长
- 各磁盘分区占用
- 电脑电池状态（百分比、是否充电、预计剩余时长）
- CPU / 内存近期趋势曲线

### 🎮 电脑控制
- 快速打开 Windows 系统面板：任务管理器、网络 / 蓝牙 / 显示 / 声音 / 相机 / 电源设置、Windows 设置
- 显示桌面、锁定屏幕
- 内存工作集整理（安全版：只回收当前用户普通应用的工作集，绝不结束进程）

### 🎵 媒体 & 音量
- 播放 / 暂停、上一首、下一首
- 音量增减 / 静音 / 拖动滑块精确设置（0–100%）

### 🔌 进程管理
- 查看内存 / CPU 占用最高的进程
- **二次确认**后可结束特定进程（内置系统关键进程白名单保护）

### 📋 剪贴板互通
- 从手机读取电脑剪贴板、写入内容到电脑剪贴板

### 📁 文件互传
- 手机 ↔ 电脑双向传输文件（默认单文件 ≤ 20MB）
- 手机上传的文件保存到电脑端项目的 `share/` 目录

### 🔔 电脑推送通知
- 从手机发送系统通知（Toast）到电脑桌面

### 🚨 智能告警
- CPU 尖峰 / 高位、内存偏高、系统盘不足、低电量（未充电）、CPU 持续高位 等自动告警，实时推送到手机

### 🤝 安全的设备配对
- 8 位一次性配对码（10 分钟有效，最多 5 次错误尝试）
- 桌面二维码扫码直连（Android App）
- 设备凭证仅存 SHA-256 摘要，不存储原始令牌

---

## 📱 支持的连接方式

| 方式 | 说明 |
|---|---|
| **Android App** | 原生应用，支持扫码 / 手动输入配对，功能最全 |
| **网页控制台** | 任意浏览器访问 `http://电脑IP:8000`，适合 iOS 或临时使用 |

---

## 🗂️ 项目结构

```
PCCompanion_App/
├── server.py                  # 后端启动入口
├── start_companion.bat        # Windows 一键启动脚本
├── requirements.txt           # Python 依赖
├── companion/
│   ├── http_api.py            # HTTP 路由（认证 + API + 静态服务）
│   ├── auth.py                # 配对码 / Bearer Token 认证
│   ├── metrics.py             # 硬件监控只读指标 + 告警
│   ├── actions.py             # Windows 控制动作白名单
│   ├── media.py               # 媒体 & 音量控制（SendInput）
│   ├── system_tools.py        # 剪贴板 / 通知 / 结束进程
│   ├── qr_text.py             # 终端二维码渲染
│   └── p9_controller.py       # （可选扩展）adb 桥接安卓设备
├── web/
│   └── index.html             # 网页控制台（单文件）
├── android_app/               # Android 原生 App 源码
│   └── app/src/main/...
├── tests/                     # 后端单元测试
└── docs/                      # 设计文档
```

---

## 🚀 快速开始（电脑端）

### 环境要求
- Windows 7+（控制功能依赖 Windows API）
- Python 3.9+

### 安装 & 启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python server.py
```

或者直接双击 `start_companion.bat`（会先装依赖再启动）。

启动后终端会显示：
- 本机 / 手机访问地址
- **当前配对码**（8 位数字，10 分钟内有效，过期自动刷新）
- 一个可被手机扫码的二维码

> 首次运行会在项目目录生成 `data/device_token.json`（只存令牌哈希）。**请勿公开分享此文件。**

### 防火墙提示
Windows 防火墙可能拦截入站连接。请放行 Python，并**仅允许"专用网络"**。

---

## 📱 手机连接

### 方式一：网页控制台（最快）
手机连接**与电脑相同的局域网 / 热点**，用浏览器打开终端里显示的 `http://电脑IP:8000`，输入配对码即可。

### 方式二：Android App
1. 克隆本项目，用 Android Studio 打开 `android_app/` 目录构建 APK（或用 `gradle assembleDebug`）
2. 在手机上安装 APK
3. 打开 App，扫描电脑终端里的二维码，或手动输入电脑 IP 和配对码
4. 配对成功后即可使用

---

## ⚙️ Android App 构建（开发者）

```bash
cd android_app
gradle assembleDebug        # 产物：app/build/outputs/apk/debug/app-debug.apk
```

**工程参数**：minSdk 24（Android 7.0+）、targetSdk 26、Java 17、Gradle 9.x、AGP 9.x。扫码使用 ZXing `core-3.5.3.jar`（已随仓库附带）。

> 目标机型为本项目开发时的华为 P9（EMUI 8）。因使用旧 Camera API，已在 `AndroidManifest` 标注 `requires-feature camera=false`，未运行时不会强制要求摄像头权限，理论上兼容主流 Android 机型。

---

## 🧪 运行测试

```bash
python -m unittest discover -s tests -v
```

---

## 🔌 主要 API（部分）

所有 `/api/*` 接口（除 `/api/pair` 外）都要求请求头 `Authorization: Bearer <token>`。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/stats` | 监控指标（含电池、趋势） |
| GET | `/api/alerts` | 当前告警列表 |
| GET | `/api/processes` | 内存占用 Top 进程 |
| GET | `/api/processes/cpu` | CPU 占用 Top 进程 |
| GET | `/api/volume` | 当前音量 & 静音状态 |
| GET | `/api/clipboard` | 读取电脑剪贴板 |
| POST | `/api/clipboard` | 写入电脑剪贴板 `{text}` |
| POST | `/api/processes/kill` | 结束进程 `{pid, name, confirm:true}` |
| POST | `/api/notify` | 发送桌面通知 `{title, message}` |
| POST | `/api/action` | 执行控制动作 `{action, confirm?}` |
| GET | `/api/paircode` & `/api/pair/qr` | 获取配对码 / 二维码（未认证） |
| POST | `/api/pair` | 用配对码换取 token（未认证） |

**`/api/action` 支持的 `action` 白名单：**
系统面板：`task_manager` `network_settings` `windows_settings` `bluetooth_settings` `display_settings` `sound_settings` `camera_settings` `power_settings` `show_desktop` `lock_screen`
内存：`memory_optimize`
媒体 & 音量：`media_play_pause` `media_next` `media_prev` `volume_up` `volume_down` `volume_mute` `volume_set`（+`level`/`delta` 参数）
电源（需 `confirm:true`）：`system_sleep` `system_restart` `system_shutdown`

> 服务端**只接受白名单固定动作**，绝不执行客户端传入的任意命令。

---

## 🔐 安全说明

本工具定位是**可信私人局域网**内的辅助工具，尚未经过专业安全审计：

- ⚠️ 使用 **HTTP 明文**，令牌可能在同一个不可信网络上被观察到
- ✅ 仅在**可信的私人热点 / 局域网**使用，防火墙仅允许"专用网络"
- ✅ **不要**把 8000 端口映射到公网，也**不要**把服务暴露到公网
- 撤销设备：停止服务 → 删除 `data/device_token.json` → 重启服务，旧设备令牌即失效

---

## 📄 许可证

[MIT](LICENSE) © mutang-v
