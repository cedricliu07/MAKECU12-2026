Three PlatformIO projects. Open ONE folder at a time in VS Code.

1. mac_finder  - flash on each ESP32, write its MAC on tape
2. user_node   - ESP32 #1 (wrist). Put the HAND board's MAC in HAND_MAC.
3. hand_node   - ESP32 #2 (servos). Put the USER board's MAC in USER_MAC.

Before powering servos: set the supply to 5-6 V, check with the DMM,
join grounds, and tune OPEN_ANGLE / CLOSED_ANGLE in hand_node.
The TouchTronix reader (readFingertipForce) is a stub until you know its interface.
