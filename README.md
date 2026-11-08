# MAKECU12-2026

## Bluetooth servo test (`test_bt`)

This PlatformIO project runs on an ESP32 and advertises as
`ESP32-Servo-Controller`. It controls five servos on GPIO pins 18, 19, 21, 22,
and 23. On startup, all five servos move to 90 degrees.

### Build and flash

Open `test_bt` as the PlatformIO project, then build and upload to the connected
ESP32 (the configured environment is `esp32dev`). From the repository root, the
equivalent PlatformIO commands are:

```sh
pio run -d test_bt
pio run -d test_bt -t upload
```

### Send BLE commands

Install the Python BLE client dependency:

```sh
python -m pip install bleak
```

Run the client from the repository root:

```sh
python test_bt/ble_servo.py connect
```

The `connect` command scans for the controller, connects, and keeps the BLE
session open for multiple commands. At the `servo>` prompt, enter:

```text
servo <index> <angle>       Set one servo; index is 0-4 and angle is 0-180
all <a0> <a1> <a2> <a3> <a4> Set all five servos; each angle is 0-180
quit                        Disconnect
```

For example, `servo 0 45` sets the first servo to 45 degrees. The client also
supports one-shot commands, which connect, send the command, confirm the
response, and disconnect:

```sh
python test_bt/ble_servo.py servo 0 45
python test_bt/ble_servo.py all 90 90 90 90 90
```

The client scans for up to 10 seconds per attempt and retries a failed scan or
connection up to three times. Set a different scan timeout with
`--timeout <seconds>` before the subcommand. If the controller is not found,
check that it is powered and advertising and that Bluetooth is enabled.

### Run a repeating servo pattern

Run the existing script from the repository root:

```sh
python test_bt/pattern.py
```

It connects directly over BLE and sends different, smoothly changing angles to
all five servos every half second for 40 seconds. Press Ctrl+C to stop and
disconnect. The staggered phase (`servo * 1.1`) makes the servos follow
different positions rather than all moving together.

If the client connects but reports missing BLE characteristics, flash the
current `test_bt` firmware. If that firmware is already installed, remove the
ESP32 from Windows Bluetooth settings, restart the ESP32, and retry to clear a
possibly stale GATT cache.

### Map ASL letters to finger positions

The static letter lookup in `test_bt/asl_letters.py` returns five angles in
thumb-to-pinky order. Angles are degrees: `0` is fully retracted and `180` is
fully extended. For example:

```sh
python test_bt/asl_letters.py A
python test_bt/asl_letters.py A --send
```

The first command prints the five servo positions; `--send` also sends them to
the ESP32 over BLE. The lookup is an approximate finger-flexion model, not a
complete ASL handshape model: five independent servos cannot represent palm
orientation, finger spreading/crossing, or fingertip contact. J and Z require
movement, so their entries return only a static handshape, not the letter's
motion. Check the physical hand against fluent ASL references and tune the
angles before using it for communication.
