"""Bluetooth output for coach.py: drives Cedric's test_bt firmware.

The firmware only understands raw angles ("A,a0,a1,a2,a3,a4", 0-180). All the
smarts (letter shapes, holding, spelling timing, smoothing) stay on the laptop:
this thread follows the same target as the on-screen DigitalHand and streams
eased angles ~25 times a second, only when something changed.

Finger order everywhere: thumb, index, middle, ring, pinky = servo 0..4
(pins 18, 19, 21, 22, 23 in test_bt).
"""
import asyncio
import threading
import time

DEVICE_NAME = "ESP32-Servo-Controller"
SERVICE_UUID = "6a7c1000-3a5b-4f2e-9b41-4e8d2c10a001"
COMMAND_UUID = "6a7c1001-3a5b-4f2e-9b41-4e8d2c10a001"

# ===== CALIBRATE on the real hand (GET /raw/... helps, see README) =====
# Servo angle when the finger is fully STRAIGHT (curl 0) and fully CURLED (curl 100).
# test_bt convention: 180 = fully extended, 0 = fully retracted (asl_letters.py);
# the firmware already reverses ring + pinky, so all five use the same direction here.
OPEN_DEG = [180, 180, 180, 180, 180]
CLOSED_DEG = [0, 0, 0, 0, 0]
# =======================================================================

TICK = 0.04          # 25 Hz
STAGGER = 0.12       # s between fingers when the hand changes shape
EASE = 0.35          # fraction of the remaining distance per tick (smooth, fast)


def curl_to_angle(i, curl):
    curl = max(0.0, min(100.0, curl))
    return round(OPEN_DEG[i] + (CLOSED_DEG[i] - OPEN_DEG[i]) * curl / 100.0)


class BleOut:
    def __init__(self, hand, timeout=10.0):
        self.hand = hand            # DigitalHand: we read hand.target_now()
        self.timeout = timeout
        self.cur = [0.0] * 5        # our own eased curls (independent of camera fps)
        self.raw = None             # manual angle override from /raw (calibration)
        self.connected = False
        self.last_sent = None
        self.status = "starting"

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True).start()

    def set_raw(self, angles):
        self.raw = [max(0, min(180, int(a))) for a in angles]

    def clear_raw(self):
        self.raw = None

    def _angles(self):
        """Final pose only, one finger every STAGGER s (no 25 Hz easing stream).

        Streaming eased frames, or all five servos jumping at once, dropped the BLE link
        on the real hand (11-08). The servos move smoothly on their own; staggering cuts
        the current spike when the whole hand changes shape."""
        if self.raw is not None:
            return list(self.raw)
        _, tgt = self.hand.target_now()
        tgt = [curl_to_angle(i, c) for i, c in enumerate(tgt)]
        now = time.monotonic()
        if tgt != getattr(self, "_goal", None):
            self._goal, self._goal_at = tgt, now
            self._shown = list(getattr(self, "_shown", None) or OPEN_DEG)   # ESP32 boots open
        for i in range(5):
            if now - self._goal_at >= i * STAGGER:
                self._shown[i] = tgt[i]
        self.cur = [100 * (OPEN_DEG[i] - a) / max(1, OPEN_DEG[i] - CLOSED_DEG[i]) for i, a in enumerate(self._shown)]
        return list(self._shown)

    def _settled(self, a):
        """True once easing has (almost) reached the target: log one line per pose, not 25."""
        return self.raw is not None or a == getattr(self, "_goal", None)

    async def _main(self):
        from bleak import BleakClient, BleakScanner
        while True:
            self.status = f"scanning for {DEVICE_NAME}"
            print(f"[BLE] scanning for {DEVICE_NAME}...", flush=True)
            # match by name OR by the firmware's service UUID (macOS sometimes caches an old name)
            seen = await BleakScanner.discover(timeout=self.timeout, return_adv=True)
            dev, names = None, []
            for d, adv in seen.values():
                n = adv.local_name or d.name
                uuids = [u.lower() for u in adv.service_uuids]
                if n == DEVICE_NAME or SERVICE_UUID in uuids:
                    dev = d
                    break
                if n:
                    names.append(f"{n}({adv.rssi})")
            if dev is None:
                print(f"[BLE] ESP32 not found among {len(seen)} devices. Named ones nearby: "
                      f"{', '.join(sorted(names)[:12]) or 'none'}", flush=True)
                print("      -> ESP32 powered? test_bt flashed? Cedric's pattern.py/ble_servo.py closed?", flush=True)
                await asyncio.sleep(1)
                continue
            try:
                async with BleakClient(dev, timeout=self.timeout) as client:
                    self.connected, self.last_sent = True, None
                    self.status = "connected"
                    print(f"[BLE] connected to {DEVICE_NAME}. Hand is live.", flush=True)
                    sent_at = 0.0
                    while client.is_connected:
                        a = self._angles()
                        now = time.monotonic()
                        # send on change, and re-send the pose every second so a lost packet can't stick
                        if a != self.last_sent or now - sent_at > 1.0:
                            msg = "A," + ",".join(str(x) for x in a)
                            # write WITH response: the ESP32 confirms each one (macOS drops
                            # write-without-response packets when they come fast)
                            await client.write_gatt_char(COMMAND_UUID, msg.encode(), response=True)
                            if a != self.last_sent:
                                print(f"[BLE] -> {msg}", flush=True) if self._settled(a) else None
                            self.last_sent, sent_at = a, now
                        await asyncio.sleep(TICK)
                    print("[BLE] ESP32 disconnected. Reconnecting.", flush=True)
            except Exception as e:  # dropped link, GATT error, etc. -> rescan
                print(f"[BLE] link lost ({e}). Reconnecting.", flush=True)
            self.connected = False
            await asyncio.sleep(0.5)
