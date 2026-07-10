import httpx

from server.discovery.channels.canadabuys import CanadaBuysChannel

CSV_BODY = (
    '"title-titre-eng","referenceNumber-numeroReference","tenderClosingDate-appelOffresDateCloture",'
    '"contractingEntityName-nomEntitContractante-eng","noticeURL-URLavis-eng","tenderDescription-descriptionAppelOffres-eng"\n'
    '"Graphic design services for public campaign","CB-100","2026-08-01",'
    '"Public Services and Procurement Canada","https://canadabuys.canada.ca/en/tender/100","Design of campaign materials"\n'
    '"Snow removal services","CB-101","2026-08-02",'
    '"PSPC","https://canadabuys.canada.ca/en/tender/101","Snow removal for federal buildings"\n'
)


def test_fetch_filters_by_keyword():
    def handler(request):
        return httpx.Response(200, text=CSV_BODY)

    ch = CanadaBuysChannel(transport=httpx.MockTransport(handler))
    posts = ch.fetch({"keywords": ["design services"], "label": "design"})
    assert len(posts) == 1
    p = posts[0]
    assert p.id == "CB-100"
    assert p.channel == "canadabuys"
    assert p.extra["deadline"] == "2026-08-01"
    assert p.extra["agency"] == "Public Services and Procurement Canada"
    assert p.url == "https://canadabuys.canada.ca/en/tender/100"


def test_health_error_on_failure():
    ch = CanadaBuysChannel(
        transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    assert ch.health().status == "error"
