#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
SERVICE_NAME="smart-home-control"
DEPLOY_DIR="$ROOT_DIR/deploy"
SYSTEMD_TEMPLATE="$DEPLOY_DIR/systemd/${SERVICE_NAME}.service"
NGINX_TEMPLATE="$DEPLOY_DIR/nginx/smart_home_control.conf"
PUBLIC_HOST="${PUBLIC_HOST:-your-host-or-ip}"
WEB_PORT="${WEB_PORT:-28681}"
SUBPATH="${SUBPATH:-/smart-home/}"
NGINX_SITE_FILE="${NGINX_SITE_FILE:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
APP_USER="${APP_USER:-${SUDO_USER:-$(id -un)}}"
APP_GROUP="${APP_GROUP:-$(id -gn "$APP_USER")}"
APP_WORKERS="${APP_WORKERS:-2}"

run_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

require_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1"
        exit 1
    fi
}

require_file() {
    if [ ! -f "$1" ]; then
        echo "Missing required file: $1"
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

escape_sed_replacement() {
    printf '%s' "$1" | sed -e 's/[&|]/\\&/g'
}

render_template_to_root() {
    local template_file="$1"
    local output_file="$2"
    local smart_home_path="${SUBPATH%/}"
    local escaped_app_user
    local escaped_app_group
    local escaped_backend_dir
    local escaped_web_port
    local escaped_workers
    local escaped_subpath
    local escaped_smart_home_path

    escaped_app_user="$(escape_sed_replacement "$APP_USER")"
    escaped_app_group="$(escape_sed_replacement "$APP_GROUP")"
    escaped_backend_dir="$(escape_sed_replacement "$BACKEND_DIR")"
    escaped_web_port="$(escape_sed_replacement "$WEB_PORT")"
    escaped_workers="$(escape_sed_replacement "$APP_WORKERS")"
    escaped_subpath="$(escape_sed_replacement "$SUBPATH")"
    escaped_smart_home_path="$(escape_sed_replacement "$smart_home_path")"

    sed \
        -e "s|__APP_USER__|$escaped_app_user|g" \
        -e "s|__APP_GROUP__|$escaped_app_group|g" \
        -e "s|__BACKEND_DIR__|$escaped_backend_dir|g" \
        -e "s|__WEB_PORT__|$escaped_web_port|g" \
        -e "s|__GUNICORN_WORKERS__|$escaped_workers|g" \
        -e "s|__SMART_HOME_PATH__|$escaped_smart_home_path|g" \
        -e "s|__SMART_HOME_SUBPATH__|$escaped_subpath|g" \
        -e "s|__SMART_HOME_PORT__|$escaped_web_port|g" \
        "$template_file" | run_root tee "$output_file" >/dev/null
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

    run_root mkdir -p /etc/nginx/snippets
    render_template_to_root "$NGINX_TEMPLATE" "$snippet_file"

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
        echo "Could not find a server block in $site_file for auto-inserting the include."
        echo "Please add /etc/nginx/snippets/${SERVICE_NAME}.conf to the correct server block manually."
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
require_file "$SYSTEMD_TEMPLATE"
require_file "$NGINX_TEMPLATE"

if [ "$(id -u)" -ne 0 ]; then
    require_cmd sudo
fi

SUBPATH="$(normalize_subpath "$SUBPATH")"

if [ ! -d "$BACKEND_DIR" ]; then
    echo "Could not find backend directory: $BACKEND_DIR"
    exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "Created $BACKEND_DIR/.env"
    echo "Please update MQTT_HOST, MQTT_USERNAME, and MQTT_PASSWORD, then rerun this script."
    exit 1
fi

if grep -Eq '^MQTT_HOST=your-emqx-host$|^MQTT_USERNAME=your-mqtt-username$|^MQTT_PASSWORD=your-mqtt-password$' "$BACKEND_DIR/.env"; then
    echo "$BACKEND_DIR/.env still contains placeholder MQTT values. Update them before rerunning."
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
render_template_to_root "$SYSTEMD_TEMPLATE" "$SYSTEMD_FILE"

if ! NGINX_SITE_FILE="$(detect_nginx_site_file)"; then
    echo "Could not detect an nginx site file automatically."
    echo "Set NGINX_SITE_FILE=/etc/nginx/sites-available/<your-site-file> and rerun."
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
echo "Deployment complete."
echo "Project directory: $ROOT_DIR"
echo "Backend directory: $BACKEND_DIR"
echo "systemd service: $SERVICE_NAME"
echo "Nginx site file: $NGINX_SITE_FILE"
echo "Local health check: http://127.0.0.1:$WEB_PORT/api/health"
echo "Public entry point: http://$PUBLIC_HOST${SUBPATH}"
