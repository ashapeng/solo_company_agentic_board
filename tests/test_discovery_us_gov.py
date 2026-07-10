import httpx
import pytest

from server.discovery.channels.grants_gov import GrantsGovChannel
from server.discovery.channels.sam_gov import SamGovChannel

SAM_FIXTURE = {
    "opportunitiesData": [
        {
            "noticeId": "n-100",
            "title": "Creative Services for Public Outreach",
            "fullParentPathName": "GENERAL SERVICES ADMINISTRATION",
            "type": "Solicitation",
            "postedDate": "2026-07-01",
            "responseDeadLine": "2026-07-20",
            "uiLink": "https://sam.gov/opp/n-100/view",
            "description": "Agency seeks creative design services",
        }
    ]
}

GRANTS_FIXTURE = {
    "data": {
        "oppHits": [
            {
                "id": 358000,
                "number": "NEA-2026-01",
                "title": "Arts Small Business Support Grants",
                "agencyName": "National Endowment for the Arts",
                "openDate": "2026-06-15",
                "closeDate": "2026-08-15",
            }
        ]
    }
}


def test_sam_gov_maps_notices():
    def handler(request):
        assert "api.sam.gov" in str(request.url)
        assert "api_key=k123" in str(request.url)
        return httpx.Response(200, json=SAM_FIXTURE)

    ch = SamGovChannel(transport=httpx.MockTransport(handler), api_key="k123")
    posts = ch.fetch({"keywords": ["creative services"], "label": "creative"})
    p = posts[0]
    assert p.id == "n-100"
    assert p.channel == "sam_gov"
    assert p.extra["deadline"] == "2026-07-20"
    assert p.extra["agency"] == "GENERAL SERVICES ADMINISTRATION"
    assert p.extra["notice_type"] == "Solicitation"


def test_sam_gov_unconfigured_without_key(monkeypatch):
    monkeypatch.delenv("SAM_GOV_API_KEY", raising=False)
    ch = SamGovChannel(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    assert ch.health().status == "unconfigured"
    with pytest.raises(RuntimeError, match="SAM_GOV_API_KEY"):
        ch.fetch({"keywords": ["x"], "label": "x"})


def test_grants_gov_maps_hits():
    def handler(request):
        assert request.method == "POST"
        assert "api.grants.gov" in str(request.url)
        return httpx.Response(200, json=GRANTS_FIXTURE)

    ch = GrantsGovChannel(transport=httpx.MockTransport(handler))
    posts = ch.fetch({"keywords": ["arts small business"], "label": "arts"})
    p = posts[0]
    assert p.id == "358000"
    assert p.channel == "grants_gov"
    assert p.url == "https://www.grants.gov/search-results-detail/358000"
    assert p.extra["deadline"] == "2026-08-15"
    assert p.extra["agency"] == "National Endowment for the Arts"
