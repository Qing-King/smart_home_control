# Backend

第二阶段开始，这里同时包含：

- 第一阶段的命令行 MQTT 控制脚本
- 第二阶段的 Flask Web 服务

当前后端需要和 ESP8266 固件保持同一套 MQTT 约定：

- Broker: 使用你自己的 EMQX 地址和端口
- Topic root: 默认示例是 `nodemcu`
- Command topic: `<topic_root>/cmd`
- Status topic: `<topic_root>/status`
- 支持命令: `on`、`off`、`toggle`、`status`

## 目录说明

- `control_device.py`: 第一阶段直接运行的控制入口
- `run_web.py`: 第二阶段的 Web 服务启动入口
- `src/smart_home_backend/config.py`: 读取 `.env` 配置
- `src/smart_home_backend/controller.py`: MQTT 连接和发命令逻辑
- `src/smart_home_backend/web_app.py`: Flask API 和页面托管逻辑

## 快速开始

1. 进入目录：

   ```bash
   cd /home/qing/esp/smart_home_control/backend
   ```

2. 创建虚拟环境并安装依赖：

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install -r requirements.txt
   ```

3. 准备配置文件：

   ```bash
   cp .env.example .env
   ```

   然后把 `.env` 里的 MQTT 配置改成和设备端一致。

4. 控制设备：

   ```bash
   python3 control_device.py on
   python3 control_device.py off
   python3 control_device.py toggle
   python3 control_device.py status
   ```

默认会在发命令后等待设备回一条 `nodemcu/status` 状态消息，并把 JSON 打印出来。

如果你只想发命令、不等回包，可以用：

```bash
python3 control_device.py on --no-wait
```

## 启动网页控制端

默认 Web 服务会监听不常用端口 `28681`，并绑定 `0.0.0.0`，方便你后面直接部署到服务器。

启动命令：

```bash
python3 run_web.py
```

浏览器访问：

```text
http://<服务器IP>:28681/
```

可用接口：

- `GET /api/health`
- `GET /api/device/status`
- `POST /api/device/command`

`POST /api/device/command` 示例：

```json
{
  "command": "on",
  "wait_for_status": true
}
```

## 部署提示

- 服务器安全组或防火墙需要放行 `28681/TCP`
- 如果你后面要挂域名或 Nginx，可以把这个 Flask 服务放在内网端口继续跑
- 如果要改端口，可以修改 `backend/.env` 里的 `WEB_PORT`
