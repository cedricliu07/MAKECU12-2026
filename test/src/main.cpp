#include <Arduino.h>

// Send an angle (0-180) followed by newline in the 115200-baud serial monitor.
// UART is receive-only here so serial output cannot interfere with the servo.
// MG90S signal connects to ESP32 GPIO1 (TX0 / physical pin 41).
// Power the servo from a separate regulated 5 V supply and join its GND
// to an ESP32 GND. Do not power the servo from the ESP32 3.3 V pin.
const uint8_t SERVO_PIN = 18;
const uint8_t SERIAL_RX_PIN = 3; // UART0 RX; GPIO1 is reserved for servo PWM

const uint32_t SERVO_FREQUENCY_HZ = 50;
const uint8_t SERVO_RESOLUTION_BITS = 16;
const uint16_t SERVO_PERIOD_US = 20000;
const uint16_t SERVO_MIN_PULSE_US = 600;
const uint16_t SERVO_MAX_PULSE_US = 2300;
const uint8_t SERVO_MIN_ANGLE = 0;
const uint8_t SERVO_MAX_ANGLE = 180;

const uint8_t SERVO_LEDC_CHANNEL = 0;
char commandBuffer[8];
size_t commandLength = 0;
bool commandInvalid = false;

bool beginServoPwm()
{
#if ESP_ARDUINO_VERSION_MAJOR >= 3
	return ledcAttach(SERVO_PIN, SERVO_FREQUENCY_HZ, SERVO_RESOLUTION_BITS);
#else
	ledcSetup(SERVO_LEDC_CHANNEL, SERVO_FREQUENCY_HZ, SERVO_RESOLUTION_BITS);
	ledcAttachPin(SERVO_PIN, SERVO_LEDC_CHANNEL);
	return true;
#endif
}

void writeServoAngle(uint8_t angle)
{
	angle = constrain(angle, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE);
	const uint32_t pulseUs = map(
		angle, SERVO_MIN_ANGLE, SERVO_MAX_ANGLE,
		SERVO_MIN_PULSE_US, SERVO_MAX_PULSE_US);
	const uint32_t maxDuty = (1UL << SERVO_RESOLUTION_BITS) - 1;
	const uint32_t duty = pulseUs * maxDuty / SERVO_PERIOD_US;

#if ESP_ARDUINO_VERSION_MAJOR >= 3
	ledcWrite(SERVO_PIN, duty);
#else
	ledcWrite(SERVO_LEDC_CHANNEL, duty);
#endif
}

void acceptAngleCommand()
{
	if (commandLength > 0 && !commandInvalid)
	{
		commandBuffer[commandLength] = '\0';
		char *end = nullptr;
		const long angle = strtol(commandBuffer, &end, 10);
		if (*end == '\0' && angle >= SERVO_MIN_ANGLE && angle <= SERVO_MAX_ANGLE)
		{
			writeServoAngle(static_cast<uint8_t>(angle));
			Serial.print("angle ");
			Serial.println(angle);
		}
	}
	commandLength = 0;
	commandInvalid = false;
}

void readAngleCommands()
{
	while (Serial.available() > 0)
	{
		const char input = static_cast<char>(Serial.read());

		if (input == '\r' || input == '\n')
		{
			acceptAngleCommand();
		}
		else if (!commandInvalid)
		{
			if (input >= '0' && input <= '9' &&
				commandLength < sizeof(commandBuffer) - 1)
			{
				commandBuffer[commandLength++] = input;
			}
			else
			{
				commandInvalid = true;
			}
		}
	}
}

void setup()
{
	Serial.begin(115200);

	if (!beginServoPwm())
	{
		while (true)
			delay(1000);
	}

	writeServoAngle(90);
}

void loop()
{
	readAngleCommands();
}
