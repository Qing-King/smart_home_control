# Smart Home Control

这个目录现在作为“家庭设备控制平台”的总项目目录，后面前后端代码都放在这里。

## 当前目录规划

- `backend/`: Python 后端。现在已经包含 MQTT 控制逻辑和 Flask Web 服务。
- `frontend/`: 网页前端资源目录，由后端直接托管。
- `deploy/`: 服务器部署示例，包括 Nginx 和 systemd 配置

## 当前阶段完成情况

前两阶段已经完成：

`Python backend -> EMQX -> ESP8266`

`Browser -> Flask backend -> EMQX -> ESP8266`

也就是说现在既可以用 Python 命令行控制设备，也可以通过网页控制设备。

## 推荐上线方式

如果你的服务器已经有 Nginx，推荐使用：

`Nginx -> Gunicorn -> Flask`

这样公网只暴露 Nginx，Python 服务继续跑在本机 `127.0.0.1:28681`。
