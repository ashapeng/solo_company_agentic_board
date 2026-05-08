"""Chair intake tests."""
from __future__ import annotations

from server.board.deliberation import intake


def test_routing_decision_dataclass_shape():
    rd = intake.RoutingDecision(
        interpreted_query="Q",
        decision_type="strategic", complexity="medium", importance="notable",
        rationale="why",
        members=[intake.MemberAssignment(
            member_id="strategist", mode="standard",
            focus="market", priority=90,
        )],
        script="live_research",
        deep_research_dossier=False,
    )
    assert rd.script == "live_research"
    assert rd.members[0].member_id == "strategist"


def test_default_routing_returns_valid_decision():
    rd = intake.DEFAULT_ROUTING(query="anything")
    assert rd.script == "live_research"
    assert rd.members
    assert all(m.mode in ("fast", "standard", "deep") for m in rd.members)


def test_parse_routing_decision_json_valid():
    raw = """
    {
      "interpreted_query": "Should we enter the X market?",
      "decision_type": "strategic",
      "complexity": "high",
      "importance": "critical",
      "rationale": "Market entry decision needs deep evidence.",
      "members": [
        {"member_id": "strategist", "mode": "deep", "focus": "TAM/SAM", "priority": 90},
        {"member_id": "researcher", "mode": "deep", "focus": "personas", "priority": 80}
      ],
      "script": "live_research",
      "deep_research_dossier": false
    }
    """
    rd = intake.parse_routing_decision(raw)
    assert rd.decision_type == "strategic"
    assert len(rd.members) == 2
    assert rd.members[0].mode == "deep"


def test_parse_routing_decision_malformed_returns_none():
    assert intake.parse_routing_decision("{not json") is None
    assert intake.parse_routing_decision("") is None
    assert intake.parse_routing_decision('{"missing": "fields"}') is None
