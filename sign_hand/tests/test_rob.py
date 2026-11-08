"""Tests for the Rob launcher helpers and /help (no subprocess, no ports)."""
import rob


def test_help_lists_commands():
    client = rob.app.test_client()
    r = client.get("/help")
    assert r.status_code == 200
    data = r.get_json()
    assert data["say"]
    assert "system" in data["commands"]
    assert "teaching" in data["commands"]
    assert "/teach/D" in data["commands"]["teaching"]
    assert "/start" in data["commands"]["system"]


def test_opts_from_query():
    # Isolate from whatever the live launcher may have set in a prior import.
    rob.current = {}
    with rob.app.test_request_context("/start?robot=dry&camera=2&sim=1&contacts=0"):
        o = rob.opts_from_query()
    assert o["robot"] == "dry"
    assert o["camera"] == 2
    assert o["sim"] is True
    assert o["contacts"] is False


def test_log_tail_strips_users_paths(tmp_path, monkeypatch):
    log = tmp_path / "rob.log"
    log.write_text(
        "ok line\n"
        "Error at /Users/someone/MAKECU12-2026/sign_hand/coach.py:12\n"
        "I0000 mediapipe noise\n"
        "another /Users/alice/proj/file.py detail\n"
    )
    monkeypatch.setattr(rob, "LOG", str(log))
    lines = rob.log_tail(10)
    assert any("Error" in l for l in lines)
    assert not any("/Users/" in l for l in lines)
    assert any("~/MAKECU12-2026" in l or "~/proj" in l for l in lines)
    assert not any(l.startswith("I0000") for l in lines)
