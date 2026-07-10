# Venture Topic Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn one week of discovery raw posts into a ranked venture-idea topic list with summaries, cited evidence, and resource links (JSON + Markdown), exposed via `python -m server.discovery analyze`.

**Architecture:** Keep `channels/` LLM-free. Add `server/discovery/analyze/` that loads a week’s raw posts, budgets a corpus, calls `query_llm` once for structured topics, validates citations against real post keys, and writes `data/discovery/analyzed/{week}/topics.{json,md}`. Wire a new CLI subcommand; reuse the classifier-class model by default.

**Tech Stack:** Python 3.11+, existing `server.board.llm.query_llm`, pytest, dataclasses + JSON (no new deps).

**Design spec:** `design/superpowers/specs/2026-07-10-venture-topic-summary-design.md`

---

## File map

| Path | Responsibility |
|------|----------------|
| `server/discovery/analyze/__init__.py` | Public exports |
| `server/discovery/analyze/models.py` | Dataclasses for Topic, Evidence, Resource, TopicReport |
| `server/discovery/analyze/corpus.py` | Load week posts + engagement ranking + truncation |
| `server/discovery/analyze/prompt.py` | System + user prompt builders |
| `server/discovery/analyze/validate.py` | Parse LLM JSON, repair/drop bad citations, rank |
| `server/discovery/analyze/render.py` | Markdown renderer |
| `server/discovery/analyze/synthesize.py` | Orchestrate LLM call + validate + write |
| `server/discovery/store.py` | Add `read_week_posts`, `write_analyzed`, `analyzed_exists` |
| `server/discovery/cli.py` | Add `analyze` subcommand; extend `status` |
| `server/board/config.py` | Add `get_discovery_analyze_model()` |
| `tests/test_discovery_analyze_*.py` | Unit + CLI tests with mocked LLM |

---

### Task 1: Topic report data models

**Files:**
- Create: `server/discovery/analyze/__init__.py`
- Create: `server/discovery/analyze/models.py`
- Test: `tests/test_discovery_analyze_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_models.py
from server.discovery.analyze.models import Evidence, Resource, Topic, TopicReport


def test_topic_report_roundtrip_dict():
    report = TopicReport(
        week="2026-W28",
        generated_at="2026-07-10T00:00:00+00:00",
        model="gemini/gemini-2.5-flash",
        post_count=2,
        topics=[
            Topic(
                id="yarn-inventory",
                title="Yarn inventory chaos",
                summary="Makers lose track of stock.",
                who="Etsy knitters",
                pain_class="hair_on_fire",
                signal_strength=0.9,
                engagement_score=60,
                evidence=[
                    Evidence(
                        post_key="fake:fake-1",
                        channel="fake",
                        title="I wish there was a tool for tracking yarn inventory",
                        url="https://example.com/1",
                        score=42,
                        comments=18,
                        quote="Spreadsheets keep breaking",
                    )
                ],
                resources=[
                    Resource(label="thread", url="https://example.com/1", kind="discussion")
                ],
            )
        ],
        discarded_noise_notes="",
    )
    data = report.to_dict()
    restored = TopicReport.from_dict(data)
    assert restored.week == "2026-W28"
    assert restored.topics[0].evidence[0].post_key == "fake:fake-1"
    assert restored.topics[0].resources[0].kind == "discussion"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_models.py::test_topic_report_roundtrip_dict -v`

Expected: FAIL with `ModuleNotFoundError` or import error for `server.discovery.analyze.models`

- [ ] **Step 3: Write minimal implementation**

```python
# server/discovery/analyze/__init__.py
"""LLM analysis of discovery raw posts. Channels remain LLM-free."""

from server.discovery.analyze.models import Evidence, Resource, Topic, TopicReport

__all__ = ["Evidence", "Resource", "Topic", "TopicReport"]
```

```python
# server/discovery/analyze/models.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


PAIN_CLASSES = frozenset(
    {"hair_on_fire", "important", "nice_to_solve", "opportunity"}
)


@dataclass
class Evidence:
    post_key: str
    channel: str
    title: str
    url: str
    score: int = 0
    comments: int = 0
    quote: str = ""


@dataclass
class Resource:
    label: str
    url: str
    kind: str = "discussion"  # discussion | video | issue | tender | other


@dataclass
class Topic:
    id: str
    title: str
    summary: str
    who: str
    pain_class: str
    signal_strength: float
    engagement_score: int = 0
    evidence: list[Evidence] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)


@dataclass
class TopicReport:
    week: str
    generated_at: str
    model: str
    post_count: int
    topics: list[Topic] = field(default_factory=list)
    discarded_noise_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TopicReport:
        topics = []
        for t in data.get("topics", []):
            evidence = [Evidence(**e) for e in t.get("evidence", [])]
            resources = [Resource(**r) for r in t.get("resources", [])]
            topics.append(
                Topic(
                    id=t["id"],
                    title=t["title"],
                    summary=t["summary"],
                    who=t.get("who", ""),
                    pain_class=t.get("pain_class", "important"),
                    signal_strength=float(t.get("signal_strength", 0)),
                    engagement_score=int(t.get("engagement_score", 0)),
                    evidence=evidence,
                    resources=resources,
                )
            )
        return cls(
            week=data["week"],
            generated_at=data["generated_at"],
            model=data["model"],
            post_count=int(data.get("post_count", 0)),
            topics=topics,
            discarded_noise_notes=data.get("discarded_noise_notes", ""),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_models.py::test_topic_report_roundtrip_dict -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/analyze/__init__.py server/discovery/analyze/models.py tests/test_discovery_analyze_models.py
git commit -m "feat(discovery): add topic report data models"
```

---

### Task 2: Store helpers for week load + analyzed write

**Files:**
- Modify: `server/discovery/store.py`
- Test: `tests/test_discovery_store.py` (extend) or `tests/test_discovery_analyze_store.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_store.py
import json
from dataclasses import asdict

from server.discovery.analyze.models import Topic, TopicReport
from server.discovery.channels.base import RawPost
from server.discovery.store import DiscoveryStore


def test_read_week_posts_loads_all_channel_files(tmp_path):
    store = DiscoveryStore(tmp_path)
    week = "2026-W28"
    posts = [
        RawPost(
            id="1",
            channel="fake",
            source="fake",
            title="A",
            body="b",
            url="https://example.com/a",
            score=10,
            comments=2,
        )
    ]
    store.write_raw(week, "fake", "unit", posts)
    store.write_manifest(week, {"week": week, "runs": [], "doctor": []})
    loaded = store.read_week_posts(week)
    assert len(loaded) == 1
    assert loaded[0].key() == "fake:1"


def test_write_analyzed_persists_json_and_md(tmp_path):
    store = DiscoveryStore(tmp_path)
    report = TopicReport(
        week="2026-W28",
        generated_at="2026-07-10T00:00:00+00:00",
        model="test",
        post_count=0,
        topics=[
            Topic(
                id="t1",
                title="Title",
                summary="Sum",
                who="Who",
                pain_class="important",
                signal_strength=0.5,
            )
        ],
    )
    paths = store.write_analyzed("2026-W28", report, "# Title\n")
    assert paths["json"].exists()
    assert paths["md"].exists()
    assert store.analyzed_exists("2026-W28")
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert data["topics"][0]["id"] == "t1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_store.py -v`

Expected: FAIL — `read_week_posts` / `write_analyzed` missing

- [ ] **Step 3: Write minimal implementation**

Add to `server/discovery/store.py`:

```python
def read_week_posts(self, week: str) -> list[RawPost]:
    week_dir = self.root / "raw" / week
    if not week_dir.exists():
        return []
    posts: list[RawPost] = []
    for path in sorted(week_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        for item in raw:
            posts.append(RawPost(**{k: item[k] for k in (
                "id", "channel", "source", "title", "body", "url",
                "author", "score", "comments", "created_at", "extra",
            ) if k in item}))
    return posts


def write_analyzed(self, week: str, report: "TopicReport", markdown: str) -> dict[str, Path]:
    # Import locally to avoid circular imports at module load if needed
    from server.discovery.analyze.models import TopicReport as _TR  # noqa: F401

    out = self.root / "analyzed" / week
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "topics.json"
    md_path = out / "topics.md"
    json_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    md_path.write_text(markdown, encoding="utf-8")
    return {"json": json_path, "md": md_path}


def analyzed_exists(self, week: str) -> bool:
    return (self.root / "analyzed" / week / "topics.json").exists()
```

Use a proper type hint: add `from __future__ import annotations` (already present) and quote `TopicReport` or import it at top of `store.py`:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.discovery.analyze.models import TopicReport
```

When constructing `RawPost`, supply defaults for missing optional fields:

```python
posts.append(
    RawPost(
        id=item["id"],
        channel=item["channel"],
        source=item.get("source", item["channel"]),
        title=item.get("title", ""),
        body=item.get("body", ""),
        url=item.get("url", ""),
        author=item.get("author", ""),
        score=int(item.get("score", 0) or 0),
        comments=int(item.get("comments", 0) or 0),
        created_at=item.get("created_at", ""),
        extra=item.get("extra") or {},
    )
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_store.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/store.py tests/test_discovery_analyze_store.py
git commit -m "feat(discovery): load week posts and write analyzed topics"
```

---

### Task 3: Corpus preparation

**Files:**
- Create: `server/discovery/analyze/corpus.py`
- Test: `tests/test_discovery_analyze_corpus.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_corpus.py
from server.discovery.analyze.corpus import prepare_corpus, post_engagement
from server.discovery.channels.base import RawPost


def _post(pid, score, comments, body="x" * 500):
    return RawPost(
        id=pid,
        channel="fake",
        source="fake",
        title=f"t-{pid}",
        body=body,
        url=f"https://example.com/{pid}",
        score=score,
        comments=comments,
    )


def test_prepare_corpus_ranks_and_truncates():
    posts = [_post("low", 1, 0), _post("high", 100, 50), _post("mid", 10, 5)]
    corpus = prepare_corpus(posts, max_posts=2, body_chars=20)
    assert [p["id"] for p in corpus] == ["high", "mid"]
    assert len(corpus[0]["body"]) <= 20
    assert corpus[0]["post_key"] == "fake:high"


def test_post_engagement():
    assert post_engagement(_post("a", 10, 5)) == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_corpus.py -v`

Expected: FAIL — module missing

- [ ] **Step 3: Write minimal implementation**

```python
# server/discovery/analyze/corpus.py
from __future__ import annotations

from typing import Any

from server.discovery.channels.base import RawPost


def post_engagement(post: RawPost) -> int:
    return int(post.score or 0) + int(post.comments or 0)


def prepare_corpus(
    posts: list[RawPost],
    *,
    max_posts: int = 80,
    body_chars: int = 400,
) -> list[dict[str, Any]]:
    ranked = sorted(posts, key=post_engagement, reverse=True)
    selected = ranked[: max(0, max_posts)]
    corpus: list[dict[str, Any]] = []
    for p in selected:
        body = p.body or ""
        if len(body) > body_chars:
            body = body[: body_chars].rstrip() + "…"
        corpus.append(
            {
                "post_key": p.key(),
                "id": p.id,
                "channel": p.channel,
                "title": p.title,
                "body": body,
                "url": p.url,
                "author": p.author,
                "score": int(p.score or 0),
                "comments": int(p.comments or 0),
                "created_at": p.created_at,
            }
        )
    return corpus
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_corpus.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/analyze/corpus.py tests/test_discovery_analyze_corpus.py
git commit -m "feat(discovery): prepare engagement-ranked analyze corpus"
```

---

### Task 4: Prompt builder

**Files:**
- Create: `server/discovery/analyze/prompt.py`
- Test: `tests/test_discovery_analyze_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_prompt.py
import json

from server.discovery.analyze.prompt import build_messages


def test_build_messages_includes_week_and_posts():
    corpus = [
        {
            "post_key": "fake:1",
            "channel": "fake",
            "title": "Pricing handmade goods is guesswork",
            "body": "No idea if I'm undercharging",
            "url": "https://example.com/1",
            "score": 10,
            "comments": 3,
        }
    ]
    system, messages = build_messages(week="2026-W28", corpus=corpus, max_topics=5)
    assert "venture" in system.lower() or "pain" in system.lower()
    user = messages[0]["content"]
    assert "2026-W28" in user
    assert "fake:1" in user
    assert "max_topics" in user or "5" in user
    # corpus embedded as JSON for the model
    assert "Pricing handmade" in user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_prompt.py -v`

Expected: FAIL — module missing

- [ ] **Step 3: Write minimal implementation**

```python
# server/discovery/analyze/prompt.py
from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """You are a venture discovery analyst for an early-stage product board.
Given raw social/web posts from a weekly scan, extract recurring customer pains and
venture-relevant opportunity topics.

Rules:
- Prefer problems people are actively struggling with over feature wishlists.
- Merge near-duplicate posts into one topic.
- Every topic MUST cite real post_key values from the input corpus only.
- Do not invent URLs or post keys.
- Return ONLY valid JSON matching the schema in the user message.
- pain_class must be one of: hair_on_fire, important, nice_to_solve, opportunity.
- signal_strength is your 0..1 confidence that this is a real, repeated pain worth exploring.
"""


def build_messages(
    *,
    week: str,
    corpus: list[dict[str, Any]],
    max_topics: int = 8,
) -> tuple[str, list[dict[str, str]]]:
    schema_hint = {
        "topics": [
            {
                "id": "kebab-case-id",
                "title": "short topic title",
                "summary": "2-4 sentence founder-facing summary",
                "who": "who feels this pain",
                "pain_class": "hair_on_fire",
                "signal_strength": 0.0,
                "evidence": [
                    {
                        "post_key": "channel:id",
                        "quote": "short quote from body/title",
                    }
                ],
                "resources": [
                    {"label": "short label", "url": "https://...", "kind": "discussion"}
                ],
            }
        ],
        "discarded_noise_notes": "optional",
    }
    user = (
        f"ISO week: {week}\n"
        f"max_topics: {max_topics}\n"
        "Return JSON object with keys topics, discarded_noise_notes.\n"
        f"Schema example:\n{json.dumps(schema_hint, indent=2)}\n\n"
        f"Corpus ({len(corpus)} posts):\n{json.dumps(corpus, ensure_ascii=False)}"
    )
    return SYSTEM_PROMPT, [{"role": "user", "content": user}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_prompt.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/analyze/prompt.py tests/test_discovery_analyze_prompt.py
git commit -m "feat(discovery): add venture topic synthesis prompt"
```

---

### Task 5: Validate + citation repair + ranking

**Files:**
- Create: `server/discovery/analyze/validate.py`
- Test: `tests/test_discovery_analyze_validate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_validate.py
from server.discovery.analyze.validate import parse_and_validate_topics


def test_parse_and_validate_attaches_real_evidence_and_drops_hallucinations():
    corpus_by_key = {
        "fake:1": {
            "post_key": "fake:1",
            "channel": "fake",
            "title": "Yarn inventory",
            "body": "Spreadsheets keep breaking",
            "url": "https://example.com/1",
            "score": 40,
            "comments": 10,
        },
        "fake:2": {
            "post_key": "fake:2",
            "channel": "fake",
            "title": "Pricing guesswork",
            "body": "Undercharging",
            "url": "https://example.com/2",
            "score": 20,
            "comments": 5,
        },
    }
    raw = {
        "topics": [
            {
                "id": "inventory",
                "title": "Inventory chaos",
                "summary": "Hard to track materials.",
                "who": "makers",
                "pain_class": "hair_on_fire",
                "signal_strength": 0.8,
                "evidence": [
                    {"post_key": "fake:1", "quote": "Spreadsheets keep breaking"},
                    {"post_key": "fake:999", "quote": "hallucinated"},
                    {"post_key": "fake:2", "quote": "Undercharging"},
                ],
                "resources": [
                    {"label": "bad", "url": "https://evil.example/x", "kind": "discussion"},
                    {"label": "good", "url": "https://example.com/1", "kind": "discussion"},
                ],
            }
        ],
        "discarded_noise_notes": "memes ignored",
    }
    topics, notes = parse_and_validate_topics(raw, corpus_by_key, max_topics=8, min_evidence=2)
    assert len(topics) == 1
    assert [e.post_key for e in topics[0].evidence] == ["fake:1", "fake:2"]
    assert topics[0].engagement_score == 40 + 10 + 20 + 5
    assert all(r.url.startswith("https://example.com/") for r in topics[0].resources)
    assert notes == "memes ignored"


def test_topic_with_too_few_valid_citations_is_dropped():
    corpus_by_key = {
        "fake:1": {
            "post_key": "fake:1",
            "channel": "fake",
            "title": "A",
            "body": "b",
            "url": "https://example.com/1",
            "score": 1,
            "comments": 0,
        }
    }
    raw = {
        "topics": [
            {
                "id": "x",
                "title": "X",
                "summary": "s",
                "who": "w",
                "pain_class": "important",
                "signal_strength": 0.5,
                "evidence": [{"post_key": "fake:1", "quote": "b"}],
                "resources": [],
            }
        ]
    }
    topics, _ = parse_and_validate_topics(raw, corpus_by_key, max_topics=8, min_evidence=2)
    assert topics == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_validate.py -v`

Expected: FAIL — module missing

- [ ] **Step 3: Write minimal implementation**

```python
# server/discovery/analyze/validate.py
from __future__ import annotations

import json
import re
from typing import Any

from server.discovery.analyze.models import PAIN_CLASSES, Evidence, Resource, Topic

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:64] or "topic"


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start : end + 1])
        raise


def parse_and_validate_topics(
    raw: dict[str, Any] | str,
    corpus_by_key: dict[str, dict[str, Any]],
    *,
    max_topics: int = 8,
    min_evidence: int = 2,
) -> tuple[list[Topic], str]:
    if isinstance(raw, str):
        data = _extract_json(raw)
    else:
        data = raw

    allowed_urls = {v.get("url") for v in corpus_by_key.values() if v.get("url")}
    topics: list[Topic] = []
    for item in data.get("topics") or []:
        evidence: list[Evidence] = []
        seen_keys: set[str] = set()
        for ev in item.get("evidence") or []:
            key = ev.get("post_key") or ""
            if key in seen_keys or key not in corpus_by_key:
                continue
            seen_keys.add(key)
            src = corpus_by_key[key]
            evidence.append(
                Evidence(
                    post_key=key,
                    channel=src.get("channel", ""),
                    title=src.get("title", ""),
                    url=src.get("url", ""),
                    score=int(src.get("score", 0) or 0),
                    comments=int(src.get("comments", 0) or 0),
                    quote=(ev.get("quote") or "")[:280],
                )
            )
        if len(evidence) < min_evidence:
            continue

        resources: list[Resource] = []
        for res in item.get("resources") or []:
            url = res.get("url") or ""
            if url not in allowed_urls:
                continue
            resources.append(
                Resource(
                    label=(res.get("label") or url)[:120],
                    url=url,
                    kind=(res.get("kind") or "discussion")[:32],
                )
            )
        # Always ensure each evidence URL is available as a resource
        have = {r.url for r in resources}
        for ev in evidence:
            if ev.url and ev.url not in have:
                resources.append(
                    Resource(label=ev.title[:80] or ev.post_key, url=ev.url, kind="discussion")
                )
                have.add(ev.url)

        pain = item.get("pain_class") or "important"
        if pain not in PAIN_CLASSES:
            pain = "important"
        strength = float(item.get("signal_strength") or 0)
        strength = max(0.0, min(1.0, strength))
        topic_id = _slugify(item.get("id") or item.get("title") or "topic")
        engagement = sum(e.score + e.comments for e in evidence)
        topics.append(
            Topic(
                id=topic_id,
                title=(item.get("title") or topic_id)[:160],
                summary=(item.get("summary") or "")[:2000],
                who=(item.get("who") or "")[:200],
                pain_class=pain,
                signal_strength=strength,
                engagement_score=engagement,
                evidence=evidence,
                resources=resources,
            )
        )

    topics.sort(key=lambda t: (t.signal_strength, t.engagement_score), reverse=True)
    topics = topics[: max(0, max_topics)]
    notes = str(data.get("discarded_noise_notes") or "")
    return topics, notes
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_validate.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/analyze/validate.py tests/test_discovery_analyze_validate.py
git commit -m "feat(discovery): validate topic citations against corpus"
```

---

### Task 6: Markdown renderer

**Files:**
- Create: `server/discovery/analyze/render.py`
- Test: `tests/test_discovery_analyze_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_render.py
from server.discovery.analyze.models import Evidence, Resource, Topic, TopicReport
from server.discovery.analyze.render import render_topics_markdown


def test_render_topics_markdown_includes_evidence_links():
    report = TopicReport(
        week="2026-W28",
        generated_at="2026-07-10T00:00:00+00:00",
        model="test-model",
        post_count=2,
        topics=[
            Topic(
                id="inventory",
                title="Inventory chaos",
                summary="Makers cannot track stock.",
                who="Etsy knitters",
                pain_class="hair_on_fire",
                signal_strength=0.9,
                engagement_score=50,
                evidence=[
                    Evidence(
                        post_key="fake:1",
                        channel="fake",
                        title="Yarn tool wish",
                        url="https://example.com/1",
                        score=40,
                        comments=10,
                        quote="Spreadsheets keep breaking",
                    )
                ],
                resources=[
                    Resource(label="Yarn tool wish", url="https://example.com/1", kind="discussion")
                ],
            )
        ],
    )
    md = render_topics_markdown(report)
    assert "# Venture topics — 2026-W28" in md
    assert "Inventory chaos" in md
    assert "https://example.com/1" in md
    assert "Spreadsheets keep breaking" in md
    assert "hair_on_fire" in md
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_render.py -v`

Expected: FAIL — module missing

- [ ] **Step 3: Write minimal implementation**

```python
# server/discovery/analyze/render.py
from __future__ import annotations

from server.discovery.analyze.models import TopicReport


def render_topics_markdown(report: TopicReport) -> str:
    lines: list[str] = [
        f"# Venture topics — {report.week}",
        "",
        f"_Generated {report.generated_at} · model `{report.model}` · "
        f"{report.post_count} source posts · {len(report.topics)} topics_",
        "",
    ]
    if not report.topics:
        lines.append("_No topics met the evidence threshold for this week._")
        lines.append("")
        return "\n".join(lines)

    for i, topic in enumerate(report.topics, start=1):
        lines.append(f"## {i}. {topic.title}")
        lines.append("")
        lines.append(
            f"**Who:** {topic.who} · **Pain:** `{topic.pain_class}` · "
            f"**Signal:** {topic.signal_strength:.2f} · "
            f"**Engagement:** {topic.engagement_score}"
        )
        lines.append("")
        lines.append(topic.summary)
        lines.append("")
        lines.append("### Evidence")
        for ev in topic.evidence:
            quote = f" — “{ev.quote}”" if ev.quote else ""
            lines.append(
                f"- [{ev.title}]({ev.url}) (`{ev.post_key}`, "
                f"score={ev.score}, comments={ev.comments}){quote}"
            )
        lines.append("")
        if topic.resources:
            lines.append("### Resources")
            for res in topic.resources:
                lines.append(f"- [{res.label}]({res.url}) ({res.kind})")
            lines.append("")

    if report.discarded_noise_notes:
        lines.append("## Notes")
        lines.append("")
        lines.append(report.discarded_noise_notes)
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_render.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/analyze/render.py tests/test_discovery_analyze_render.py
git commit -m "feat(discovery): render venture topics markdown brief"
```

---

### Task 7: Model config helper

**Files:**
- Modify: `server/board/config.py`
- Test: `tests/test_discovery_analyze_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_config.py
from server.board.config import get_discovery_analyze_model


def test_discovery_analyze_model_defaults_to_classifier(monkeypatch):
    monkeypatch.delenv("DISCOVERY_ANALYZE_MODEL", raising=False)
    monkeypatch.setenv("CLASSIFIER_MODEL", "gemini/gemini-2.5-flash")
    assert get_discovery_analyze_model() == "gemini/gemini-2.5-flash"


def test_discovery_analyze_model_env_override(monkeypatch):
    monkeypatch.setenv("DISCOVERY_ANALYZE_MODEL", "deepseek/deepseek-v4-pro")
    assert get_discovery_analyze_model() == "deepseek/deepseek-v4-pro"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_config.py -v`

Expected: FAIL — `get_discovery_analyze_model` missing

- [ ] **Step 3: Write minimal implementation**

In `server/board/config.py`, after `get_classifier_model`:

```python
def get_discovery_analyze_model() -> str:
    return os.getenv("DISCOVERY_ANALYZE_MODEL") or get_classifier_model()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_config.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/board/config.py tests/test_discovery_analyze_config.py
git commit -m "feat(discovery): add DISCOVERY_ANALYZE_MODEL config helper"
```

---

### Task 8: Synthesize orchestrator

**Files:**
- Create: `server/discovery/analyze/synthesize.py`
- Test: `tests/test_discovery_analyze_synthesize.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_synthesize.py
import json

import pytest

from server.discovery.analyze.synthesize import synthesize_week
from server.discovery.channels.base import RawPost
from server.discovery.store import DiscoveryStore


@pytest.mark.asyncio
async def test_synthesize_week_writes_report(tmp_path, monkeypatch):
    store = DiscoveryStore(tmp_path)
    week = "2026-W28"
    posts = [
        RawPost("1", "fake", "fake", "Yarn inventory pain", "Spreadsheets break", "https://example.com/1", score=40, comments=10),
        RawPost("2", "fake", "fake", "Still losing yarn", "Photos everywhere", "https://example.com/2", score=20, comments=5),
        RawPost("3", "fake", "fake", "Pricing guesswork", "Undercharging", "https://example.com/3", score=15, comments=4),
        RawPost("4", "fake", "fake", "Pricing is hard", "No idea on margins", "https://example.com/4", score=12, comments=3),
    ]
    store.write_raw(week, "fake", "unit", posts)
    store.write_manifest(week, {"week": week, "runs": [], "doctor": []})

    async def fake_query_llm(*, model, messages, system=None, temperature=0.2, **kwargs):
        class Resp:
            content = json.dumps(
                {
                    "topics": [
                        {
                            "id": "yarn-inventory",
                            "title": "Yarn inventory chaos",
                            "summary": "Makers cannot track materials.",
                            "who": "knitters",
                            "pain_class": "hair_on_fire",
                            "signal_strength": 0.9,
                            "evidence": [
                                {"post_key": "fake:1", "quote": "Spreadsheets break"},
                                {"post_key": "fake:2", "quote": "Photos everywhere"},
                            ],
                            "resources": [],
                        },
                        {
                            "id": "pricing",
                            "title": "Handmade pricing guesswork",
                            "summary": "Sellers undercharge.",
                            "who": "Etsy sellers",
                            "pain_class": "important",
                            "signal_strength": 0.7,
                            "evidence": [
                                {"post_key": "fake:3", "quote": "Undercharging"},
                                {"post_key": "fake:4", "quote": "No idea on margins"},
                            ],
                            "resources": [],
                        },
                    ],
                    "discarded_noise_notes": "",
                }
            )
            model = model
        return Resp()

    monkeypatch.setattr("server.discovery.analyze.synthesize.query_llm", fake_query_llm)

    report, paths = await synthesize_week(
        store,
        week=week,
        model="test-model",
        max_topics=8,
        max_posts=80,
        dry_run=False,
    )
    assert len(report.topics) == 2
    assert report.topics[0].id == "yarn-inventory"
    assert paths["json"].exists()
    assert "Yarn inventory chaos" in paths["md"].read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_synthesize.py -v`

Expected: FAIL — module missing

- [ ] **Step 3: Write minimal implementation**

```python
# server/discovery/analyze/synthesize.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.board.llm import query_llm
from server.discovery.analyze.corpus import prepare_corpus
from server.discovery.analyze.models import TopicReport
from server.discovery.analyze.prompt import build_messages
from server.discovery.analyze.render import render_topics_markdown
from server.discovery.analyze.validate import parse_and_validate_topics
from server.discovery.store import DiscoveryStore


class AnalyzeError(Exception):
    """Hard failure during topic synthesis."""


async def synthesize_week(
    store: DiscoveryStore,
    *,
    week: str,
    model: str,
    max_topics: int = 8,
    max_posts: int = 80,
    dry_run: bool = False,
) -> tuple[TopicReport, dict[str, Path] | dict[str, None]]:
    posts = store.read_week_posts(week)
    if not posts:
        raise AnalyzeError(f"no raw posts found for week {week}")

    corpus = prepare_corpus(posts, max_posts=max_posts)
    corpus_by_key = {row["post_key"]: row for row in corpus}
    min_evidence = 1 if len(corpus) < 2 else 2

    system, messages = build_messages(week=week, corpus=corpus, max_topics=max_topics)
    resp = await query_llm(
        model=model,
        messages=messages,
        system=system,
        temperature=0.2,
        max_tokens=4096,
    )
    topics, notes = parse_and_validate_topics(
        resp.content or "",
        corpus_by_key,
        max_topics=max_topics,
        min_evidence=min_evidence,
    )
    report = TopicReport(
        week=week,
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        model=getattr(resp, "model", None) or model,
        post_count=len(posts),
        topics=topics,
        discarded_noise_notes=notes,
    )
    markdown = render_topics_markdown(report)
    if dry_run:
        return report, {"json": None, "md": None, "markdown": markdown}  # type: ignore[dict-item]

    paths = store.write_analyzed(week, report, markdown)
    return report, paths
```

If the dry_run return shape is awkward for typing, prefer:

```python
@dataclass
class SynthesizeResult:
    report: TopicReport
    markdown: str
    paths: dict[str, Path] | None  # None when dry_run
```

and adjust the test accordingly. Keep the public function returning a clear structure; update the test to match the chosen API. Prefer `SynthesizeResult` for clarity:

```python
@dataclass
class SynthesizeResult:
    report: TopicReport
    markdown: str
    paths: dict[str, Path] | None


async def synthesize_week(...) -> SynthesizeResult:
    ...
    if dry_run:
        return SynthesizeResult(report=report, markdown=markdown, paths=None)
    paths = store.write_analyzed(week, report, markdown)
    return SynthesizeResult(report=report, markdown=markdown, paths=paths)
```

Update the test asserts to use `result.report`, `result.paths`, etc.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_synthesize.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/analyze/synthesize.py tests/test_discovery_analyze_synthesize.py
git commit -m "feat(discovery): synthesize weekly venture topic report"
```

---

### Task 9: CLI `analyze` + `status` hint

**Files:**
- Modify: `server/discovery/cli.py`
- Test: `tests/test_discovery_analyze_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery_analyze_cli.py
import json
from dataclasses import dataclass

from server.discovery.analyze.models import Topic, TopicReport
from server.discovery.channels.base import RawPost
from server.discovery.cli import main
from server.discovery.store import DiscoveryStore


def test_analyze_command_writes_topics(tmp_path, monkeypatch, capsys):
    data = tmp_path / "data"
    store = DiscoveryStore(data)
    week = "2026-W28"
    posts = [
        RawPost("1", "fake", "fake", "A", "body a enough", "https://example.com/1", score=10, comments=2),
        RawPost("2", "fake", "fake", "B", "body b enough", "https://example.com/2", score=8, comments=1),
    ]
    store.write_raw(week, "fake", "unit", posts)
    store.write_manifest(week, {"week": week, "runs": [], "doctor": []})

    @dataclass
    class FakeResult:
        report: TopicReport
        markdown: str
        paths: dict

    async def fake_synthesize(store, **kwargs):
        report = TopicReport(
            week=week,
            generated_at="2026-07-10T00:00:00+00:00",
            model="test",
            post_count=2,
            topics=[
                Topic(
                    id="a",
                    title="Topic A",
                    summary="Summary",
                    who="makers",
                    pain_class="important",
                    signal_strength=0.6,
                )
            ],
        )
        paths = store.write_analyzed(week, report, "# Venture topics — 2026-W28\n")
        return FakeResult(report=report, markdown="# Venture topics — 2026-W28\n", paths=paths)

    monkeypatch.setattr("server.discovery.cli.synthesize_week", fake_synthesize)

    rc = main(["analyze", "--data-dir", str(data), "--week", week, "--model", "test"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "topics.json" in out
    assert (data / "analyzed" / week / "topics.json").exists()


def test_status_mentions_analyzed(tmp_path, capsys):
    data = tmp_path / "data"
    store = DiscoveryStore(data)
    week = "2026-W28"
    store.write_manifest(week, {"week": week, "generated_at": "t", "runs": [], "doctor": []})
    report = TopicReport(
        week=week,
        generated_at="t",
        model="test",
        post_count=0,
        topics=[],
    )
    store.write_analyzed(week, report, "# empty\n")
    rc = main(["status", "--data-dir", str(data)])
    assert rc == 0
    assert "analyzed: yes" in capsys.readouterr().out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_discovery_analyze_cli.py -v`

Expected: FAIL — unknown `analyze` subcommand or missing status line

- [ ] **Step 3: Write minimal implementation**

In `server/discovery/cli.py`:

1. Import asyncio and helpers:

```python
import asyncio

from server.board.config import get_discovery_analyze_model
from server.discovery.analyze.synthesize import AnalyzeError, synthesize_week
```

2. Add `_cmd_analyze`:

```python
def _cmd_analyze(args: argparse.Namespace) -> int:
    store = DiscoveryStore(Path(args.data_dir))
    week = args.week
    if not week:
        latest = store.latest_manifest()
        if latest is None:
            print("no fetch runs recorded yet; run fetch first")
            return 1
        week = latest[0]
    model = args.model or get_discovery_analyze_model()
    try:
        result = asyncio.run(
            synthesize_week(
                store,
                week=week,
                model=model,
                max_topics=args.max_topics,
                max_posts=args.max_posts,
                dry_run=args.dry_run,
            )
        )
    except AnalyzeError as exc:
        print(f"analyze failed: {exc}")
        return 1
    print(f"week: {result.report.week}")
    print(f"topics: {len(result.report.topics)} (from {result.report.post_count} posts)")
    if args.dry_run:
        print(result.markdown)
        return 0
    assert result.paths is not None
    print(f"wrote: {result.paths['json']}")
    print(f"wrote: {result.paths['md']}")
    return 0
```

3. Extend `_cmd_status` after printing run stats:

```python
analyzed = "yes" if DiscoveryStore(Path(args.data_dir)).analyzed_exists(week) else "no"
print(f"analyzed: {analyzed}")
```

4. In `main()`, register subparser:

```python
p_analyze = sub.add_parser("analyze", help="Generate venture topic summary from raw week")
p_analyze.add_argument("--watchlist", default=None)  # unused; omit if not needed
p_analyze.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
p_analyze.add_argument("--week", default=None)
p_analyze.add_argument("--max-topics", type=int, default=8)
p_analyze.add_argument("--max-posts", type=int, default=80)
p_analyze.add_argument("--model", default=None)
p_analyze.add_argument("--dry-run", action="store_true")
p_analyze.set_defaults(func=_cmd_analyze)
```

Mirror the existing argparse style in `cli.py` exactly (read the file and extend `sub.add_parser` blocks the same way as `fetch`/`doctor`/`status`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_discovery_analyze_cli.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/discovery/cli.py tests/test_discovery_analyze_cli.py
git commit -m "feat(discovery): add analyze CLI for venture topic summaries"
```

---

### Task 10: Docs + package export polish

**Files:**
- Modify: `CLAUDE.md` (Running / Venture discovery section)
- Modify: `server/discovery/analyze/__init__.py` (export synthesize helpers if useful)
- Optional: `.env.example` — add `DISCOVERY_ANALYZE_MODEL=`

- [ ] **Step 1: Update CLAUDE.md discovery section**

Replace the venture discovery comment block with:

```bash
# Venture discovery (weekly scan → topic summary)
uv run python -m server.discovery doctor          # channel health
uv run python -m server.discovery fetch           # pull watchlist data for this week
uv run python -m server.discovery analyze         # topic list with evidence + resources
uv run python -m server.discovery status          # summarize last run (+ analyzed?)
```

Remove or rephrase the “analysis runs in Claude Code via /venture-scan” line to:

```text
# analyze synthesizes ranked venture topics (evidence-backed) from raw week JSON
```

- [ ] **Step 2: Add env example line**

In `.env.example`, near other model overrides:

```bash
# DISCOVERY_ANALYZE_MODEL=gemini/gemini-2.5-flash
```

- [ ] **Step 3: Run full discovery analyze test suite**

Run:

```bash
uv run pytest tests/test_discovery_analyze_*.py tests/test_discovery_cli.py tests/test_discovery_store.py -v
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md .env.example server/discovery/analyze/__init__.py
git commit -m "docs: document discovery analyze topic summary flow"
```

---

### Task 11: End-to-end smoke with fake channel (no live LLM)

**Files:**
- Test: `tests/test_discovery_analyze_e2e.py`

- [ ] **Step 1: Write e2e test**

```python
# tests/test_discovery_analyze_e2e.py
import json

from server.discovery.cli import main


def test_fetch_then_analyze_with_mocked_llm(tmp_path, monkeypatch, capsys):
    wl = tmp_path / "wl.yaml"
    wl.write_text("fake:\n  - query: pain\n    label: unit\n", encoding="utf-8")
    data = tmp_path / "data"

    rc = main(["fetch", "--watchlist", str(wl), "--data-dir", str(data), "--week", "2026-W28"])
    assert rc == 0

    async def fake_query_llm(*, model, messages, system=None, **kwargs):
        class Resp:
            content = json.dumps(
                {
                    "topics": [
                        {
                            "id": "yarn-inventory",
                            "title": "Yarn inventory",
                            "summary": "Tracking yarn is painful.",
                            "who": "knitters",
                            "pain_class": "hair_on_fire",
                            "signal_strength": 0.85,
                            "evidence": [
                                {"post_key": "fake:fake-1", "quote": "Spreadsheets keep breaking"},
                                {"post_key": "fake:fake-2", "quote": "undercharging"},
                            ],
                            "resources": [],
                        }
                    ],
                    "discarded_noise_notes": "",
                }
            )
            model = model
        return Resp()

    monkeypatch.setattr("server.discovery.analyze.synthesize.query_llm", fake_query_llm)
    rc = main(["analyze", "--data-dir", str(data), "--week", "2026-W28", "--model", "test"])
    assert rc == 0
    topics = json.loads((data / "analyzed" / "2026-W28" / "topics.json").read_text(encoding="utf-8"))
    assert topics["topics"][0]["evidence"][0]["url"]
    md = (data / "analyzed" / "2026-W28" / "topics.md").read_text(encoding="utf-8")
    assert "Yarn inventory" in md
```

Confirm fake channel IDs are exactly `fake-1` / `fake-2` by reading `server/discovery/channels/fake.py` before finalizing post_keys.

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/test_discovery_analyze_e2e.py -v`

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_discovery_analyze_e2e.py
git commit -m "test(discovery): e2e fetch+analyze topic summary with mocked LLM"
```

---

## Self-review checklist

| Spec requirement | Task |
|------------------|------|
| Ranked topic list from weekly search | Tasks 3, 5, 8 |
| Summary per topic | Tasks 1, 4, 5 |
| Evidence citations | Tasks 5, 6 |
| Resources / URLs | Tasks 5, 6 |
| Persist JSON + Markdown | Tasks 2, 8 |
| CLI entrypoint | Task 9 |
| Channels stay LLM-free | Architecture + Task 8 imports only in `analyze/` |
| Docs | Task 10 |

No placeholders left in task steps. Types (`TopicReport`, `SynthesizeResult`, `Evidence`, etc.) are defined before use. Prefer `SynthesizeResult` consistently in Tasks 8–9 if both are edited in the same implementation pass.

---

## Out of scope (follow-ups)

- Auto-feed top topics into `server.cli` deliberation
- Multi-week trend / topic continuity
- UI page for browsing `analyzed/`
- Scheduled Render cron for fetch+analyze
- Replacing `/venture-scan` Claude Code skill with a thin wrapper that shells to `analyze`
