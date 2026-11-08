"""Offline tests for BLE angle mapping and stagger (no Bluetooth)."""
import ble_out
from ble_out import CLOSED_DEG, OPEN_DEG, STAGGER, BleOut, curl_to_angle


class FakeHand:
    def __init__(self, curls):
        self.curls = list(curls)

    def target_now(self):
        return "X", self.curls


def test_curl_to_angle_endpoints():
    for i in range(5):
        assert curl_to_angle(i, 0) == OPEN_DEG[i] == 180
        assert curl_to_angle(i, 100) == CLOSED_DEG[i] == 0
        assert curl_to_angle(i, -10) == 180
        assert curl_to_angle(i, 150) == 0


def test_angles_stagger_from_open_pose(monkeypatch):
    hand = FakeHand([100, 100, 100, 100, 100])   # all curled -> angle 0
    out = BleOut(hand)
    t0 = 1000.0
    monkeypatch.setattr(ble_out.time, "monotonic", lambda: t0)
    a0 = out._angles()
    # finger 0 moves immediately; 1..4 still at open (180)
    assert a0[0] == 0
    assert a0[1:] == [180, 180, 180, 180]

    monkeypatch.setattr(ble_out.time, "monotonic", lambda: t0 + STAGGER * 2 + 0.001)
    a2 = out._angles()
    assert a2[:3] == [0, 0, 0]
    assert a2[3:] == [180, 180]

    monkeypatch.setattr(ble_out.time, "monotonic", lambda: t0 + STAGGER * 4 + 0.001)
    assert out._angles() == [0, 0, 0, 0, 0]


def test_raw_override_returns_raw_angles(monkeypatch):
    hand = FakeHand([0, 0, 0, 0, 0])
    out = BleOut(hand)
    monkeypatch.setattr(ble_out.time, "monotonic", lambda: 0.0)
    out.set_raw([10, 20, 30, 40, 50])
    assert out._angles() == [10, 20, 30, 40, 50]
    out.clear_raw()
    # back to following the hand (open curls -> 180)
    assert out._angles() == [180, 180, 180, 180, 180]
