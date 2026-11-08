import asyncio
import importlib.util

from ble_servo import COMMAND_UUID, DEVICE_NAME, RESPONSE_UUID

SERVO_COUNT = 5
ALTERNATIONS = 5
STEP_DELAY = 0.1


async def run_pattern() -> None:
    if importlib.util.find_spec("bleak") is None:
        raise SystemExit(
            "The 'bleak' BLE dependency is missing from this Python environment.\n"
            "Install it with: python -m pip install bleak"
        )

    try:
        from bleak import BleakClient, BleakScanner
        from bleak.exc import BleakError
    except ImportError as error:
        raise SystemExit(
            "The 'bleak' BLE dependency could not be imported. "
            "Install it with: python -m pip install bleak"
        ) from error

    last_error: Exception | None = None
    last_phase = "scan"
    for attempt in range(3):
        connected = False
        phase = "scan"
        try:
            print(f"Scanning for {DEVICE_NAME} (attempt {attempt + 1}/3)...")
            device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
            if device is None:
                last_error = TimeoutError(f"Could not find {DEVICE_NAME!r} while scanning.")
                last_phase = phase
            else:
                phase = "connect"
                print(f"Found {DEVICE_NAME} at {device.address}; connecting...")
                async with BleakClient(device, timeout=10.0) as client:
                    connected = True
                    discovered = {
                        str(characteristic.uuid).lower()
                        for service in client.services
                        for characteristic in service.characteristics
                    }
                    expected = {COMMAND_UUID.lower(), RESPONSE_UUID.lower()}
                    if not expected.issubset(discovered):
                        services = "\n".join(
                            f"  {service.uuid}: "
                            f"{', '.join(str(item.uuid) for item in service.characteristics) or '(no characteristics)'}"
                            for service in client.services
                        )
                        raise SystemExit(
                            "Connected, but the ESP32 does not expose the expected "
                            "servo BLE characteristics.\n"
                            f"Missing: {', '.join(sorted(expected - discovered))}\n"
                            f"Discovered GATT services:\n{services or '  (none)'}\n"
                            "Flash the current test_bt firmware. If it is already "
                            "flashed, remove the ESP32 from Windows Bluetooth "
                            "settings, restart the ESP32, and try again."
                        )

                    print(f"Connected to {DEVICE_NAME}; running the servo pattern.")
                    phase = "command"
                    for servo in range(SERVO_COUNT):
                        print(f"Moving servo {servo} ({servo + 1}/{SERVO_COUNT})...")
                        for _ in range(ALTERNATIONS):
                            for angle in (0, 180):
                                command = f"S,{servo},{angle}"
                                await client.write_gatt_char(
                                    COMMAND_UUID,
                                    command.encode("ascii"),
                                    response=True,
                                )
                                response = (
                                    await client.read_gatt_char(RESPONSE_UUID)
                                ).decode("ascii", errors="replace")
                                if response != "OK":
                                    raise SystemExit(
                                        f"ESP32 rejected the command: {response}"
                                    )
                                await asyncio.sleep(STEP_DELAY)

                print(
                    f"All {SERVO_COUNT} servos alternated between 0 and 180 degrees "
                    f"{ALTERNATIONS} times in index order."
                )
                return
        except (BleakError, OSError, TimeoutError) as error:
            if connected:
                raise SystemExit(
                    f"BLE communication failed during {phase}; pattern stopped: "
                    f"{type(error).__name__}: {error!r}"
                ) from error
            last_error = error
            last_phase = phase

        if attempt < 2:
            if last_phase == "scan" and isinstance(last_error, TimeoutError):
                print(f"{DEVICE_NAME} was not found advertising.")
            else:
                print(
                    f"BLE {last_phase} failed: {type(last_error).__name__}: "
                    f"{last_error!r}"
                )
            print("Retrying...")
            await asyncio.sleep(1.0)

    raise SystemExit(
        f"Could not connect after 3 attempts ({last_phase}): "
        f"{type(last_error).__name__}: {last_error!r}\n"
        "Check that the ESP32 is powered and advertising. On Windows, turn "
        "Bluetooth off and on, then retry. Close any other app currently "
        "connected to the controller and retry."
    )


def main() -> None:
    try:
        asyncio.run(run_pattern())
    except KeyboardInterrupt:
        print("\nPattern stopped; disconnected.")


if __name__ == "__main__":
    main()
