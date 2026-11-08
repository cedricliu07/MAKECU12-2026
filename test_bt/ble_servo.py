import argparse
import asyncio

DEVICE_NAME = "ESP32-Servo-Controller"
COMMAND_UUID = "6a7c1001-3a5b-4f2e-9b41-4e8d2c10a001"
RESPONSE_UUID = "6a7c1002-3a5b-4f2e-9b41-4e8d2c10a001"


async def send_command(command: str, timeout: float) -> None:
    try:
        from bleak import BleakClient, BleakScanner
        from bleak.exc import BleakError
    except ImportError as error:
        raise SystemExit("Install the BLE client dependency with: python -m pip install bleak") from error

    last_error = None
    for attempt in range(3):
        device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=timeout)
        if device is None:
            last_error = TimeoutError(f"Could not find {DEVICE_NAME!r} while scanning.")
        else:
            try:
                async with BleakClient(device, timeout=timeout) as client:
                    await client.write_gatt_char(
                        COMMAND_UUID, command.encode("ascii"), response=True
                    )
                    response = (await client.read_gatt_char(RESPONSE_UUID)).decode(
                        "ascii", errors="replace"
                    )

                if response != "OK":
                    raise SystemExit(f"ESP32 rejected the command: {response}")
                print("Command accepted by the ESP32.")
                return
            except (BleakError, TimeoutError) as error:
                last_error = error

        if attempt < 2:
            print(f"BLE connection attempt {attempt + 1} failed; rescanning and retrying.")
            await asyncio.sleep(1.0)

    raise SystemExit(
        f"Could not send the command after 3 attempts: {last_error}\n"
        "Check that the ESP32 is powered and advertising. On Windows, turn "
        "Bluetooth off and on, then retry."
    )


def parse_interactive_command(line: str) -> str | None:
    parts = line.split()
    if not parts:
        return ""
    if parts[0].lower() in {"quit", "exit"} and len(parts) == 1:
        return None

    try:
        if len(parts) == 3 and parts[0].lower() == "servo":
            index, angle = (int(value) for value in parts[1:])
            if 0 <= index < 5 and 0 <= angle <= 180:
                return f"S,{index},{angle}"
        elif len(parts) == 6 and parts[0].lower() == "all":
            angles = [int(value) for value in parts[1:]]
            if all(0 <= angle <= 180 for angle in angles):
                return "A," + ",".join(str(angle) for angle in angles)
    except ValueError:
        pass

    print("Use: servo <index 0-4> <angle 0-180>, all <a0> <a1> <a2> <a3> <a4>, or quit")
    return ""


async def interactive(timeout: float) -> None:
    try:
        from bleak import BleakClient, BleakScanner
        from bleak.exc import BleakError
    except ImportError as error:
        raise SystemExit("Install the BLE client dependency with: python -m pip install bleak") from error

    last_error = None
    for attempt in range(3):
        device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=timeout)
        if device is None:
            last_error = TimeoutError(f"Could not find {DEVICE_NAME!r} while scanning.")
        else:
            try:
                async with BleakClient(device, timeout=timeout) as client:
                    print(f"Connected to {DEVICE_NAME}. Enter commands; type 'quit' to disconnect.")
                    print("Commands: servo <index> <angle> | all <a0> <a1> <a2> <a3> <a4>")
                    while client.is_connected:
                        try:
                            line = await asyncio.to_thread(input, "servo> ")
                        except EOFError:
                            break

                        command = parse_interactive_command(line)
                        if command is None:
                            break
                        if not command:
                            continue

                        await client.write_gatt_char(
                            COMMAND_UUID, command.encode("ascii"), response=True
                        )
                        response = (await client.read_gatt_char(RESPONSE_UUID)).decode(
                            "ascii", errors="replace"
                        )
                        if response == "OK":
                            print("Command accepted.")
                        else:
                            print(f"ESP32 response: {response}")
                    else:
                        print("BLE connection was lost.")
                return
            except (BleakError, TimeoutError) as error:
                last_error = error

        if attempt < 2:
            print(f"BLE connection attempt {attempt + 1} failed; rescanning and retrying.")
            await asyncio.sleep(1.0)

    raise SystemExit(
        f"Could not connect after 3 attempts: {last_error}\n"
        "Check that the ESP32 is powered and advertising. On Windows, turn "
        "Bluetooth off and on, then retry."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Send BLE commands to the ESP32 servo controller.")
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="BLE scan timeout in seconds"
    )
    commands = parser.add_subparsers(dest="operation", required=True)

    commands.add_parser("connect", help="stay connected and enter multiple commands")

    one = commands.add_parser("servo", help="set one servo")
    one.add_argument("index", type=int, choices=range(5), help="servo index (0-4)")
    one.add_argument("angle", type=int, choices=range(181), help="angle (0-180 degrees)")

    all_servos = commands.add_parser("all", help="set all five servos")
    all_servos.add_argument(
        "angles",
        type=int,
        nargs=5,
        choices=range(181),
        metavar=("A0", "A1", "A2", "A3", "A4"),
        help="five angles, each from 0 to 180 degrees",
    )

    args = parser.parse_args()
    if args.operation == "connect":
        try:
            asyncio.run(interactive(args.timeout))
        except KeyboardInterrupt:
            print("\nDisconnected.")
        return
    if args.operation == "servo":
        command = f"S,{args.index},{args.angle}"
    else:
        command = "A," + ",".join(str(angle) for angle in args.angles)

    asyncio.run(send_command(command, args.timeout))


if __name__ == "__main__":
    main()
