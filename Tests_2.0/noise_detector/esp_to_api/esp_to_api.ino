// esp_to_api.ino
// -----------------------------------------------------------------------------
// ESP32 bridge: reads a single line from Teensy over UART and POSTs JSON to API.
// Expected line from Teensy on *event end*:
//
//   NOISE <duration_ms> <peak_dbfs>\n
//
// Example: "NOISE 1234 -12.34"
//
// The ESP32 stamps current epoch seconds (NTP) and sends:
// {
//   "device_id": "esp32-01",
//   "duration_ms": <int>,
//   "peak_dbfs": <float>,
//   "esp_epoch": <int seconds>
// }
//
// Keeps your Wi-Fi credentials, API host, and API key unchanged.
// -----------------------------------------------------------------------------

#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>

// ---- Wi-Fi + API (unchanged) -----------------------------------------------
const char* WIFI_SSID = "Your Info";
const char* WIFI_PASS = "Your Info";

const char* API_HOST = "Your Info";  // your PC's LAN IP
const uint16_t API_PORT = 8000;
const char* API_PATH = "/noise";
const char* API_KEY  = "1234";

// Identify this device in the DB
const char* DEVICE_ID = "esp32-01";

// ---- Teensy link (UART1 on your chosen pins) --------------------------------
// Teensy D1 (TX1) -> RX_GPIO, Teensy D0 (RX1) <- TX_GPIO (TX optional)
#define RX_GPIO 38
#define TX_GPIO 37
HardwareSerial Link(1);

// ---- Activity LED (optional) ------------------------------------------------
#define LED_PIN 13
#define LED_ACTIVE_LOW false
inline void led_on()  { digitalWrite(LED_PIN, LED_ACTIVE_LOW ? LOW  : HIGH); }
inline void led_off() { digitalWrite(LED_PIN, LED_ACTIVE_LOW ? HIGH : LOW ); }

// ---- Utilities --------------------------------------------------------------
static void ensureWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi: connecting");
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.printf("\nWiFi: connected, IP=%s\n", WiFi.localIP().toString().c_str());
}

// Parse "NOISE <duration_ms> <peak_dbfs>"
static bool parseNOISE(const String& line, long& out_dur_ms, float& out_peak_dbfs) {
  if (!line.startsWith("NOISE")) return false;
  int s1 = line.indexOf(' ');
  if (s1 < 0) return false;
  int s2 = line.indexOf(' ', s1 + 1);
  if (s2 < 0) return false;
  out_dur_ms    = line.substring(s1 + 1, s2).toInt();
  out_peak_dbfs = line.substring(s2 + 1).toFloat();
  return out_dur_ms > 0;
}

// POST the event to your FastAPI server
static int postNoise(long duration_ms, float peak_dbfs) {
  ensureWifi();

  WiFiClient client;
  HTTPClient http;
  http.setConnectTimeout(7000);

  if (!http.begin(client, API_HOST, API_PORT, API_PATH)) {
    Serial.println("ERROR: http.begin() failed");
    return -1000;
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);

  time_t nowSecs = time(NULL);
  String body = String("{")
              + "\"device_id\":\"" + String(DEVICE_ID) + "\","
              + "\"duration_ms\":"   + String(duration_ms) + ","
              + "\"peak_dbfs\":"     + String(peak_dbfs, 2) + ","
              + "\"esp_epoch\":"     + String((long)nowSecs)
              + "}";

  int code = http.POST(body);
  Serial.printf("POST %d (%s) :: %s\n", code, HTTPClient::errorToString(code).c_str(), body.c_str());
  http.end();
  return code;
}

// ---- Arduino lifecycle ------------------------------------------------------
void setup() {
  Serial.begin(115200);
  Link.begin(115200, SERIAL_8N1, RX_GPIO, TX_GPIO);

  pinMode(LED_PIN, OUTPUT);
  led_off();

  // NTP for accurate timestamps (UTC offset 0; adjust on server if needed)
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  ensureWifi();

  Serial.println("ESP32 noise forwarder ready.");
  Serial.printf("API: http://%s:%u%s  device_id=%s\n", API_HOST, API_PORT, API_PATH, DEVICE_ID);
}

void loop() {
  if (!Link.available()) { delay(5); return; }

  // Read one complete line from Teensy
  String line = Link.readStringUntil('\n');
  line.trim();
  if (!line.length()) return;

  long dur_ms = 0;
  float peak = 0.0f;
  if (!parseNOISE(line, dur_ms, peak)) {
    Serial.printf("WARN: could not parse line: %s\n", line.c_str());
    return;
  }

  led_on();
  int code = postNoise(dur_ms, peak);
  if (code > 0 && code < 400) {
    Serial.printf("OK -> API (dur=%ld ms, peak=%.2f dBFS)\n", dur_ms, peak);
  } else {
    Serial.printf("ERROR: API send failed (code=%d, %s)\n", code, HTTPClient::errorToString(code).c_str());
  }
  led_off();
}
