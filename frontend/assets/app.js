const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const logOutput = document.getElementById("log-output");
const deviceLed = document.getElementById("device-led");
const deviceIp = document.getElementById("device-ip");
const deviceReason = document.getElementById("device-reason");
const deviceClientId = document.getElementById("device-client-id");
const refreshButton = document.getElementById("refresh-button");
const commandButtons = document.querySelectorAll("[data-command]");
const apiBaseUrl = new URL("api/", window.location.href);

function setBusy(isBusy) {
  refreshButton.disabled = isBusy;
  commandButtons.forEach((button) => {
    button.disabled = isBusy;
  });
}

function setStatusPill(ok, text) {
  statusDot.classList.remove("online", "offline");
  statusDot.classList.add(ok ? "online" : "offline");
  statusText.textContent = text;
}

function writeLog(data) {
  logOutput.textContent = JSON.stringify(data, null, 2);
}

function updateDeviceInfo(response) {
  const parsed = response?.status?.parsed;

  if (!parsed) {
    deviceLed.textContent = "未知";
    deviceIp.textContent = "-";
    deviceReason.textContent = "-";
    deviceClientId.textContent = "-";
    return;
  }

  deviceLed.textContent = parsed.led ?? "未知";
  deviceIp.textContent = parsed.ip ?? "-";
  deviceReason.textContent = parsed.reason ?? "-";
  deviceClientId.textContent = parsed.client_id ?? "-";
}

async function callApi(url, options = {}) {
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
    ...options,
  });

  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `请求失败，状态码 ${response.status}`);
  }

  return data;
}

async function fetchStatus() {
  setBusy(true);
  try {
    const data = await callApi(new URL("device/status", apiBaseUrl));
    setStatusPill(true, "设备在线，状态已更新");
    updateDeviceInfo(data);
    writeLog(data);
  } catch (error) {
    setStatusPill(false, `连接失败: ${error.message}`);
    writeLog({ ok: false, error: error.message });
  } finally {
    setBusy(false);
  }
}

async function sendCommand(command) {
  setBusy(true);
  try {
    const data = await callApi(new URL("device/command", apiBaseUrl), {
      method: "POST",
      body: JSON.stringify({ command, wait_for_status: true }),
    });
    setStatusPill(true, `命令 ${command} 已发送`);
    updateDeviceInfo(data);
    writeLog(data);
  } catch (error) {
    setStatusPill(false, `命令失败: ${error.message}`);
    writeLog({ ok: false, command, error: error.message });
  } finally {
    setBusy(false);
  }
}

refreshButton.addEventListener("click", fetchStatus);
commandButtons.forEach((button) => {
  button.addEventListener("click", () => {
    sendCommand(button.dataset.command);
  });
});

fetchStatus();
