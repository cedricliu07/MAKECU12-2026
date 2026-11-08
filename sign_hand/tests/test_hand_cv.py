"""Offline tests for hand measurement, judging and recognition (no camera)."""
import numpy as np

import hand_cv as hc
from hand_cv import SHAPES, Calibration, features, judge, recognize


def _flat_hand():
    """21x3 landmarks: open hand, palm facing camera, fingers straight up."""
    w = np.zeros((21, 3), dtype=float)
    w[0] = [0.0, 0.0, 0.0]           # wrist
    # knuckles across the palm
    w[5], w[9], w[13], w[17] = [-0.02, 0.08, 0], [0.0, 0.09, 0], [0.02, 0.08, 0], [0.04, 0.07, 0]
    # straight fingers (tip above knuckle)
    for base, tip_y in ((5, 0.18), (9, 0.19), (13, 0.18), (17, 0.16)):
        for k, t in enumerate((0.33, 0.66, 1.0), start=1):
            w[base + k] = [w[base][0], w[base][1] + tip_y * t, 0.0]
    # thumb out to the side
    w[1], w[2], w[3], w[4] = [-0.02, 0.02, 0], [-0.04, 0.04, 0], [-0.06, 0.05, 0], [-0.08, 0.06, 0]
    return w


def _fist():
    """21x3 landmarks: closed fist (tips near palm)."""
    w = _flat_hand()
    for tip in (8, 12, 16, 20):
        kn = tip - 3
        w[tip] = w[kn] + [0.0, 0.01, 0.02]
        w[tip - 1] = w[kn] + [0.0, 0.015, 0.015]
        w[tip - 2] = w[kn] + [0.0, 0.02, 0.008]
    # thumb across
    w[4] = [0.01, 0.06, 0.02]
    w[3] = [0.0, 0.05, 0.015]
    w[2] = [-0.01, 0.04, 0.01]
    return w


def test_features_on_synthetic_hands():
    for world in (_flat_hand(), _fist()):
        feat = features(world)
        assert set(feat) >= {"bends", "reach", "touch_i", "touch_m", "spread"}
        assert set(feat["bends"]) == {"thumb", "index", "middle", "ring", "pinky"}
        for n, b in feat["bends"].items():
            assert np.isfinite(b), n
        for k in ("reach", "touch_i", "touch_m", "spread"):
            assert feat[k] > 0 and np.isfinite(feat[k])


def test_judge_passes_target_fails_wrong():
    letter = "L"
    curls = list(SHAPES[letter])
    feat = {"bends": {}, "reach": 1.0, "touch_i": 0.5, "touch_m": 0.5, "spread": 1.5}
    ok = judge(letter, curls, feat)
    assert ok["match"] is True
    assert ok["letter"] == letter
    assert ok["score"] >= 85
    bad = judge(letter, list(SHAPES["B"]), feat)
    assert bad["match"] is False
    assert bad["fix"]


def test_recognize_ranks_right_letter_first():
    # Contact-friendly features for U (together) and W (spread); others ignore contacts.
    feats = {
        "L": {"bends": {}, "reach": 1.1, "touch_i": 0.5, "touch_m": 0.5, "spread": 1.5},
        "Y": {"bends": {}, "reach": 1.1, "touch_i": 0.5, "touch_m": 0.5, "spread": 1.5},
        "B": {"bends": {}, "reach": 0.4, "touch_i": 0.5, "touch_m": 0.5, "spread": 1.2},
        "I": {"bends": {}, "reach": 0.4, "touch_i": 0.5, "touch_m": 0.5, "spread": 1.5},
        "W": {"bends": {}, "reach": 0.4, "touch_i": 0.5, "touch_m": 0.5, "spread": 2.0},
        "U": {"bends": {}, "reach": 0.4, "touch_i": 0.5, "touch_m": 0.5, "spread": 1.0},
    }
    for letter in ("L", "Y", "B", "I", "W", "U"):
        ranked, _ = recognize(list(SHAPES[letter]), feats[letter])
        assert ranked[0][0] == letter, f"expected {letter} first, got {ranked[:3]}"


def test_calibration_capture_curls_in_range():
    cal = Calibration()
    open_f = features(_flat_hand())
    fist_f = features(_fist())
    cal.capture(open_f, "open")
    cal.capture(fist_f, "fist")
    for feat in (open_f, fist_f):
        curls = cal.curls(feat)
        assert len(curls) == 5
        for c in curls:
            assert 0.0 <= c <= 100.0
