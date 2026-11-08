"""Hand measurement + letter judging for the Rob coach.

Everything is described with the SAME 5 numbers the robot uses: how curled each finger
is (0 = straight, 100 = fully curled; thumb, index, middle, ring, pinky), plus a few
"contact" measurements that tell look-alike letters apart (O vs C, U vs V/W, F, D).

All measurements use MediaPipe's 3D *world* landmarks (metres, centred on the hand), so
they don't change when the hand moves around or turns a little, and work for either hand.
"""
import math
import numpy as np

FINGERS = ["thumb", "index", "middle", "ring", "pinky"]
NICE = {"thumb": "thumb", "index": "index finger", "middle": "middle finger",
        "ring": "ring finger", "pinky": "pinky"}

# Curl targets. KEEP IN SYNC with SHAPES in firmware/sign_hand/sign_hand.ino
SHAPES = {
    "A": [20, 100, 100, 100, 100], "B": [100, 0, 0, 0, 0],    "C": [40, 50, 50, 50, 50],
    "D": [70, 0, 80, 80, 80],      "E": [100, 80, 80, 80, 80], "F": [60, 70, 0, 0, 0],
    "I": [100, 100, 100, 100, 0],  "L": [0, 0, 100, 100, 100], "O": [60, 65, 65, 65, 65],
    "U": [100, 0, 0, 100, 100],    "W": [100, 0, 0, 0, 100],   "X": [100, 50, 100, 100, 100],
    "Y": [0, 100, 100, 100, 0],    "ILY": [0, 0, 100, 100, 0],
}
ALLOWED = set("ABCDEFILOUWXY")
TOL = [45, 32, 32, 32, 32]          # allowed difference per finger (thumb is hardest to read)

# Contact rules: (feature, "<" or ">", threshold, fix sentence). Features are ratios, so they
# don't depend on hand size. Lenient on purpose; turn off with --no-contacts if they misfire.
RULES = {
    "O": [("touch_i", "<", 0.34, "Close the O: touch your fingertips to your thumb.")],
    "F": [("touch_i", "<", 0.34, "Touch your index fingertip to your thumb.")],
    "D": [("touch_m", "<", 0.40, "Touch your thumb to your middle fingertip.")],
    "C": [("touch_i", ">", 0.36, "Leave a gap between your thumb and fingers, like a C.")],
    "U": [("spread", "<", 1.7, "Press your index and middle fingers together.")],
    "W": [("spread", ">", 1.4, "Spread your fingers apart.")],
}
USE_CONTACTS = True

CHAINS = {"thumb": [1, 2, 3, 4], "index": [0, 5, 6, 7, 8], "middle": [0, 9, 10, 11, 12],
          "ring": [0, 13, 14, 15, 16], "pinky": [0, 17, 18, 19, 20]}
HAND_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
              (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
              (18, 19), (19, 20), (0, 17)]
TIP = {"thumb": 4, "index": 8, "middle": 12, "ring": 16, "pinky": 20}


def _angle(u, v):
    c = np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9)
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def features(world):
    """world: 21x3 MediaPipe world landmarks -> raw measurements."""
    w = np.asarray(world, dtype=float)
    scale = np.linalg.norm(w[9] - w[0]) + 1e-9            # wrist -> middle knuckle
    bends = {n: sum(_angle(w[b] - w[a], w[c] - w[b]) for a, b, c in zip(ch, ch[1:], ch[2:]))
             for n, ch in CHAINS.items()}
    return {
        "bends": bends,
        "reach": float(np.linalg.norm(w[4] - w[17]) / scale),   # thumb tip -> pinky knuckle: big = thumb out
        "touch_i": float(np.linalg.norm(w[4] - w[8]) / scale),  # thumb tip -> index tip
        "touch_m": float(np.linalg.norm(w[4] - w[12]) / scale), # thumb tip -> middle tip
        "spread": float(np.linalg.norm(w[8] - w[12]) / (np.linalg.norm(w[5] - w[9]) + 1e-9)),
    }


class Calibration:
    """Maps raw bends to 0..100. 'open' = flat hand, 'fist' = closed fist (keys 1 / 2 or UI)."""
    def __init__(self):
        self.bend = {"thumb": [15, 85], "index": [10, 230], "middle": [10, 240],
                     "ring": [10, 240], "pinky": [10, 230]}
        self.reach = [1.15, 0.40]          # [open, closed]

    def capture(self, feat, which):
        k = 0 if which == "open" else 1
        for n in FINGERS:
            self.bend[n][k] = feat["bends"][n]
        self.reach[k] = feat["reach"]

    @staticmethod
    def _norm(x, rng):
        a, b = rng
        return 100.0 * float(np.clip((x - a) / ((b - a) if abs(b - a) > 1e-6 else 1e-6), 0, 1))

    def curls(self, feat):
        thumb = 0.7 * self._norm(feat["reach"], self.reach) + 0.3 * self._norm(feat["bends"]["thumb"], self.bend["thumb"])
        return [thumb] + [self._norm(feat["bends"][n], self.bend[n]) for n in FINGERS[1:]]


def _rule_ok(rule, feat):
    key, op, thr, _ = rule
    return feat[key] < thr if op == "<" else feat[key] > thr


def judge(letter, curls, feat):
    """Per-finger verdict for one target letter -> dict with match, score 0-100, fixes."""
    target = SHAPES[letter]
    fingers, problems = {}, []
    for i, n in enumerate(FINGERS):
        d = curls[i] - target[i]
        if abs(d) <= TOL[i]:
            fingers[n] = "ok"
        else:
            fingers[n] = "bend" if d < 0 else "straighten"
            how = (f"curl your {NICE[n]} down" if target[i] >= 70 else f"bend your {NICE[n]} a little") \
                if d < 0 else f"straighten your {NICE[n]}"
            sev = (abs(d) - TOL[i]) * (0.6 if n == "thumb" else 1.0)  # thumb reading is least reliable
            problems.append((sev, how))
    contacts = []
    if USE_CONTACTS and feat is not None:
        for r in RULES.get(letter, []):
            ok = _rule_ok(r, feat)
            contacts.append({"rule": r[3], "ok": ok, "value": round(feat[r[0]], 2)})
    finger_ok = all(v == "ok" for v in fingers.values())
    contact_ok = all(c["ok"] for c in contacts)
    closeness = sum(max(0.0, 1 - max(0.0, abs(curls[i] - target[i]) - TOL[i] * 0.4) / 100) for i in range(5)) / 5
    score = int(round(100 * closeness * (1.0 if contact_ok else 0.85)))
    problems.sort(reverse=True)
    if finger_ok and contact_ok:
        fix = "Perfect, hold it there!"
    elif finger_ok:
        fix = next(c["rule"] for c in contacts if not c["ok"])
    else:
        parts = [p[1] for p in problems[:2]]
        fix = parts[0][0].upper() + parts[0][1:] + (f", and {parts[1]}" if len(parts) > 1 else "") + "."
    return {"letter": letter, "match": finger_ok and contact_ok, "score": score, "fingers": fingers,
            "contacts": contacts, "fix": fix, "learner": [int(c) for c in curls], "target": target}


def recognize(curls, feat):
    """Which letter does the hand look like? -> [(letter, probability)] best first."""
    costs = {}
    for L, t in SHAPES.items():
        c = sum(((curls[i] - t[i]) / TOL[i]) ** 2 for i in range(5))
        if USE_CONTACTS and feat is not None:
            c += sum(2.0 for r in RULES.get(L, []) if not _rule_ok(r, feat))
        costs[L] = c
    m = min(costs.values())
    ex = {L: math.exp(-(c - m) / 2) for L, c in costs.items()}
    z = sum(ex.values())
    ranked = sorted(((L, ex[L] / z) for L in costs), key=lambda x: -x[1])
    return ranked, costs[ranked[0][0]]
