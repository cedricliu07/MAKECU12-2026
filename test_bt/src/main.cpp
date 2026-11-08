#include <Arduino.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <ESP32Servo.h>
#include <stdlib.h>
#include <string>

namespace {

constexpr uint8_t SERVO_COUNT = 5;
const uint8_t SERVO_PINS[SERVO_COUNT] = {18, 19, 21, 22, 23};
constexpr int SERVO_MIN_ANGLE = 0;
constexpr int SERVO_MAX_ANGLE = 180;
constexpr int START_ANGLE = 90;

const char *const DEVICE_NAME = "ESP32-Servo-Controller";
const char *const SERVICE_UUID = "6a7c1000-3a5b-4f2e-9b41-4e8d2c10a001";
const char *const COMMAND_UUID = "6a7c1001-3a5b-4f2e-9b41-4e8d2c10a001";
const char *const RESPONSE_UUID = "6a7c1002-3a5b-4f2e-9b41-4e8d2c10a001";

Servo servos[SERVO_COUNT];
int commandAngles[SERVO_COUNT] = {START_ANGLE, START_ANGLE, START_ANGLE,
                                  START_ANGLE, START_ANGLE};
bool commandPending = false;
bool advertisingPending = false;
portMUX_TYPE commandMux = portMUX_INITIALIZER_UNLOCKED;
BLECharacteristic *responseCharacteristic = nullptr;
BLEServer *bleServer = nullptr;

bool parseUnsigned(const std::string &value, int maximum, int &parsed) {
  if (value.empty()) {
    return false;
  }

  for (const char digit : value) {
    if (digit < '0' || digit > '9') {
      return false;
    }
  }

  char *end = nullptr;
  const long number = strtol(value.c_str(), &end, 10);
  if (end == value.c_str() || *end != '\0' || number > maximum) {
    return false;
  }

  parsed = static_cast<int>(number);
  return true;
}

bool parseCommand(const std::string &value, bool &setAll, int (&parsed)[SERVO_COUNT],
                  int &servoIndex) {
  std::string fields[SERVO_COUNT + 1];
  uint8_t fieldCount = 0;
  size_t start = 0;

  while (start <= value.size()) {
    if (fieldCount >= SERVO_COUNT + 1) {
      return false;
    }

    const size_t comma = value.find(',', start);
    const size_t end = comma == std::string::npos ? value.size() : comma;
    fields[fieldCount++] = value.substr(start, end - start);
    if (comma == std::string::npos) {
      break;
    }
    start = comma + 1;
  }

  if (fields[0] == "S" && fieldCount == 3) {
    setAll = false;
    return parseUnsigned(fields[1], SERVO_COUNT - 1, servoIndex) &&
           parseUnsigned(fields[2], SERVO_MAX_ANGLE, parsed[0]);
  }

  if (fields[0] == "A" && fieldCount == SERVO_COUNT + 1) {
    setAll = true;
    for (uint8_t i = 0; i < SERVO_COUNT; ++i) {
      if (!parseUnsigned(fields[i + 1], SERVO_MAX_ANGLE, parsed[i])) {
        return false;
      }
    }
    return true;
  }

  return false;
}

class CommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic *characteristic) override {
    const String incoming = characteristic->getValue();
    const std::string value(incoming.c_str(), incoming.length());
    int parsed[SERVO_COUNT] = {};
    int servoIndex = -1;
    bool setAll = false;

    if (!parseCommand(value, setAll, parsed, servoIndex)) {
      responseCharacteristic->setValue(
          "ERR: use S,index,angle or A,a0,a1,a2,a3,a4 (angles 0-180)");
      return;
    }

    portENTER_CRITICAL(&commandMux);
    if (setAll) {
      for (uint8_t i = 0; i < SERVO_COUNT; ++i) {
        commandAngles[i] = parsed[i];
      }
    } else {
      commandAngles[servoIndex] = parsed[0];
    }
    commandPending = true;
    portEXIT_CRITICAL(&commandMux);

    responseCharacteristic->setValue("OK");
  }
};

class ServerCallbacks : public BLEServerCallbacks {
  void onDisconnect(BLEServer *) override {
    portENTER_CRITICAL(&commandMux);
    advertisingPending = true;
    portEXIT_CRITICAL(&commandMux);
  }
};

}  // namespace

void setup() {
  Serial.begin(115200);

  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  for (uint8_t i = 0; i < SERVO_COUNT; ++i) {
    servos[i].setPeriodHertz(50);
    servos[i].attach(SERVO_PINS[i], 500, 2400);
    servos[i].write(START_ANGLE);
  }

  BLEDevice::init(DEVICE_NAME);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new ServerCallbacks());
  BLEService *service = bleServer->createService(SERVICE_UUID);

  BLECharacteristic *commandCharacteristic = service->createCharacteristic(
      COMMAND_UUID, BLECharacteristic::PROPERTY_WRITE |
                        BLECharacteristic::PROPERTY_WRITE_NR);
  responseCharacteristic = service->createCharacteristic(
      RESPONSE_UUID, BLECharacteristic::PROPERTY_READ);
  responseCharacteristic->setValue("Ready");
  commandCharacteristic->setCallbacks(new CommandCallbacks());

  service->start();
  BLEAdvertising *advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->start();

  Serial.print("BLE device name: ");
  Serial.println(DEVICE_NAME);
  Serial.println("Commands: S,index,angle or A,a0,a1,a2,a3,a4");
}

void loop() {
  int angles[SERVO_COUNT];
  bool applyCommand = false;
  bool restartAdvertising = false;

  portENTER_CRITICAL(&commandMux);
  if (commandPending) {
    for (uint8_t i = 0; i < SERVO_COUNT; ++i) {
      angles[i] = commandAngles[i];
    }
    commandPending = false;
    applyCommand = true;
  }
  if (advertisingPending) {
    advertisingPending = false;
    restartAdvertising = true;
  }
  portEXIT_CRITICAL(&commandMux);

  if (restartAdvertising) {
    delay(250);
    bleServer->startAdvertising();
    Serial.println("BLE advertising restarted");
  }

  if (applyCommand) {
    for (uint8_t i = 0; i < SERVO_COUNT; ++i) {
      servos[i].write(angles[i]);
    }
    Serial.println("Applied BLE servo command");
  }

  delay(2);
}
