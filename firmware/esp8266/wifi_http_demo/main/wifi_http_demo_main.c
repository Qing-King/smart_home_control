#include <ctype.h>
#include <stdbool.h>
#include <stdio.h>
#include <strings.h>
#include <string.h>

#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_system.h"
#include "mqtt_client.h"
#include "sdkconfig.h"
#include "lwip/ip_addr.h"
#include "nvs_flash.h"
#include "protocol_examples_common.h"
#include "tcpip_adapter.h"

#define MQTT_TOPIC_BUFFER_SIZE 128
#define MQTT_CLIENT_ID_BUFFER_SIZE 48
#define MQTT_MESSAGE_BUFFER_SIZE 192

static const char *TAG = "wifi_mqtt_demo";
static bool s_led_is_on = false;
static esp_mqtt_client_handle_t s_mqtt_client = NULL;
static char s_mqtt_client_id[MQTT_CLIENT_ID_BUFFER_SIZE];
static char s_mqtt_command_topic[MQTT_TOPIC_BUFFER_SIZE];
static char s_mqtt_status_topic[MQTT_TOPIC_BUFFER_SIZE];
static const char *OFFLINE_LWT = "{\"status\":\"offline\"}";

extern const uint8_t digicert_global_root_g2_pem_start[] asm("_binary_digicert_global_root_g2_pem_start");

static void set_led_state(bool on)
{
    uint32_t output_level = on ? 1 : 0;

#ifdef CONFIG_WIFI_HTTP_DEMO_LED_ACTIVE_LOW
    output_level = on ? 0 : 1;
#endif

    ESP_ERROR_CHECK(gpio_set_level(CONFIG_WIFI_HTTP_DEMO_LED_GPIO, output_level));
    s_led_is_on = on;
}

static void configure_led(void)
{
    gpio_config_t io_conf = {
        .pin_bit_mask = BIT(CONFIG_WIFI_HTTP_DEMO_LED_GPIO),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };

    ESP_ERROR_CHECK(gpio_config(&io_conf));
    set_led_state(false);
    ESP_LOGI(TAG, "LED configured on GPIO%d (%s)",
             CONFIG_WIFI_HTTP_DEMO_LED_GPIO,
#ifdef CONFIG_WIFI_HTTP_DEMO_LED_ACTIVE_LOW
             "active-low"
#else
             "active-high"
#endif
    );
}

static esp_err_t parse_ipv4_config(const char *text, ip4_addr_t *address, const char *field_name)
{
    if (!ip4addr_aton(text, address)) {
        ESP_LOGE(TAG, "Invalid %s in sdkconfig: %s", field_name, text);
        return ESP_ERR_INVALID_ARG;
    }

    return ESP_OK;
}

static void configure_static_sta_network(void)
{
    tcpip_adapter_ip_info_t ip_info = { 0 };
    tcpip_adapter_dns_info_t dns_main = { 0 };
    tcpip_adapter_dns_info_t dns_backup = { 0 };
    esp_err_t err;

    ESP_ERROR_CHECK(parse_ipv4_config(CONFIG_WIFI_HTTP_DEMO_STATIC_IP,
                                      &ip_info.ip, "static IPv4 address"));
    ESP_ERROR_CHECK(parse_ipv4_config(CONFIG_WIFI_HTTP_DEMO_STATIC_NETMASK,
                                      &ip_info.netmask, "static netmask"));
    ESP_ERROR_CHECK(parse_ipv4_config(CONFIG_WIFI_HTTP_DEMO_STATIC_GATEWAY,
                                      &ip_info.gw, "static gateway"));
    ESP_ERROR_CHECK(parse_ipv4_config(CONFIG_WIFI_HTTP_DEMO_STATIC_DNS_MAIN,
                                      ip_2_ip4(&dns_main.ip), "primary DNS"));
    ESP_ERROR_CHECK(parse_ipv4_config(CONFIG_WIFI_HTTP_DEMO_STATIC_DNS_BACKUP,
                                      ip_2_ip4(&dns_backup.ip), "backup DNS"));

    err = tcpip_adapter_dhcpc_stop(TCPIP_ADAPTER_IF_STA);
    if (err != ESP_OK && err != ESP_ERR_TCPIP_ADAPTER_DHCP_ALREADY_STOPPED) {
        ESP_ERROR_CHECK(err);
    }

    ESP_ERROR_CHECK(tcpip_adapter_set_ip_info(TCPIP_ADAPTER_IF_STA, &ip_info));
    ESP_ERROR_CHECK(tcpip_adapter_set_dns_info(TCPIP_ADAPTER_IF_STA,
                                               TCPIP_ADAPTER_DNS_MAIN, &dns_main));
    ESP_ERROR_CHECK(tcpip_adapter_set_dns_info(TCPIP_ADAPTER_IF_STA,
                                               TCPIP_ADAPTER_DNS_BACKUP, &dns_backup));

    ESP_LOGI(TAG,
             "Static STA network configured: ip=" IPSTR " mask=" IPSTR
             " gw=" IPSTR " dns1=" IPSTR " dns2=" IPSTR,
             IP2STR(&ip_info.ip),
             IP2STR(&ip_info.netmask),
             IP2STR(&ip_info.gw),
             IP2STR(ip_2_ip4(&dns_main.ip)),
             IP2STR(ip_2_ip4(&dns_backup.ip)));
}

static bool get_current_lan_ip_string(char *buffer, size_t buffer_size)
{
    tcpip_adapter_ip_info_t ip_info = { 0 };
    esp_err_t err = tcpip_adapter_get_ip_info(TCPIP_ADAPTER_IF_STA, &ip_info);

    if (err != ESP_OK) {
        return false;
    }

    if (ip4_addr_isany_val(ip_info.ip)) {
        return false;
    }

    if (ip4addr_ntoa_r(&ip_info.ip, buffer, buffer_size) == NULL) {
        return false;
    }

    return true;
}

static void print_current_lan_ip(void)
{
    char ip_string[16] = { 0 };

    if (!get_current_lan_ip_string(ip_string, sizeof(ip_string))) {
        ESP_LOGW(TAG, "STA interface is up but no LAN IP is assigned yet");
        return;
    }

    ESP_LOGI(TAG, "Current LAN IP: %s", ip_string);
}

static void build_topic(char *buffer, size_t buffer_size, const char *suffix)
{
    int written;

    written = snprintf(buffer, buffer_size, "%s/%s",
                       CONFIG_WIFI_HTTP_DEMO_MQTT_TOPIC_ROOT, suffix);
    if (written < 0 || written >= buffer_size) {
        ESP_LOGE(TAG, "MQTT topic buffer too small for suffix '%s'", suffix);
        abort();
    }
}

static void prepare_mqtt_identity(void)
{
    uint8_t mac[6] = { 0 };
    int written;

    ESP_ERROR_CHECK(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    written = snprintf(s_mqtt_client_id, sizeof(s_mqtt_client_id), "%s-%02X%02X%02X",
                       CONFIG_WIFI_HTTP_DEMO_MQTT_CLIENT_ID_PREFIX,
                       mac[3], mac[4], mac[5]);
    if (written < 0 || written >= sizeof(s_mqtt_client_id)) {
        ESP_LOGE(TAG, "MQTT client ID buffer too small");
        abort();
    }

    build_topic(s_mqtt_command_topic, sizeof(s_mqtt_command_topic), "cmd");
    build_topic(s_mqtt_status_topic, sizeof(s_mqtt_status_topic), "status");

    ESP_LOGI(TAG, "MQTT client_id=%s", s_mqtt_client_id);
    ESP_LOGI(TAG, "MQTT command topic=%s", s_mqtt_command_topic);
    ESP_LOGI(TAG, "MQTT status topic=%s", s_mqtt_status_topic);
}

static char *trim_text(char *text)
{
    char *end;

    while (*text != '\0' && isspace((unsigned char)*text)) {
        ++text;
    }

    end = text + strlen(text);
    while (end > text && isspace((unsigned char) end[-1])) {
        --end;
    }
    *end = '\0';

    return text;
}

static bool copy_event_string(char *destination, size_t destination_size,
                              const char *source, int source_len)
{
    if (source_len < 0 || source_len >= destination_size) {
        return false;
    }

    memcpy(destination, source, source_len);
    destination[source_len] = '\0';
    return true;
}

static void publish_status(esp_mqtt_client_handle_t client, const char *reason)
{
    char ip_string[16] = { 0 };
    char payload[MQTT_MESSAGE_BUFFER_SIZE];
    int msg_id;
    int written;

    if (!get_current_lan_ip_string(ip_string, sizeof(ip_string))) {
        snprintf(ip_string, sizeof(ip_string), "%s", "0.0.0.0");
    }

    written = snprintf(payload, sizeof(payload),
                       "{\"client_id\":\"%s\",\"led\":\"%s\",\"ip\":\"%s\",\"reason\":\"%s\",\"status\":\"online\"}",
                       s_mqtt_client_id,
                       s_led_is_on ? "on" : "off",
                       ip_string,
                       reason);
    if (written < 0 || written >= sizeof(payload)) {
        ESP_LOGE(TAG, "MQTT status payload truncated");
        return;
    }

    msg_id = esp_mqtt_client_publish(client, s_mqtt_status_topic, payload, 0, 1, 1);
    ESP_LOGI(TAG, "Published status, msg_id=%d payload=%s", msg_id, payload);
}

static void handle_command(esp_mqtt_client_handle_t client, const char *command)
{
    if (strcasecmp(command, "on") == 0) {
        set_led_state(true);
        ESP_LOGI(TAG, "LED set to ON from MQTT");
        publish_status(client, "cmd_on");
        return;
    }

    if (strcasecmp(command, "off") == 0) {
        set_led_state(false);
        ESP_LOGI(TAG, "LED set to OFF from MQTT");
        publish_status(client, "cmd_off");
        return;
    }

    if (strcasecmp(command, "toggle") == 0) {
        set_led_state(!s_led_is_on);
        ESP_LOGI(TAG, "LED toggled from MQTT");
        publish_status(client, "cmd_toggle");
        return;
    }

    if (strcasecmp(command, "status") == 0) {
        ESP_LOGI(TAG, "Status requested from MQTT");
        publish_status(client, "cmd_status");
        return;
    }

    ESP_LOGW(TAG, "Unsupported MQTT command: %s", command);
}

static esp_err_t mqtt_event_handler_cb(esp_mqtt_event_handle_t event)
{
    esp_mqtt_client_handle_t client = event->client;
    char topic[MQTT_TOPIC_BUFFER_SIZE];
    char data[MQTT_MESSAGE_BUFFER_SIZE];
    char *command;
    int msg_id;

    switch (event->event_id) {
    case MQTT_EVENT_CONNECTED:
        ESP_LOGI(TAG, "MQTT_EVENT_CONNECTED");
        msg_id = esp_mqtt_client_subscribe(client, s_mqtt_command_topic, 1);
        ESP_LOGI(TAG, "Subscribed to %s, msg_id=%d", s_mqtt_command_topic, msg_id);
        publish_status(client, "connected");
        break;

    case MQTT_EVENT_DISCONNECTED:
        ESP_LOGW(TAG, "MQTT_EVENT_DISCONNECTED");
        break;

    case MQTT_EVENT_SUBSCRIBED:
        ESP_LOGI(TAG, "MQTT_EVENT_SUBSCRIBED, msg_id=%d", event->msg_id);
        break;

    case MQTT_EVENT_PUBLISHED:
        ESP_LOGI(TAG, "MQTT_EVENT_PUBLISHED, msg_id=%d", event->msg_id);
        break;

    case MQTT_EVENT_DATA:
        if (event->current_data_offset != 0 || event->total_data_len != event->data_len) {
            ESP_LOGW(TAG, "Ignoring fragmented MQTT payload on topic event");
            break;
        }

        if (!copy_event_string(topic, sizeof(topic), event->topic, event->topic_len) ||
            !copy_event_string(data, sizeof(data), event->data, event->data_len)) {
            ESP_LOGW(TAG, "Incoming MQTT topic or payload is too large");
            break;
        }

        ESP_LOGI(TAG, "MQTT_EVENT_DATA topic=%s data=%s", topic, data);
        if (strcmp(topic, s_mqtt_command_topic) != 0) {
            ESP_LOGW(TAG, "Ignoring message for unexpected topic: %s", topic);
            break;
        }

        command = trim_text(data);
        handle_command(client, command);
        break;

    case MQTT_EVENT_ERROR:
        ESP_LOGE(TAG, "MQTT_EVENT_ERROR");
        if (event->error_handle == NULL) {
            break;
        }

        if (event->error_handle->error_type == MQTT_ERROR_TYPE_ESP_TLS) {
            ESP_LOGE(TAG, "esp-tls last err=0x%x tls_stack=0x%x cert_flags=0x%x",
                     event->error_handle->esp_tls_last_esp_err,
                     event->error_handle->esp_tls_stack_err,
                     event->error_handle->esp_tls_cert_verify_flags);
        } else if (event->error_handle->error_type == MQTT_ERROR_TYPE_CONNECTION_REFUSED) {
            ESP_LOGE(TAG, "Broker refused connection, code=0x%x",
                     event->error_handle->connect_return_code);
        } else {
            ESP_LOGE(TAG, "Unknown MQTT error type=0x%x",
                     event->error_handle->error_type);
        }
        break;

    default:
        ESP_LOGI(TAG, "Unhandled MQTT event id=%d", event->event_id);
        break;
    }

    return ESP_OK;
}

static void mqtt_event_handler(void *handler_args, esp_event_base_t base,
                               int32_t event_id, void *event_data)
{
    (void) handler_args;
    (void) base;
    (void) event_id;
    mqtt_event_handler_cb(event_data);
}

static void start_mqtt_client(void)
{
    const esp_mqtt_client_config_t mqtt_cfg = {
        .uri = CONFIG_WIFI_HTTP_DEMO_MQTT_URI,
        .client_id = s_mqtt_client_id,
        .username = CONFIG_WIFI_HTTP_DEMO_MQTT_USERNAME,
        .password = CONFIG_WIFI_HTTP_DEMO_MQTT_PASSWORD,
        .cert_pem = (const char *) digicert_global_root_g2_pem_start,
        .lwt_topic = s_mqtt_status_topic,
        .lwt_msg = OFFLINE_LWT,
        .lwt_qos = 1,
        .lwt_retain = 1,
        .keepalive = 60,
    };

    ESP_LOGI(TAG, "Starting MQTT client for %s", CONFIG_WIFI_HTTP_DEMO_MQTT_URI);
    s_mqtt_client = esp_mqtt_client_init(&mqtt_cfg);
    ESP_ERROR_CHECK(s_mqtt_client == NULL ? ESP_FAIL : ESP_OK);
    ESP_ERROR_CHECK(esp_mqtt_client_register_event(s_mqtt_client, ESP_EVENT_ANY_ID,
                                                   mqtt_event_handler, s_mqtt_client));
    ESP_ERROR_CHECK(esp_mqtt_client_start(s_mqtt_client));
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    ESP_LOGI(TAG, "Starting Wi-Fi MQTT demo");
    ESP_LOGI(TAG, "Configure Wi-Fi credentials in menuconfig if needed");

    configure_led();
    configure_static_sta_network();
    ESP_ERROR_CHECK(example_connect());
    print_current_lan_ip();
    prepare_mqtt_identity();
    ESP_LOGI(TAG, "Publish MQTT commands to %s: on | off | toggle | status",
             s_mqtt_command_topic);
    ESP_LOGI(TAG, "Subscribe to %s to observe status updates", s_mqtt_status_topic);
    start_mqtt_client();
}
