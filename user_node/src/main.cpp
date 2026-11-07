// USER NODE (worn on the wrist) - ESP32 #1
// - Reads the pressure pad (GPIO 34) and sends a "press level" to the hand node.
// - Receives "grip force" back and drives the vibration motor (TB6612FNG PWMA on GPIO 25).
// - Optional I2C OLED (SDA 21, SCL 22) shows both numbers.
//
// Wiring reminders:
//   Pad: one leg to 3V3, other leg to GPIO 34 AND through 10k to GND.
//   TB6612FNG: VCC+STBY+AIN1 to 3V3, AIN2 to GND, PWMA to GPIO 25, motor on AO1/AO2.
//
// Not compiled or tested on hardware - expect to tune the numbers below.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// ================== CONFIG: edit these ==================
uint8_t HAND_MAC[6] = {0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF};  // MAC of the HAND node (ESP32 #2)

const int   PAD_PIN          = 34;    // ADC1 pin
const int   MOTOR_PWM_PIN    = 25;    // TB6612FNG PWMA
const int   PAD_RAW_MAX      = 3000;  // raw ADC (0-4095) at a hard press - tune this
const float SMOOTH_ALPHA     = 0.2f;  // 0..1, lower = smoother (this is your tremor filter)
const int   PRESS_DEADBAND   = 30;    // ignore tiny signals (0..1000 scale)
const int   FORCE_DEADBAND   = 20;    // no buzz below this grip force (0..1000)
const int   VIB_MIN_DUTY     = 70;    // lowest PWM (0..255) that spins the motor - tune
const uint32_t LINK_TIMEOUT_MS = 500; // no message for this long = link lost
const bool  USE_OLED         = true;
// ========================================================

// Message format - MUST be identical on both nodes
typedef struct __attribute__((packed)) {
  uint16_t value;  // 0..1000
} LevelMsg;

Adafruit_SSD1306 display(128, 64, &Wire, -1);
bool oledOk = false;

volatile uint16_t gripForce = 0;     // received from hand node
volatile uint32_t lastForceMs = 0;
int   pressLevel = 0;                // 0..1000, sent to hand node
float smoothed = 0, baseline = 0;

// PWM works differently on Arduino-ESP32 core v2 vs v3
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  #define PWM_SETUP()  ledcAttach(MOTOR_PWM_PIN, 5000, 8)
  #define PWM_WRITE(v) ledcWrite(MOTOR_PWM_PIN, (v))
#else
  #define PWM_SETUP()  do { ledcSetup(0, 5000, 8); ledcAttachPin(MOTOR_PWM_PIN, 0); } while (0)
  #define PWM_WRITE(v) ledcWrite(0, (v))
#endif

// Receive callback signature also differs between core versions
#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
#else
void onRecv(const uint8_t *mac, const uint8_t *data, int len) {
#endif
  if (len != (int)sizeof(LevelMsg)) return;
  LevelMsg m;
  memcpy(&m, data, sizeof(m));
  gripForce = m.value;
  lastForceMs = millis();
}

void readPad() {
  float raw = analogRead(PAD_PIN);
  smoothed = SMOOTH_ALPHA * raw + (1.0f - SMOOTH_ALPHA) * smoothed;
  float span = max(1.0f, (float)PAD_RAW_MAX - baseline);
  int level = (int)((smoothed - baseline) * 1000.0f / span);
  level = constrain(level, 0, 1000);
  if (level < PRESS_DEADBAND) level = 0;
  pressLevel = level;
}

void sendPress() {
  LevelMsg m;
  m.value = (uint16_t)pressLevel;
  esp_now_send(HAND_MAC, (uint8_t *)&m, sizeof(m));
}

void updateMotor() {
  bool linkOk = (millis() - lastForceMs) < LINK_TIMEOUT_MS;
  int duty = 0;
  if (linkOk && gripForce > FORCE_DEADBAND) {
    duty = map((int)gripForce, FORCE_DEADBAND, 1000, VIB_MIN_DUTY, 255);
    duty = constrain(duty, 0, 255);
  }
  PWM_WRITE(duty);  // link lost or no grip = motor off
}

void drawOled() {
  if (!oledOk) return;
  bool linkOk = (millis() - lastForceMs) < LINK_TIMEOUT_MS;
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.print("Press ");
  display.print(pressLevel);
  display.drawRect(0, 10, 128, 10, SSD1306_WHITE);
  display.fillRect(0, 10, map(pressLevel, 0, 1000, 0, 128), 10, SSD1306_WHITE);
  display.setCursor(0, 28);
  display.print("Grip  ");
  display.print((int)gripForce);
  display.drawRect(0, 38, 128, 10, SSD1306_WHITE);
  display.fillRect(0, 38, map((int)gripForce, 0, 1000, 0, 128), 10, SSD1306_WHITE);
  display.setCursor(0, 56);
  display.print(linkOk ? "LINK OK" : "NO LINK");
  display.display();
}

void setup() {
  Serial.begin(115200);
  PWM_SETUP();
  PWM_WRITE(0);

  // Measure the pad's resting level (keep hands off for ~0.3 s at boot)
  long sum = 0;
  for (int i = 0; i < 50; i++) { sum += analogRead(PAD_PIN); delay(6); }
  baseline = sum / 50.0f;
  smoothed = baseline;

  if (USE_OLED) {
    Wire.begin(21, 22);
    oledOk = display.begin(SSD1306_SWITCHCAPVCC, 0x3C);  // try 0x3D if blank
    if (!oledOk) Serial.println("OLED not found - continuing without it");
  }

  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    while (true) delay(1000);
  }
  esp_now_register_recv_cb(onRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, HAND_MAC, 6);
  peer.channel = 0;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("Failed to add peer - check HAND_MAC");
  }

  Serial.println("press,force");  // CSV header for Zelos / plotting
}

void loop() {
  static uint32_t tSend = 0, tMotor = 0, tUi = 0;
  uint32_t now = millis();

  if (now - tSend >= 20) {   // 50 Hz
    tSend = now;
    readPad();
    sendPress();
  }
  if (now - tMotor >= 50) {  // 20 Hz
    tMotor = now;
    updateMotor();
  }
  if (now - tUi >= 100) {    // 10 Hz
    tUi = now;
    drawOled();
    Serial.print(pressLevel);
    Serial.print(",");
    Serial.println((int)gripForce);
  }
}
