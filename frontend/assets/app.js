const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const logOutput = document.getElementById("log-output");
const deviceLed = document.getElementById("device-led");
const deviceIp = document.getElementById("device-ip");
const deviceReason = document.getElementById("device-reason");
const deviceClientId = document.getElementById("device-client-id");
const refreshButton = document.getElementById("refresh-button");
const commandButtons = document.querySelectorAll("[data-command]");
const cycleRefreshButton = document.getElementById("cycle-refresh-button");
const cycleStartButton = document.getElementById("cycle-start-button");
const cycleStopButton = document.getElementById("cycle-stop-button");
const cycleTotalHours = document.getElementById("cycle-total-hours");
const cycleOnMinutes = document.getElementById("cycle-on-minutes");
const cycleOffMinutes = document.getElementById("cycle-off-minutes");
const cycleStatus = document.getElementById("cycle-status");
const cyclePhase = document.getElementById("cycle-phase");
const cycleRemaining = document.getElementById("cycle-remaining");
const cycleNextSwitch = document.getElementById("cycle-next-switch");
const cycleStartedAt = document.getElementById("cycle-started-at");
const cycleEndsAt = document.getElementById("cycle-ends-at");
const apiBaseUrl = new URL("api/", window.location.href);
const cycleSettingsStorageKey = "smartHomeCycleSettings";
const cycleSettingInputs = [cycleTotalHours, cycleOnMinutes, cycleOffMinutes];

function getCycleSettingsPayload() {
  return {
    total_hours: cycleTotalHours.value,
    on_minutes: cycleOnMinutes.value,
    off_minutes: cycleOffMinutes.value,
  };
}

function saveCycleSettings() {
  try {
    window.localStorage.setItem(
      cycleSettingsStorageKey,
      JSON.stringify(getCycleSettingsPayload())
    );
  } catch (error) {
    console.warn("Unable to save cycle settings", error);
  }
}

function restoreCycleSettings() {
  let savedSettings = null;

  try {
    savedSettings = JSON.parse(window.localStorage.getItem(cycleSettingsStorageKey));
  } catch (error) {
    console.warn("Unable to restore cycle settings", error);
  }

  if (!savedSettings || typeof savedSettings !== "object") {
    return;
  }

  if (savedSettings.total_hours) {
    cycleTotalHours.value = savedSettings.total_hours;
  }

  if (savedSettings.on_minutes) {
    cycleOnMinutes.value = savedSettings.on_minutes;
  }

  if (savedSettings.off_minutes) {
    cycleOffMinutes.value = savedSettings.off_minutes;
  }
}

function setBusy(isBusy) {
  refreshButton.disabled = isBusy;
  cycleRefreshButton.disabled = isBusy;
  cycleStartButton.disabled = isBusy;
  cycleStopButton.disabled = isBusy;

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

function formatDateTime(timestamp) {
  if (!timestamp) {
    return "-";
  }

  const date = new Date(timestamp * 1000);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }

  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatDuration(seconds) {
  if (!seconds || seconds <= 0) {
    return "0 秒";
  }

  const totalSeconds = Math.round(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const remainSeconds = totalSeconds % 60;
  const parts = [];

  if (hours > 0) {
    parts.push(`${hours} 小时`);
  }

  if (minutes > 0) {
    parts.push(`${minutes} 分钟`);
  }

  if (remainSeconds > 0 || parts.length === 0) {
    parts.push(`${remainSeconds} 秒`);
  }

  return parts.join(" ");
}

function formatCyclePhase(phase) {
  if (phase === "on") {
    return "设备打开中";
  }

  if (phase === "off") {
    return "设备关闭中";
  }

  return "-";
}

function formatCycleStatus(cycle) {
  if (!cycle) {
    return "未启动";
  }

  if (cycle.active) {
    return "运行中";
  }

  if (cycle.status === "completed") {
    return "已完成";
  }

  if (cycle.status === "stopped") {
    return "已停止";
  }

  if (cycle.status === "failed") {
    return "执行失败";
  }

  return "未启动";
}

function updateCycleInfo(cycle) {
  cycleStatus.textContent = formatCycleStatus(cycle);
  cyclePhase.textContent = formatCyclePhase(cycle?.current_phase);
  cycleRemaining.textContent = cycle?.active ? formatDuration(cycle.remaining_seconds) : "-";
  cycleNextSwitch.textContent = cycle?.active ? formatDateTime(cycle.next_switch_at) : "-";
  cycleStartedAt.textContent = formatDateTime(cycle?.started_at);
  cycleEndsAt.textContent = formatDateTime(cycle?.ends_at);
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
    updateCycleInfo(data.cycle);
    writeLog(data);
  } catch (error) {
    setStatusPill(false, `命令失败: ${error.message}`);
    writeLog({ ok: false, command, error: error.message });
  } finally {
    setBusy(false);
  }
}

async function fetchCycleStatus({ showLog = false } = {}) {
  try {
    const data = await callApi(new URL("cycle", apiBaseUrl));
    updateCycleInfo(data.cycle);

    if (showLog) {
      writeLog(data);
    }
  } catch (error) {
    if (showLog) {
      writeLog({ ok: false, cycle: true, error: error.message });
    }
  }
}

async function startCycle() {
  setBusy(true);
  try {
    const payload = getCycleSettingsPayload();
    saveCycleSettings();
    const data = await callApi(new URL("cycle/start", apiBaseUrl), {
      method: "POST",
      body: JSON.stringify(payload),
    });
    updateCycleInfo(data.cycle);
    setStatusPill(true, "循环任务已启动");
    writeLog(data);
  } catch (error) {
    setStatusPill(false, `启动循环失败: ${error.message}`);
    writeLog({ ok: false, action: "cycle_start", error: error.message });
  } finally {
    setBusy(false);
  }
}

async function stopCycle() {
  setBusy(true);
  try {
    const data = await callApi(new URL("cycle/stop", apiBaseUrl), {
      method: "POST",
      body: JSON.stringify({}),
    });
    updateCycleInfo(data.cycle);
    setStatusPill(true, data.stop_requested ? "循环任务停止中" : "当前没有运行中的循环");
    writeLog(data);
  } catch (error) {
    setStatusPill(false, `停止循环失败: ${error.message}`);
    writeLog({ ok: false, action: "cycle_stop", error: error.message });
  } finally {
    setBusy(false);
  }
}

refreshButton.addEventListener("click", fetchStatus);
cycleRefreshButton.addEventListener("click", () => {
  fetchCycleStatus({ showLog: true });
});
cycleStartButton.addEventListener("click", startCycle);
cycleStopButton.addEventListener("click", stopCycle);

commandButtons.forEach((button) => {
  button.addEventListener("click", () => {
    sendCommand(button.dataset.command);
  });
});

cycleSettingInputs.forEach((input) => {
  input.addEventListener("input", saveCycleSettings);
  input.addEventListener("change", saveCycleSettings);
});

restoreCycleSettings();
fetchStatus();
fetchCycleStatus();
window.setInterval(() => {
  fetchCycleStatus();
}, 10000);
