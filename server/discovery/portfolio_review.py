"""Application service for an all-candidate, atomic board portfolio review."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.board.portfolio import (
    PortfolioContractError, PortfolioReviewInput, PortfolioReviewResult,
    candidate_to_input, parse_portfolio_result, render_portfolio_prompt,
)
from server.board.deliberation.structured import _iter_json_blocks
from server.discovery.lifecycle import BoardLabel, CandidateStore, DiscoveryStatus, ValidationState
from server.discovery.store import DiscoveryStore
from server.experiments.store import ExperimentStore


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PortfolioReviewService:
    def __init__(self, *, candidate_store: CandidateStore, experiment_store: ExperimentStore,
                 orchestrator: Any, review_directory: Path | None = None):
        self.candidate_store = candidate_store
        self.experiment_store = experiment_store
        self.orchestrator = orchestrator
        self.review_directory = Path(review_directory or candidate_store.root / "portfolio-reviews")

    async def review(self, *, week: str, default_select: int = 3, maximum_active: int = 5,
                     verify: bool = False, config_version: str = "1") -> PortfolioReviewResult:
        eligible = [item for item in self.candidate_store.list(
            discovery_status=DiscoveryStatus.READY_FOR_BOARD, week=week
        ) if item.founder_disposition.value != "disposed" and item.evidence]
        if not eligible:
            completed = self._completed_for_week(week)
            if completed is not None:
                request = PortfolioReviewInput.model_validate(completed["request"])
                return PortfolioReviewResult.model_validate(completed["result"]).validate_against(request)
        if not 5 <= len(eligible) <= 10:
            raise ValueError(f"portfolio review requires 5-10 eligible candidates; found {len(eligible)}")
        digest = hashlib.sha256((week + "\0" + "\0".join(sorted(c.id for c in eligible))).encode()).hexdigest()[:24]
        review_id = f"review_{digest}"
        existing = self._load(review_id)
        if existing and existing.get("status") == "completed":
            request = self._request(review_id, week, eligible, default_select, maximum_active, config_version)
            return PortfolioReviewResult.model_validate(existing["result"]).validate_against(request)
        request = self._request(review_id, week, eligible, default_select, maximum_active, config_version)
        errors: list[str] = []
        raw: Any = None
        session_id = ""
        for attempt in range(2):
            try:
                raw, session_id = await self._invoke(request, verify=verify,
                                                     repair_error=errors[-1] if errors else None)
                if isinstance(raw, PortfolioReviewResult):
                    result = raw.validate_against(request)
                else:
                    if isinstance(raw, dict) and "board_session_id" not in raw:
                        raw = {**raw, "review_id": review_id, "board_session_id": session_id}
                    result = parse_portfolio_result(raw, request)
                self._apply_atomically(result)
                self._write(review_id, {
                    "schema_version": 1, "status": "completed", "review_id": review_id,
                    "created_at": utc_now(), "input_candidate_ids": [c.id for c in eligible],
                    "report_digests": sorted({c.report_digest for c in eligible}),
                    "evidence_packet_ids": sorted({(c.promotion or {}).get("evidence_packet_id") for c in eligible if (c.promotion or {}).get("evidence_packet_id")}),
                    "selected_count": sum(d.selected_for_validation for d in result.decisions),
                    "config_version": config_version, "request": request.model_dump(mode="json"),
                    "result": result.model_dump(mode="json"), "attempt_errors": errors,
                })
                return result
            except PortfolioContractError as exc:
                errors.append(str(exc))
        self._write(review_id, {
            "schema_version": 1, "status": "failed", "review_id": review_id,
            "created_at": utc_now(), "input_candidate_ids": [c.id for c in eligible],
            "request": request.model_dump(mode="json"), "attempt_errors": errors,
        })
        raise PortfolioContractError(errors[-1])

    def _request(self, review_id: str, week: str, candidates: list[Any], default_select: int,
                 maximum_active: int, config_version: str) -> PortfolioReviewInput:
        return PortfolioReviewInput(
            review_id=review_id, week=week, candidates=[candidate_to_input(c) for c in candidates],
            default_select=default_select, max_select=maximum_active,
            available_capacity=self.experiment_store.available_capacity(maximum_active),
            config_version=config_version,
        )

    async def _invoke(self, request: PortfolioReviewInput, *, verify: bool,
                      repair_error: str | None) -> tuple[Any, str]:
        if hasattr(self.orchestrator, "review_portfolio"):
            value = self.orchestrator.review_portfolio(request, repair_error=repair_error, verify=verify)
            value = await value if inspect.isawaitable(value) else value
            session_id = getattr(value, "board_session_id", "") or (value.get("board_session_id", "") if isinstance(value, dict) else "")
            return value, session_id or f"board_{request.review_id}"
        prompt = render_portfolio_prompt(request)
        if repair_error:
            prompt += f"\n\nYour previous structured result was invalid: {repair_error}. Return corrected JSON only."
        session = await self.orchestrator.deliberate(prompt, verify=verify)
        content = session.stage3_synthesis.content if session.stage3_synthesis else ""
        blocks = list(_iter_json_blocks(content))
        if blocks:
            value = json.loads(blocks[-1])
            if isinstance(value, dict):
                value.setdefault("review_id", request.review_id)
                value.setdefault("board_session_id", session.session_id)
                return value, session.session_id
        return content, session.session_id

    def _apply_atomically(self, result: PortfolioReviewResult) -> None:
        # Validate all current states and build replacements before any write.
        originals = {d.candidate_id: self.candidate_store.get(d.candidate_id) for d in result.decisions}
        if any(c.discovery_status is not DiscoveryStatus.READY_FOR_BOARD for c in originals.values()):
            raise PortfolioContractError("candidate state changed before portfolio decisions could be applied")
        written: list[str] = []
        try:
            for decision in result.decisions:
                self.candidate_store.update(
                    decision.candidate_id, actor="board", reason="portfolio review decision",
                    related_session_id=result.board_session_id,
                    discovery_status=DiscoveryStatus.REVIEWED, board_label=BoardLabel(decision.label),
                    board_rank=decision.rank, board_rationale=decision.rationale,
                    validation_state=ValidationState.QUEUED if decision.selected_for_validation else ValidationState.NOT_SELECTED,
                )
                written.append(decision.candidate_id)
        except BaseException:
            for candidate_id in written:
                self.candidate_store.save(originals[candidate_id], rebuild=False)
            self.candidate_store.rebuild_index()
            raise

    def _path(self, review_id: str) -> Path:
        return self.review_directory / f"{review_id}.json"

    def _load(self, review_id: str) -> dict[str, Any] | None:
        path = self._path(review_id)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _write(self, review_id: str, value: dict[str, Any]) -> None:
        DiscoveryStore._atomic_write(self._path(review_id), json.dumps(value, indent=2, ensure_ascii=False) + "\n")

    def _completed_for_week(self, week: str) -> dict[str, Any] | None:
        if not self.review_directory.exists():
            return None
        matches = []
        for path in sorted(self.review_directory.glob("review_*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("status") == "completed" and value.get("request", {}).get("week") == week:
                matches.append(value)
        return matches[-1] if matches else None
