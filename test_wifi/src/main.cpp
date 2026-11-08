#include <Arduino.h>
#include <ESP32Servo.h>
#include <WebServer.h>
#include <WiFi.h>
#include <stdlib.h>

namespace
{

	constexpr uint8_t SERVO_COUNT = 5;
	const uint8_t SERVO_PINS[SERVO_COUNT] = {18, 19, 21, 22, 23};
	constexpr int SERVO_MIN_ANGLE = 0;
	constexpr int SERVO_MAX_ANGLE = 180;
	constexpr int START_ANGLE = 90;

	const char *const AP_SSID = "ESP32-Servo-Controller";
	const char *const AP_PASSWORD = "servo1234";

	Servo servos[SERVO_COUNT];
	int servoAngles[SERVO_COUNT];
	WebServer server(80);

	void sendError(int statusCode, const char *message)
	{
		String response = "{\"error\":\"";
		response += message;
		response += "\"}";
		server.send(statusCode, "application/json", response);
	}

	bool parseAngle(const String &value, int &angle)
	{
		if (value.isEmpty())
		{
			return false;
		}

		char *end = nullptr;
		const long parsed = strtol(value.c_str(), &end, 10);
		if (end == value.c_str() || *end != '\0' ||
			parsed < SERVO_MIN_ANGLE || parsed > SERVO_MAX_ANGLE)
		{
			return false;
		}

		angle = static_cast<int>(parsed);
		return true;
	}

	bool parseServoAngles(const String &value, int (&angles)[SERVO_COUNT])
	{
		int start = 0;
		for (uint8_t i = 0; i < SERVO_COUNT; ++i)
		{
			const int comma = value.indexOf(',', start);
			const int end = (i == SERVO_COUNT - 1) ? value.length() : comma;
			if (end < 0 || (i < SERVO_COUNT - 1 && comma < 0))
			{
				return false;
			}

			if (!parseAngle(value.substring(start, end), angles[i]))
			{
				return false;
			}
			start = end + 1;
		}

		return start == value.length() + 1;
	}

	void setServoAngle(uint8_t index, int angle)
	{
		servos[index].write(angle);
		servoAngles[index] = angle;
	}

	void handleRoot()
	{
		server.send(
			200, "text/plain",
			"ESP32 servo controller\n"
			"POST /api/servo?index=0&angle=90  (index 0-4, angle 0-180)\n"
			"POST /api/servos?angles=90,90,90,90,90\n"
			"GET /api/status\n");
	}

	void handleSetOneServo()
	{
		if (!server.hasArg("index") || !server.hasArg("angle"))
		{
			sendError(400, "required parameters: index and angle");
			return;
		}

		int index = -1;
		int angle = -1;
		if (!parseAngle(server.arg("index"), index) || index >= SERVO_COUNT)
		{
			sendError(400, "index must be an integer from 0 to 4");
			return;
		}
		if (!parseAngle(server.arg("angle"), angle))
		{
			sendError(400, "angle must be an integer from 0 to 180");
			return;
		}

		setServoAngle(static_cast<uint8_t>(index), angle);
		server.send(200, "application/json", "{\"ok\":true}");
	}

	void handleSetAllServos()
	{
		if (!server.hasArg("angles"))
		{
			sendError(400, "required parameter: angles");
			return;
		}

		int angles[SERVO_COUNT];
		if (!parseServoAngles(server.arg("angles"), angles))
		{
			sendError(400, "angles must contain exactly five comma-separated integers from 0 to 180");
			return;
		}

		for (uint8_t i = 0; i < SERVO_COUNT; ++i)
		{
			setServoAngle(i, angles[i]);
		}
		server.send(200, "application/json", "{\"ok\":true}");
	}

	void handleStatus()
	{
		String response = "{\"angles\":[";
		for (uint8_t i = 0; i < SERVO_COUNT; ++i)
		{
			if (i > 0)
			{
				response += ',';
			}
			response += servoAngles[i];
		}
		response += "]}";
		server.send(200, "application/json", response);
	}

	void handleNotFound()
	{
		sendError(404, "route not found");
	}

} // namespace

void setup()
{
	Serial.begin(115200);

	ESP32PWM::allocateTimer(0);
	ESP32PWM::allocateTimer(1);
	ESP32PWM::allocateTimer(2);
	ESP32PWM::allocateTimer(3);

	for (uint8_t i = 0; i < SERVO_COUNT; ++i)
	{
		servos[i].setPeriodHertz(50);
		servos[i].attach(SERVO_PINS[i], 500, 2400);
		setServoAngle(i, START_ANGLE);
	}

	WiFi.mode(WIFI_AP);
	if (!WiFi.softAP(AP_SSID, AP_PASSWORD))
	{
		Serial.println("Failed to start Wi-Fi access point");
		while (true)
		{
			delay(1000);
		}
	}

	server.on("/", HTTP_GET, handleRoot);
	server.on("/api/servo", HTTP_POST, handleSetOneServo);
	server.on("/api/servos", HTTP_POST, handleSetAllServos);
	server.on("/api/status", HTTP_GET, handleStatus);
	server.onNotFound(handleNotFound);
	server.begin();

	Serial.print("Wi-Fi network: ");
	Serial.println(AP_SSID);
	Serial.print("HTTP server: http://");
	Serial.println(WiFi.softAPIP());
}

void loop()
{
	server.handleClient();
}
