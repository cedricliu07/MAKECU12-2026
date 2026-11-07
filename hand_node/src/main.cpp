// HAND NODE (on the table) - ESP32 #2
// - Receives "press level" from the user node and closes the 3 prongs in proportion.
// - Reads the fingertip sensor and stops closing at FORCE_LIMIT.
// - Sends "grip force" back so the wristband can buzz.
// - Opens the prongs if the wireless link drops (failsafe).
//
// Servo signal pins: 18, 19, 23. Servos run from the separate 5-6 V supply,
// with that supply's GND joined to an ESP32 GND.
//
// Not compiled or tested on hardware. TUNE OPEN/CLOSED ANGLES BEFORE attaching
// the tendons or prongs, so a servo never pushes against a hard stop.

#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <ESP32Servo.h>

// ================== CONFIG: edit these ==================
uint8_t USER_MAC[6] = {0x11, 0x22, 0x33, 0x44, 0x55, 0x66};  // MAC of the USER node (ESP32 #1)

const int SERVO_PINS[3]    = {18, 19, 23};
// Angle at fully OPEN and fully CLOSED per prong. Closed can be lower than open
// (reversed servo). Start with a small range and widen it carefully.
const int OPEN_ANGLE[3]    = {30, 30, 30};
const int CLOSED_ANGLE[3]  = {110, 110, 110};

const int   PRESS_DEADBAND  = 30;    // ignore tiny presses (0..1000)
const float STEP_PER_TICK   = 25.0f; // max closeness change per 20 ms (smoothness)
const int   FORCE_LIMIT     = 600;   // stop closing at this fingertip force (0..1000)
const int   FORCE_HYST      = 80;    // above LIMIT+HYST the hand backs off slightly
const uint32_t LINK_TIMEOUT_MS = 500; // no message for this long = open the hand
// ========================================================

// Message format - MUST be identical on both nodes
typedef struct __attribute__((packed)) {
  uint16_t value;  // 0..1000
} LevelMsg;

Servo servos[3];

volatile uint16_t latestPress = 0;
volatile uint32_t lastPressMs = 0;
float closeness = 0;       // 0 = open, 1000 = fully closed
int   fingertipForce = 0;  // 0..1000
bool  sensorWarned = false;

// ---------------------------------------------------------------
// TOUCHTRONIX SENSOR - FILL THIS IN after reading the technical guide.
// Return a force-like number from 0 (no touch) to 1000 (hard press).
//
// If it is I2C:  include <Wire.h>, Wire.begin(21, 22), read its registers,
//                sum or max the 5x5 cells, scale to 0..1000.
// If it is UART: Serial2.begin(baud, SERIAL_8N1, 16, 17), parse its packets.
// If it is USB-only: this ESP32 cannot read it directly - use a laptop/Pi.
//
// Until you do, this returns 0 (so the force limit never triggers).
// ---------------------------------------------------------------
int readFingertipForce() {
  if (!sensorWarned) {
    Serial.println("WARNING: readFingertipForce() not implemented - force limit is OFF");
    sensorWarned = true;
  }
  return 0;
}

// Receive callback signature differs between Arduino-ESP32 core v2 and v3
#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
#else
void onRecv(const uint8_t *mac, const uint8_t *data, int len) {
#endif
  if (len != (int)sizeof(LevelMsg)) return;
  LevelMsg m;
  memcpy(&m, data, sizeof(m));
  latestPress = m.value;
  lastPressMs = millis();
}

void writeServos() {
  for (int i = 0; i < 3; i++) {
    float angle = OPEN_ANGLE[i] + (CLOSED_ANGLE[i] - OPEN_ANGLE[i]) * (closeness / 1000.0f);
    servos[i].write((int)angle);
  }
}

void sendForce() {
  LevelMsg m;
  m.value = (uint16_t)constrain(fingertipForce, 0, 1000);
  esp_now_send(USER_MAC, (uint8_t *)&m, sizeof(m));
}

void controlStep() {
  bool linkOk = (millis() - lastPressMs) < LINK_TIMEOUT_MS;
  int press = linkOk ? (int)latestPress : 0;     // link lost = target open
  if (press < PRESS_DEADBAND) press = 0;

  fingertipForce = readFingertipForce();

  float target = (float)press;                    // 0..1000 maps straight to closeness
  if (target > closeness) {
    // Closing: only allowed while below the force limit
    if (fingertipForce < FORCE_LIMIT) {
      closeness = min(target, closeness + STEP_PER_TICK);
    }
  } else {
    closeness = max(target, closeness - STEP_PER_TICK);  // opening is always allowed
  }

  // Squeezing too hard: back off a little
  if (fingertipForce > FORCE_LIMIT + FORCE_HYST) {
    closeness = max(0.0f, closeness - 10.0f);
  }

  writeServos();
}

void setup() {
  Serial.begin(115200);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);
  for (int i = 0; i < 3; i++) {
    servos[i].setPeriodHertz(50);
    servos[i].attach(SERVO_PINS[i], 500, 2400);  // MG90S pulse range in microseconds
  }
  writeServos();  // start open

  WiFi.mode(WIFI_STA);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init failed");
    while (true) delay(1000);
  }
  esp_now_register_recv_cb(onRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, USER_MAC, 6);
  peer.channel = 0;
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("Failed to add peer - check USER_MAC");
  }

  Serial.println("press,closeness,force");  // CSV header for Zelos / plotting
}

void loop() {
  static uint32_t tCtl = 0, tPrint = 0;
  uint32_t now = millis();

  if (now - tCtl >= 20) {    // 50 Hz control loop
    tCtl = now;
    controlStep();
    sendForce();
  }
  if (now - tPrint >= 100) { // 10 Hz serial output
    tPrint = now;
    Serial.print((int)latestPress);
    Serial.print(",");
    Serial.print((int)closeness);
    Serial.print(",");
    Serial.println(fingertipForce);
  }
}
