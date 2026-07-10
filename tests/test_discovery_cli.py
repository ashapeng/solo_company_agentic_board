import json

from server.discovery.channels import CHANNELS
from server.discovery.channels.base import ChannelHealth
from server.discovery.cli import main


def _watchlist(tmp_path, text="fake:\n  - query: pain\n    label: unit\n"):
    p = tmp_path / "wl.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_fetch_writes_raw_and_manifest(tmp_path, capsys):
    wl = _watchlist(tmp_path)
    data = tmp_path / "data"
    rc = main(["fetch", "--watchlist", str(wl), "--data-dir", str(data), "--week", "2026-W28"])
    assert rc == 0
    raw = json.loads((data / "raw" / "2026-W28" / "fake-unit.json").read_text(encoding="utf-8"))
    assert len(raw) == 2
    manifest = json.loads((data / "raw" / "2026-W28" / "manifest.json").read_text(encoding="utf-8"))
    run = manifest["runs"][0]
    assert run["channel"] == "fake"
    assert run["new"] == 2
    assert run["error"] is None


def test_fetch_dedups_on_second_run(tmp_path):
    wl = _watchlist(tmp_path)
    data = tmp_path / "data"
    main(["fetch", "--watchlist", str(wl), "--data-dir", str(data), "--week", "2026-W28"])
    main(["fetch", "--watchlist", str(wl), "--data-dir", str(data), "--week", "2026-W29"])
    manifest = json.loads((data / "raw" / "2026-W29" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runs"][0]["new"] == 0


def test_fetch_channel_error_recorded_not_fatal(tmp_path):
    wl = _watchlist(
        tmp_path,
        "agent_reach:\n  - channel: twitter\n    label: tw\nfake:\n  - query: pain\n    label: unit\n",
    )
    data = tmp_path / "data"
    rc = main(["fetch", "--watchlist", str(wl), "--data-dir", str(data), "--week", "2026-W28"])
    assert rc == 0
    manifest = json.loads((data / "raw" / "2026-W28" / "manifest.json").read_text(encoding="utf-8"))
    by_channel = {r["channel"]: r for r in manifest["runs"]}
    assert by_channel["agent_reach"]["error"] is not None
    assert by_channel["fake"]["error"] is None


def test_fetch_error_redacts_secrets_in_manifest_and_stdout(tmp_path, monkeypatch, capsys):
    class LeakyChannel:
        name = "fake"

        def fetch(self, item):
            raise RuntimeError(
                "Client error '401 Unauthorized' for url "
                "'https://api.sam.gov/opportunities/v2/search?api_key=SECRET123&title=x'"
            )

        def health(self):
            return ChannelHealth("fake", "ok")

    monkeypatch.setitem(CHANNELS, "fake", LeakyChannel)
    wl = _watchlist(tmp_path)
    data = tmp_path / "data"
    rc = main(["fetch", "--watchlist", str(wl), "--data-dir", str(data), "--week", "2026-W28"])
    assert rc == 0
    manifest = json.loads((data / "raw" / "2026-W28" / "manifest.json").read_text(encoding="utf-8"))
    err = manifest["runs"][0]["error"]
    assert "SECRET123" not in err
    assert "api_key=REDACTED" in err
    out = capsys.readouterr().out
    assert "SECRET123" not in out


def test_doctor_command_prints_channels(tmp_path, capsys):
    rc = main(["doctor", "--channels", "fake,agent_reach"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "fake" in out
    assert "agent_reach" in out


def test_status_reports_latest_manifest(tmp_path, capsys):
    wl = _watchlist(tmp_path)
    data = tmp_path / "data"
    main(["fetch", "--watchlist", str(wl), "--data-dir", str(data), "--week", "2026-W28"])
    rc = main(["status", "--data-dir", str(data)])
    assert rc == 0
    assert "2026-W28" in capsys.readouterr().out


def test_status_without_runs(tmp_path, capsys):
    rc = main(["status", "--data-dir", str(tmp_path / "empty")])
    assert rc == 0
    assert "no fetch runs" in capsys.readouterr().out.lower()
