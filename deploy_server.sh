#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
SERVICE_NAME="smart-home-control"
PUBLIC_HOST="${PUBLIC_HOST:-122.51.219.147}"
WEB_PORT="${WEB_PORT:-28681}"
SUBPATH="${SUBPATH:-/smart-home/}"
NGINX_SITE_FILE="${NGINX_SITE_FILE:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_USER="${APP_USER:-${SUDO_USER:-$(id -un)}}"
APP_GROUP="${APP_GROUP:-$(id -gn "$APP_USER")}"

run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "缺少命令: $1"
        exit 1
    fi
}

set_env_value() {
    local key="$1"
    local value="$2"

    if grep -q "^${key}=" "$BACKEND_DIR/.env"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$BACKEND_DIR/.env"
    else
        printf '%s=%s\n' "$key" "$value" >> "$BACKEND_DIR/.env"
    fi
}

normalize_subpath() {
    local raw="$1"

    if [ -z "$raw" ]; then
        raw="/smart-home/"
    fi

    if [ "${raw#/}" = "$raw" ]; then
        raw="/$raw"
    fi

    if [ "${raw%/}" = "$raw" ]; then
        raw="$raw/"
    fi

    printf '%s\n' "$raw"
}

detect_nginx_site_file() {
    local candidate

    if [ -n "$NGINX_SITE_FILE" ]; then
        printf '%s\n' "$NGINX_SITE_FILE"
        return 0
    fi

    for candidate in \
        /etc/nginx/sites-available/default \
        /etc/nginx/conf.d/default.conf \
        /etc/nginx/sites-enabled/default
    do
        if [ -f "$candidate" ]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

install_nginx_include() {
    local site_file="$1"
    local snippet_file="/etc/nginx/snippets/${SERVICE_NAME}.conf"
    local include_line="    include ${snippet_file};"
    local temp_file
    local subpath_trimmed="${SUBPATH%/}"

    run_root mkdir -p /etc/nginx/snippets

    run_root tee "$snippet_file" >/dev/null <<EOF
location = ${subpath_trimmed} {
    return 301 ${SUBPATH};
}

location ${SUBPATH} {
    proxy_pass http://127.0.0.1:${WEB_PORT}/;
    proxy_http_version 1.1;
    proxy_set_header Host \$host;
    proxy_set_header X-Real-IP \$remote_addr;
    proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \$scheme;
    proxy_set_header X-Forwarded-Host \$host;
    proxy_set_header X-Forwarded-Port \$server_port;
    proxy_read_timeout 30s;
}
EOF

    if grep -Fq "$snippet_file" "$site_file"; then
        return 0
    fi

    temp_file="$(mktemp)"

    if ! awk -v include_line="$include_line" '
        BEGIN { inserted = 0 }
        /^[[:space:]]*server[[:space:]]*\{[[:space:]]*$/ && inserted == 0 {
            print
            print include_line
            inserted = 1
            next
        }
        { print }
        END {
            if (inserted == 0) {
                exit 1
            }
        }
    ' "$site_file" >"$temp_file"; then
        rm -f "$temp_file"
        echo "没有在 $site_file 里找到可插入 include 的 server 块。"
        echo "请手动把 /etc/nginx/snippets/${SERVICE_NAME}.conf include 到现有 server 配置中。"
        exit 1
    fi

    run_root cp "$site_file" "${site_file}.bak"
    run_root cp "$temp_file" "$site_file"
    rm -f "$temp_file"
}

require_cmd "$PYTHON_BIN"
require_cmd nginx
require_cmd systemctl
require_cmd grep
require_cmd sed
require_cmd awk

if [ "$(id -u)" -ne 0 ]; then
    require_cmd sudo
fi

SUBPATH="$(normalize_subpath "$SUBPATH")"

if [ ! -d "$BACKEND_DIR" ]; then
    echo "找不到 backend 目录: $BACKEND_DIR"
    exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "已创建 $BACKEND_DIR/.env"
    echo "请先把 MQTT_HOST / MQTT_USERNAME / MQTT_PASSWORD 改成你的真实配置，然后重新执行本脚本。"
    exit 1
fi

if grep -Eq '^MQTT_HOST=your-emqx-host$|^MQTT_USERNAME=your-mqtt-username$|^MQTT_PASSWORD=your-mqtt-password$' "$BACKEND_DIR/.env"; then
    echo "$BACKEND_DIR/.env 里还是示例占位值，请先修改为真实 MQTT 配置后再执行。"
    exit 1
fi

cd "$BACKEND_DIR"

if [ ! -d ".venv" ]; then
    "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install -r requirements.txt

set_env_value "WEB_HOST" "127.0.0.1"
set_env_value "WEB_PORT" "$WEB_PORT"
set_env_value "WEB_DEBUG" "0"
set_env_value "WEB_PROXY_FIX" "1"

SYSTEMD_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

run_root tee "$SYSTEMD_FILE" >/dev/null <<EOF
[Unit]
Description=Smart Home Control Gunicorn Service
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
ExecStart=$BACKEND_DIR/.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:$WEB_PORT --access-logfile - --error-logfile - wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

if ! NGINX_SITE_FILE="$(detect_nginx_site_file)"; then
    echo "没有自动找到 Nginx 站点文件。"
    echo "请设置 NGINX_SITE_FILE=/etc/nginx/sites-available/<你的站点文件> 后重新执行。"
    exit 1
fi

install_nginx_include "$NGINX_SITE_FILE"

run_root systemctl daemon-reload
run_root systemctl enable --now "$SERVICE_NAME"
run_root nginx -t
run_root systemctl reload nginx
run_root systemctl restart "$SERVICE_NAME"

if command -v curl >/dev/null 2>&1; then
    curl -fsS "http://127.0.0.1:$WEB_PORT/api/health" >/dev/null
fi

echo
echo "部署完成。"
echo "应用目录: $ROOT_DIR"
echo "后端目录: $BACKEND_DIR"
echo "systemd 服务: $SERVICE_NAME"
echo "Nginx 站点文件: $NGINX_SITE_FILE"
echo "内部监听: http://127.0.0.1:$WEB_PORT"
echo "公网访问: http://$PUBLIC_HOST${SUBPATH}"
