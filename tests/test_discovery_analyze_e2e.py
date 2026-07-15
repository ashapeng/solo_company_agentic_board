import json

from server.discovery.cli import main


WEEK = "2026-W28"


def _fetch_prepare(tmp_path):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("fake:\n  - query: pain\n    label: unit\n", encoding="utf-8")
    data = tmp_path / "data"
    assert main(["fetch", "--watchlist", str(watchlist), "--data-dir", str(data), "--week", WEEK]) == 0
    assert main(["prepare", "--data-dir", str(data), "--week", WEEK]) == 0
    bundle = json.loads((data / "prepared" / WEEK / "agent_bundle.json").read_text(encoding="utf-8"))
    return data, bundle


def _candidate(bundle):
    return {
        "schema_version": 1,
        "week": WEEK,
        "bundle_digest": bundle["records_digest"],
        "producer": {"kind": "ide_coding_agent", "name": "test-agent", "run_id": "run-1"},
        "topics": [
            {
                "id": "maker-inventory-and-pricing",
                "title": "Maker inventory and pricing",
                "summary": "Makers struggle with stock records and reliable prices.",
                "who": "Independent makers",
                "pain_class": "important",
                "signal_strength": 0.8,
                "competition_level": "moderate",
                "existing_solutions": "Generic spreadsheets and marketplace seller tools",
                "competition_rationale": "Maker audience; few specialized inventory launches in-bundle",
                "evidence": [
                    {"post_key": "fake:fake-1", "quote": "Spreadsheets keep breaking"},
                    {"post_key": "fake:fake-2", "quote": "No idea if I'm undercharging"},
                ],
            }
        ],
        "discarded_noise_notes": "",
    }


def test_fetch_prepare_import_enriches_without_model(tmp_path):
    data, bundle = _fetch_prepare(tmp_path)
    candidate = tmp_path / "candidate_topics.json"
    candidate.write_text(json.dumps(_candidate(bundle)), encoding="utf-8")
    assert main(["import-topics", str(candidate), "--data-dir", str(data), "--week", WEEK]) == 0
    report = json.loads((data / "analyzed" / WEEK / "topics.json").read_text(encoding="utf-8"))
    evidence = report["topics"][0]["evidence"][0]
    assert evidence["url"] == "https://example.com/fake-1"
    assert evidence["channel"] == "fake"
    assert "normalized_engagement" in evidence
    markdown = (data / "analyzed" / WEEK / "topics.md").read_text(encoding="utf-8")
    assert "Maker inventory and pricing" in markdown
    assert "Bundle digest" in markdown
    assert "retrieved=" in markdown


def test_dry_run_does_not_write(tmp_path, capsys):
    data, bundle = _fetch_prepare(tmp_path)
    candidate = tmp_path / "candidate_topics.json"
    candidate.write_text(json.dumps(_candidate(bundle)), encoding="utf-8")
    assert main(["import-topics", str(candidate), "--data-dir", str(data), "--week", WEEK, "--dry-run"]) == 0
    assert not (data / "analyzed" / WEEK).exists()
    assert "dry_run=true" in capsys.readouterr().out


def test_invalid_candidate_preserves_prior_report(tmp_path):
    data, bundle = _fetch_prepare(tmp_path)
    candidate = tmp_path / "candidate_topics.json"
    candidate.write_text(json.dumps(_candidate(bundle)), encoding="utf-8")
    args = ["import-topics", str(candidate), "--data-dir", str(data), "--week", WEEK]
    assert main(args) == 0
    report_path = data / "analyzed" / WEEK / "topics.json"
    before = report_path.read_bytes()
    bad = _candidate(bundle)
    bad["topics"][0]["evidence"][0]["quote"] = "hallucinated quote"
    candidate.write_text(json.dumps(bad), encoding="utf-8")
    assert main(args) != 0
    assert report_path.read_bytes() == before
