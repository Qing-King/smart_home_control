# Firmware

这个目录用于收口设备端工程，方便和 `backend/` 一起维护。

当前包含：

- `esp8266/wifi_http_demo/`: ESP8266 RTOS SDK 固件工程，和后端共用同一套 MQTT 约定。

开发时请注意：

- 固件的 MQTT Host、用户名、密码、Topic Root 要和 `backend/.env` 保持一致。
- `esp8266/wifi_http_demo/` 里的 `sdkconfig` 是本地生成文件，不应该提交回仓库。
- Windows 下请优先阅读 `esp8266/wifi_http_demo/README.md`，里面已经整理了 MSYS2、`menuconfig` 和串口配置的注意事项。
