from server.discovery.channels import CHANNELS
from server.discovery.doctor import run_doctor


def test_doctor_subset_never_raises():
    results = run_doctor(["fake", "agent_reach"])
    by_name = {h.channel: h for h in results}
    assert by_name["fake"].status == "ok"
    assert by_name["agent_reach"].status == "unconfigured"


def test_doctor_handles_crashing_health(monkeypatch):
    class Broken:
        name = "fake"

        def health(self):
            raise ConnectionError("boom")

    monkeypatch.setitem(CHANNELS, "fake", Broken)
    results = run_doctor(["fake"])
    assert results[0].status == "error"
    assert "boom" in results[0].detail
