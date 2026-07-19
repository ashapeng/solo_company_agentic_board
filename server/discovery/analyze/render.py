from __future__ import annotations

import html
import re

from server.discovery.analyze.models import TopicReport


def _safe(value: str) -> str:
    normalized = " ".join(value.split())
    escaped = html.escape(normalized, quote=True)
    return re.sub(r"([\\`*_[\]])", r"\\\1", escaped)


def _code(value: str) -> str:
    return html.escape(" ".join(value.split()), quote=True).replace("`", "&#96;")


def _link(label: str, url: str) -> str:
    return f"[{_safe(label)}](<{html.escape(url, quote=True)}>)"


def render_markdown(report: TopicReport) -> str:
    producer_run = f" / {_code(report.producer.run_id)}" if report.producer.run_id else ""
    lines = [
        f"# Venture topics — {_safe(report.week)}",
        "",
        f"Generated/imported: `{_code(report.generated_at)}`  ",
        f"Producer: `{_code(report.producer.name)}{producer_run}` (`{report.producer.kind}`)  ",
        f"Bundle digest: `{report.bundle_digest}`  ",
        f"Raw posts: {report.post_count}; selected: {report.selected_post_count}; topics: {len(report.topics)}",
        "",
    ]
    for rank, topic in enumerate(report.topics, start=1):
        lines.extend(
            [
                f"## {rank}. {_safe(topic.title)}",
                "",
                f"**Who:** {_safe(topic.who)}  ",
                f"**Pain class:** `{topic.pain_class}`  ",
                f"**Competition:** `{topic.competition_level}`  ",
                f"**Existing solutions:** {_safe(topic.existing_solutions)}  ",
                f"**Competition rationale:** {_safe(topic.competition_rationale)}  ",
                f"**Signal:** {topic.signal_strength:.3f}; **normalized engagement:** {topic.engagement_score:.3f}",
                "",
                _safe(topic.summary),
                "",
                "### Evidence",
                "",
            ]
        )
        for item in topic.evidence:
            metadata = (
                f"channel={_safe(item.channel)}, score={item.score}, comments={item.comments}, "
                f"normalized={item.normalized_engagement:.3f}"
            )
            if item.created_at:
                metadata += f", created={_safe(item.created_at)}"
            if item.retrieved_at:
                metadata += f", retrieved={_safe(item.retrieved_at)}"
            lines.extend(
                [
                    f"- {_link(item.title or item.post_key, item.url)} — “{_safe(item.quote)}”",
                    f"  - `{_code(item.post_key)}`; {metadata}",
                ]
            )
        lines.extend(["", "### Resources", ""])
        for resource in topic.resources:
            lines.append(f"- {_link(resource.label, resource.url)} (`{resource.kind}`)")
        lines.append("")
    if report.discarded_noise_notes:
        lines.extend(
            ["## Discarded noise notes", "", _safe(report.discarded_noise_notes), ""]
        )
    return "\n".join(lines).rstrip() + "\n"
