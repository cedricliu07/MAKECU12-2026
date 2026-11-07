// MAC FINDER - flash this on each ESP32 first.
// Open the serial monitor (115200) and write the address on a tape label.
#include <Arduino.h>
#include <WiFi.h>

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  delay(500);
}

void loop() {
  Serial.print("MAC address: ");
  Serial.println(WiFi.macAddress());
  delay(2000);
}
