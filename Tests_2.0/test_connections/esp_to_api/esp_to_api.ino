// esp_to_api.ino
#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>

// -------------------- USER SETTINGS --------------------
const char* WIFI_SSID = "Your Info";
const char* WIFI_PASS = "Your Info";

// Prefer host/port/path form (robust parsing)
const char* API_HOST = "Your Info";  // <--- replace with your PC's LAN IP
const uint16_t API_PORT = 8000;
const char* API_PATH = "/events";
const char* API_KEY  = "1234";           // must match api.py
// -------------------------------------------------------

// Teensy link on UART1 (your pins: RX=38, TX=37)
#define RX_GPIO 38     // ESP32 RX (from Teensy D1 / TX1)
#define TX_GPIO 37     // ESP32 TX (to Teensy D0 / RX1) - optional
HardwareSerial Link(1);

// Built-in LED configuration
#define LED_PIN 13           // change to 2 if your board uses GPIO2
#define LED_ACTIVE_LOW false // set true if LOW turns the LED on

inline void led_on()  { digitalWrite(LED_PIN, LED_ACTIVE_LOW ? LOW  : HIGH); }
inline void led_off() { digitalWrite(LED_PIN, LED_ACTIVE_LOW ? HIGH : LOW ); }

void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi: connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.printf("\nWiFi: connected, IP=%s\n", WiFi.localIP().toString().c_str());
}

// Return HTTP status code (<0 on client errors)
int postEvent(const char* device_id, const char* state) {
  ensureWifi();

  WiFiClient client;             // explicit client object
  HTTPClient http;
  http.setConnectTimeout(7000);  // 7s connect timeout

  // Robust: begin with host/port/path
  if (!http.begin(client, API_HOST, API_PORT, API_PATH)) {
    Serial.println("ERROR: http.begin() failed");
    return -1000; // custom code
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);

  time_t nowSecs = time(NULL);
  String body = String("{\"device_id\":\"") + device_id +
                "\",\"state\":\"" + state +
                "\",\"esp_epoch\":" + String((long)nowSecs) + "}";

  int code = http.POST(body);

  // Always print raw outcome for visibility
  Serial.printf("POST %d (%s) :: %s\n",
                code, HTTPClient::errorToString(code).c_str(), body.c_str());

  http.end();
  return code;
}

void setup() {
  Serial.begin(115200);                                 // USB serial (flashing/monitor)
  Link.begin(115200, SERIAL_8N1, RX_GPIO, TX_GPIO);     // App UART on 38/37

  pinMode(LED_PIN, OUTPUT);
  led_off();

  configTime(0, 0, "pool.ntp.org", "time.nist.gov");    // optional: for esp_epoch
  ensureWifi();

  Serial.println("ESP32 ready.");
  Serial.printf("API target: %s:%u%s\n", API_HOST, API_PORT, API_PATH);
}

void loop() {
  // Expect lines like "LED_ON\n" or "LED_OFF\n" from Teensy
  if (Link.available()) {
    String msg = Link.readStringUntil('\n');
    msg.trim();

    // Apply LED change immediately
    if (msg == "LED_ON")  led_on();
    if (msg == "LED_OFF") led_off();

    // Send to API and report success/error
    int code = postEvent("esp32-s3-01", msg.c_str());
    if (code > 0 && code < 400) {
      Serial.printf("Received Teensy message '%s' — message to API successful\n", msg.c_str());
    } else {
      Serial.printf("ERROR: Could not connect/send to API (code=%d, %s)\n",
                    code, HTTPClient::errorToString(code).c_str());
    }
  }
}
