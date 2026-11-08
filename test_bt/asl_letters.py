import argparse
import asyncio

from ble_servo import send_command

FingerPositions = tuple[int, int, int, int, int]

# Servo order is thumb, index, middle, ring, pinky. Values are degrees:
# 0 is fully retracted and 180 is fully extended.
LETTER_POSITIONS: dict[str, FingerPositions] = {
    "A": (180, 0, 0, 0, 0),
    "B": (0, 180, 180, 180, 180),
    "C": (100, 100, 100, 100, 100),
    "D": (90, 180, 0, 0, 0),
    "E": (0, 0, 0, 0, 0),
    "F": (90, 90, 180, 180, 180),
    "G": (180, 180, 0, 0, 0),
    "H": (180, 180, 180, 0, 0),
    "I": (0, 0, 0, 0, 180),
    "J": (0, 0, 0, 0, 180),
    "K": (90, 180, 180, 0, 0),
    "L": (180, 180, 0, 0, 0),
    "M": (0, 0, 0, 0, 0),
    "N": (0, 0, 0, 0, 0),
    "O": (75, 75, 75, 75, 75),
    "P": (90, 180, 180, 0, 0),
    "Q": (180, 180, 0, 0, 0),
    "R": (0, 180, 180, 0, 0),
    "S": (0, 0, 0, 0, 0),
    "T": (0, 0, 0, 0, 0),
    "U": (0, 180, 180, 0, 0),
    "V": (0, 180, 180, 0, 0),
    "W": (0, 180, 180, 180, 0),
    "X": (0, 90, 0, 0, 0),
    "Y": (180, 0, 0, 0, 180),
    "Z": (0, 180, 0, 0, 0),
}

DYNAMIC_LETTERS = {"J", "Z"}

APPROXIMATION_NOTES = {
    "D": "Thumb-to-fingertip contact is not represented.",
    "E": "Thumb-over-curled-fingers placement is not represented.",
    "F": "Thumb-index contact is not represented.",
    "G": "Hand orientation is not represented.",
    "H": "Hand orientation and finger spacing are not represented.",
    "J": "The J movement is not represented; this is the I handshape.",
    "K": "Thumb contact and finger spacing are not represented.",
    "L": "Hand orientation is not represented.",
    "M": "Thumb tucked under three fingers is not represented.",
    "N": "Thumb tucked under two fingers is not represented.",
    "O": "Finger-to-thumb contact and curved finger shape are approximated.",
    "P": "This uses K's finger flexion; hand orientation is not represented.",
    "Q": "This uses G's finger flexion; hand orientation is not represented.",
    "R": "Crossed fingers are not represented.",
    "S": "Thumb-over-fingers placement is not represented.",
    "T": "Thumb-between-fingers placement is not represented.",
    "U": "Touching fingers are not represented.",
    "V": "Finger spacing is not represented.",
    "X": "The hooked index-finger shape is approximated with partial flexion.",
    "Z": "The Z movement is not represented; this is a static handshape only.",
}

FINGER_NAMES = ("thumb", "index", "middle", "ring", "pinky")


def get_letter_positions(letter: str) -> FingerPositions:
    """Return angles in thumb-to-pinky order for one static letter handshape."""
    normalized = letter.upper()
    if len(normalized) != 1 or normalized not in LETTER_POSITIONS:
        raise ValueError(f"Expected one letter from A to Z; got {letter!r}.")
    return LETTER_POSITIONS[normalized]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Show or send the approximate servo handshape for an ASL letter."
    )
    parser.add_argument("letter", help="one letter from A to Z")
    parser.add_argument(
        "--send",
        action="store_true",
        help="send the handshape to the ESP32 over BLE",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="BLE scan timeout in seconds when using --send",
    )
    args = parser.parse_args()

    try:
        positions = get_letter_positions(args.letter)
    except ValueError as error:
        parser.error(str(error))

    letter = args.letter.upper()
    print(f"{letter}: " + ", ".join(
        f"{finger}={angle}" for finger, angle in zip(FINGER_NAMES, positions)
    ))
    if letter in DYNAMIC_LETTERS:
        print("Note: the letter requires movement; this is only its static handshape.")
    if letter in APPROXIMATION_NOTES:
        print(f"Approximation: {APPROXIMATION_NOTES[letter]}")

    if args.send:
        command = "A," + ",".join(map(str, positions))
        asyncio.run(send_command(command, args.timeout))


if __name__ == "__main__":
    main()
