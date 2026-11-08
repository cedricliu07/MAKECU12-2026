"""Flask test_client checks for coach routes (no camera, no network bind)."""
import coach


def setup_module():
    # Keep robot dry so send() never touches serial/BLE.
    coach.DRY = True
    coach.BLE = None
    coach.LIVE.camera_on = True
    coach.LIVE.camera_ok = True
    coach.LIVE.hand_seen_at = 0.0
    coach.LIVE.curls = None
    coach.LIVE.feat = None
    coach.LIVE.ranked = []
    coach.LIVE.verdict = None


def test_routes_return_200_and_say():
    client = coach.app.test_client()
    paths = [
        "/teach/L",
        "/check",
        "/see",
        "/spell/FOOD",
        "/quiz",
        "/guess/L",
        "/progress",
        "/ily",
        "/status",
    ]
    for path in paths:
        r = client.get(path)
        assert r.status_code == 200, path
        data = r.get_json()
        assert data is not None, path
        assert "say" in data and isinstance(data["say"], str) and data["say"].strip(), path
