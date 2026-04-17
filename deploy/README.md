# Deploy Templates

These files are reusable templates for a new Linux host.

Files:
- `nginx/smart_home_control.conf`: snippet for the `server {}` block that serves your public host.
- `systemd/smart-home-control.service`: systemd unit template for Gunicorn.

Template placeholders:
- `__APP_USER__`: Linux user that runs the backend service.
- `__APP_GROUP__`: Linux group for the backend service.
- `__BACKEND_DIR__`: Absolute path to `smart_home_control/backend` on the target host.
- `__WEB_PORT__`: Internal Gunicorn port, for example `28681`.
- `__GUNICORN_WORKERS__`: Number of Gunicorn workers.
- `__SMART_HOME_PATH__`: Public path without a trailing slash, for example `/smart-home`.
- `__SMART_HOME_SUBPATH__`: Public path with a trailing slash, for example `/smart-home/`.
- `__SMART_HOME_PORT__`: Internal Gunicorn port used by nginx.

Quick start on a new machine:
1. Copy the project to the target host.
2. Create `backend/.env` from `backend/.env.example` and fill in the MQTT values.
3. Create `backend/.venv` and install `backend/requirements.txt`.
4. Replace the placeholders in the templates and install them manually, or run `./deploy_server.sh`.

Useful `deploy_server.sh` variables:
- `APP_USER`
- `APP_GROUP`
- `APP_WORKERS`
- `WEB_PORT`
- `SUBPATH`
- `PUBLIC_HOST`
- `NGINX_SITE_FILE`
