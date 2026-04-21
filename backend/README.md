# Backend

第二阶段开始，这里同时包含：

- 第一阶段的命令行 MQTT 控制脚本
- 第二阶段的 Flask Web 服务
- 面向服务器部署的 Gunicorn 入口

当前后端需要和 ESP8266 固件保持同一套 MQTT 约定：

- Broker: 使用你自己的 EMQX 地址和端口
- Topic root: 默认示例是 `nodemcu`
- Command topic: `<topic_root>/cmd`
- Status topic: `<topic_root>/status`
- 支持命令: `on`、`off`、`toggle`、`status`

## 目录说明

- `control_device.py`: 第一阶段直接运行的控制入口
- `run_web.py`: 第二阶段的 Web 服务启动入口
- `wsgi.py`: Gunicorn 生产入口
- `src/smart_home_backend/config.py`: 读取 `.env` 配置
- `src/smart_home_backend/controller.py`: MQTT 连接和发命令逻辑
- `src/smart_home_backend/web_app.py`: Flask API 和页面托管逻辑

## 快速开始

1. 进入目录：

   ```bash
   cd /opt/smart_home_control/backend
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

## Windows 本机启动

如果你是在 Windows 上开发，可以直接用仓库里现成的 PowerShell 脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_windows.ps1
```

这个脚本会自动：

- 创建 `backend/.venv`
- 从 `.env.example` 生成 `.env`
- 安装或更新依赖
- 启动 `run_web.py`

如果你只想先准备环境、不立即启动服务，可以用：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_windows.ps1 -SkipRun
```

Windows 下的固件工程已经整理到 `../firmware/esp8266/wifi_http_demo/`，使用前请把后端 `.env` 和固件 MQTT 配置对齐。

## 启动网页控制端

默认 Web 服务会监听不常用端口 `28681`。

如果只是本机测试，可以直接运行 Flask 开发服务：

启动命令：

```bash
python3 run_web.py
```

浏览器访问：

```text
http://127.0.0.1:28681/
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

## Nginx 反向代理部署

如果服务器已经有 Nginx，推荐不要直接暴露 Flask 端口，而是使用：

`Nginx -> Gunicorn -> Flask`

### 1. 安装依赖

```bash
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

### 2. 启动 Gunicorn

```bash
.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:28681 wsgi:app
```

### 3. 配置 Nginx 子路径代理

示例文件已经放在：

- `../deploy/nginx/smart_home_control.conf`

这个文件现在不是完整站点，而是一个 `location` 片段，应该被放进你当前正在服务 `122.51.219.147` 的那个 `server {}` 里。

如果你手动配置，可以把下面这段加进现有 Nginx 站点：

```bash
location = /smart-home {
    return 301 /smart-home/;
}

location /smart-home/ {
    proxy_pass http://127.0.0.1:28681/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_read_timeout 30s;
}
```

配置完成后，可以直接访问：

```text
http://122.51.219.147/smart-home/
```

### 4. 配置 systemd

示例文件已经放在：

- `../deploy/systemd/smart-home-control.service`

使用前请先修改里面的：

- `User`
- `Group`
- `WorkingDirectory`
- `EnvironmentFile`
- `ExecStart`

然后执行：

```bash
sudo cp /opt/smart_home_control/deploy/systemd/smart-home-control.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smart-home-control
sudo systemctl status smart-home-control --no-pager
```

## 部署提示

- 如果走 Nginx 反向代理，通常不需要对公网放行 `28681/TCP`
- 如果你现在只有公网 IP，推荐直接用 `http://122.51.219.147/smart-home/`
- 只需要让 Gunicorn 监听 `127.0.0.1:28681`
- 如果要改内部端口，可以修改 `backend/.env` 里的 `WEB_PORT`
- 如果 `/opt/smart_home_control` 不是 `www-data` 可读，请按你的服务器用户调整 `smart-home-control.service`
