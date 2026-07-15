from __future__ import annotations

import json

from server.discovery.cli import main


WEEK = "2026-W28"


def _prepared(tmp_path):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("fake:\n  - query: pain\n    label: unit\n", encoding="utf-8")
    data = tmp_path / "discovery"
    assert main(["fetch", "--watchlist", str(watchlist), "--data-dir", str(data), "--week", WEEK]) == 0
    assert main(["prepare", "--data-dir", str(data), "--week", WEEK]) == 0
    bundle = json.loads((data / "prepared" / WEEK / "agent_bundle.json").read_text())
    return data, bundle


def _candidate(bundle):
    return {
        "schema_version": 1,
        "week": WEEK,
        "bundle_digest": bundle["records_digest"],
        "producer": {"kind": "ide_coding_agent", "name": "manual", "run_id": ""},
        "topics": [{
            "id": "maker-pain",
            "title": "Maker pain",
            "summary": "Makers have recurring operational pain.",
            "who": "Makers",
            "pain_class": "important",
            "signal_strength": 0.8,
            "competition_level": "moderate",
            "existing_solutions": "Generic spreadsheets and marketplace seller tools",
            "competition_rationale": "Maker audience; few overlapping launches in-bundle",
            "evidence": [
                {"post_key": "fake:fake-1", "quote": "Spreadsheets keep breaking"},
                {"post_key": "fake:fake-2", "quote": "No idea if I'm undercharging"},
            ],
        }],
        "discarded_noise_notes": "",
    }


def test_manual_run_resume_and_founder_review_commands(tmp_path, capsys):
    data, bundle = _prepared(tmp_path)
    assert main([
        "synthesize", "--producer", "manual", "--week", WEEK,
        "--data-dir", str(data),
    ]) == 0
    output = capsys.readouterr().out
    run_id = next(line.split()[-1] for line in output.splitlines() if line.startswith("pending producer run:"))
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(_candidate(bundle)), encoding="utf-8")

    assert main([
        "resume-run", run_id, "--candidate", str(candidate_path),
        "--data-dir", str(data),
    ]) == 0
    files = list((data / "candidates").glob("cand_*.json"))
    candidate_id = files[0].stem
    assert main(["shortlist", candidate_id, "--note", "review", "--data-dir", str(data)]) == 0
    stored = json.loads(files[0].read_text())
    assert stored["status"] == "shortlisted"
    assert stored["producer_run_id"] == run_id
    assert main(["candidates", "--status", "shortlisted", "--data-dir", str(data)]) == 0
    assert candidate_id in capsys.readouterr().out


def test_resume_rejects_completed_run(tmp_path, capsys):
    data, bundle = _prepared(tmp_path)
    main(["synthesize", "--producer", "manual", "--week", WEEK, "--data-dir", str(data)])
    output = capsys.readouterr().out
    run_id = next(line.split()[-1] for line in output.splitlines() if line.startswith("pending producer run:"))
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(json.dumps(_candidate(bundle)), encoding="utf-8")
    args = ["resume-run", run_id, "--candidate", str(candidate_path), "--data-dir", str(data)]
    assert main(args) == 0
    assert main(args) == 2
    assert "not resumable" in capsys.readouterr().out
