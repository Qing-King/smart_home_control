# WiFi MQTT Demo

这个目录是打包进 `smart_home_control` 的 ESP8266 固件工程，用于和 `backend/` 配合完成整条控制链路。

它会让 ESP8266：

- 连接 Wi-Fi
- 通过 TLS 连接 MQTT Broker
- 订阅 `<topic_root>/cmd`
- 上报 `<topic_root>/status`
- 根据 `on`、`off`、`toggle`、`status` 控制实际设备输出口
- 默认使用 NodeMCU D1，也就是 ESP8266 GPIO5；`on` 输出高电平，`off` 输出低电平
- 同时保留板载 LED 作为指示灯，默认使用 GPIO2；设备打开时 LED 亮，设备关闭时 LED 灭
- 根据后端下发的循环参数在 ESP8266 本地执行开/关循环；参数收到后，即使 MQTT/Wi-Fi 之后断开，也会继续按本地计时执行到结束

## 和后端的对应关系

这个固件要和 `backend/.env` 使用同一套 MQTT 配置：

- Broker: 你的 EMQX 地址和端口
- Username / Password: 和后端一致
- Topic root: 默认示例是 `nodemcu`
- Command topic: `<topic_root>/cmd`
- Status topic: `<topic_root>/status`

## Windows 快速开始

推荐在 Windows 上这样使用：

1. 安装 ESP8266 RTOS SDK 和官方工具链。
   这个仓库已经带上固件工程本身，但没有把第三方 SDK 和工具链一起 vendor 进来，避免仓库体积继续膨胀。
2. 把 `smart_home_control` 放到不带空格的目录。
3. 打开 `MSYS2 MinGW32` 或者 SDK 对应的 shell。
4. 进入当前目录：

   ```bash
   cd /c/path/to/smart_home_control/firmware/esp8266/wifi_http_demo
   ```

5. 导出 SDK 环境：

   ```bash
   source /c/path/to/ESP8266_RTOS_SDK/export.sh
   ```

6. 运行配置界面：

   ```bash
   make menuconfig
   ```

7. 至少确认这些配置：

   - `Example Connection Configuration` > `WiFi SSID`
   - `Example Connection Configuration` > `WiFi Password`
   - `WiFi MQTT Demo Network Configuration`
   - `WiFi MQTT Demo Device Output Configuration`
   - `WiFi MQTT Demo MQTT Configuration`
   - `Serial flasher config` > `Default serial port`

8. 在 Windows 下，把串口设置成你的 `COMx`，例如 `COM3`。
9. 构建、烧录并打开串口监视：

   ```bash
   make -j4 flash monitor
   ```

## 配置文件说明

- `sdkconfig.defaults`：仓库里的安全模板，已经改成占位值，适合作为 Windows 和 Linux 的共用起点。
- `sdkconfig`：本地生成文件，已经加入 `.gitignore`，不要提交。
- `main/Kconfig.projbuild`：`menuconfig` 里显示的默认值定义。

如果你只是想快速改值，可以先编辑 `sdkconfig.defaults`；如果你更习惯图形化配置，就直接用 `make menuconfig`。

## 测试建议

1. 先把 `backend/.env` 配成和固件一致的 MQTT 参数。
2. 在 Windows PowerShell 里启动后端：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\backend\start_windows.ps1
   ```

3. 固件连上后，浏览器访问：

   ```text
   http://127.0.0.1:28681/
   ```

4. 也可以直接往 `<topic_root>/cmd` 发布：

   - `on`
   - `off`
   - `toggle`
   - `status`
   - `cycle:start:<total_ms>:<on_ms>:<off_ms>`
   - `cycle:stop`
   - `cycle:cancel`

串口日志里能看到 MQTT 事件，设备也会向 `<topic_root>/status` 回传状态 JSON。
