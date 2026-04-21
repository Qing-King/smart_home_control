# Smart Home Control

这个仓库现在包含一整套“家庭设备控制平台”的开发内容，方便在一处同时维护后端、网页和 ESP8266 固件。

## 目录规划

- `backend/`: Python 后端，包含 MQTT 控制逻辑、Flask Web 服务和 Windows 本地启动脚本。
- `frontend/`: 网页前端资源目录，由后端直接托管。
- `firmware/`: 设备端固件工程，目前收口了 ESP8266 的 `wifi_http_demo`，方便在 Windows 上继续开发。
- `deploy/`: Linux 服务器部署示例，包括 Nginx 和 systemd 配置。

## 当前链路

当前已经打通：

`Python backend -> EMQX -> ESP8266`

`Browser -> Flask backend -> EMQX -> ESP8266`

也就是说现在既可以用 Python 命令行控制设备，也可以通过网页控制设备。

## Windows 本地开发

如果你想在 Windows 上继续开发，推荐直接用这个仓库：

1. 后端：

   在 PowerShell 中进入 `backend/`，运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
   ```

   首次运行会自动创建 `.venv`、复制 `.env` 并安装依赖。

2. 固件：

   ESP8266 固件已经收进 `firmware/esp8266/wifi_http_demo/`。
   为了避免仓库过大，第三方 `ESP8266_RTOS_SDK` 和工具链没有直接 vendor 进来，仍然建议在 Windows 上单独安装一次。

   Windows 下的构建和烧录说明见：

   - `firmware/README.md`
   - `firmware/esp8266/wifi_http_demo/README.md`

3. 配置对齐：

   后端 `backend/.env` 里的 MQTT 配置，需要和固件 `firmware/esp8266/wifi_http_demo/sdkconfig.defaults` 或 `menuconfig` 里的配置保持一致。

## 推荐上线方式

如果你的 Linux 服务器已经有 Nginx，推荐使用：

`Nginx -> Gunicorn -> Flask`

这样公网只暴露 Nginx，Python 服务继续跑在本机 `127.0.0.1:28681`。
