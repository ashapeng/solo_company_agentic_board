"""Persistent manager agents and sub-agent templates for execution units."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubAgentTemplate:
    id: str
    title: str
    purpose: str
    allowed_tools: list[str]
    output_contract: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExecutionAgent:
    id: str
    title: str
    execution_unit_id: str
    role: str
    capabilities: list[str]
    system_prompt: str
    allowed_tools: list[str]
    default_approval_required: bool
    max_parallel_subagents: int
    subagent_templates: list[SubAgentTemplate]
    active: bool = True
    memory_scope: str = "task"
    benchmark_queries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _templates(*items: tuple[str, str, str, list[str], str]) -> list[SubAgentTemplate]:
    return [
        SubAgentTemplate(
            id=item[0],
            title=item[1],
            purpose=item[2],
            allowed_tools=item[3],
            output_contract=item[4],
        )
        for item in items
    ]


EXECUTION_AGENTS = [
    ExecutionAgent(
        id="strategy_lead",
        title="Strategy Lead Agent",
        execution_unit_id="strategy",
        role="Owns market positioning, GTM, and competitive strategy execution.",
        capabilities=["market_strategy", "competitive_analysis", "go_to_market"],
        system_prompt="You turn board strategy decisions into focused market and GTM work.",
        allowed_tools=["files", "web_search"],
        default_approval_required=True,
        max_parallel_subagents=2,
        subagent_templates=_templates(
            ("market_mapper", "Market Mapper Agent", "Map market segments and competitors.", ["web_search"], "Cited market map with risks."),
            ("positioning_agent", "Positioning Agent", "Draft positioning and GTM options.", ["files"], "Positioning brief with tradeoffs."),
        ),
        benchmark_queries=["Should we enter a new segment with this wedge?"],
    ),
    ExecutionAgent(
        id="product_lead",
        title="Product Lead Agent",
        execution_unit_id="product",
        role="Owns MVP scope, roadmap slices, value proposition, and PMF tests.",
        capabilities=["product_strategy", "mvp_scope", "product_market_fit"],
        system_prompt="You convert board product decisions into crisp product execution plans.",
        allowed_tools=["files"],
        default_approval_required=True,
        max_parallel_subagents=2,
        subagent_templates=_templates(
            ("scope_planner", "Scope Planner Agent", "Decompose MVP scope and sequencing.", ["files"], "MVP scope with acceptance criteria."),
            ("experiment_designer", "Experiment Designer Agent", "Design PMF and validation experiments.", ["files"], "Experiment plan and success metrics."),
        ),
        benchmark_queries=["What is the smallest testable product slice?"],
    ),
    ExecutionAgent(
        id="research_lead",
        title="Research Lead Agent",
        execution_unit_id="research",
        role="Owns customer, market, and evidence-packet research.",
        capabilities=["customer_research", "interviews", "evidence_packets"],
        system_prompt="You gather evidence and customer truth before execution or board decisions.",
        allowed_tools=["files", "web_search"],
        default_approval_required=True,
        max_parallel_subagents=2,
        subagent_templates=_templates(
            ("web_research_agent", "Web Research Agent", "Collect current sources and claims.", ["web_search"], "Evidence packet with citations."),
            ("customer_interview_planner", "Customer Interview Planner", "Design interview plan and questions.", ["files"], "Interview plan with recruiting criteria."),
        ),
        benchmark_queries=["What evidence would change this decision?"],
    ),
    ExecutionAgent(
        id="technical_lead",
        title="Technical Lead Agent",
        execution_unit_id="engineering",
        role="Owns architecture, implementation planning, and verification coordination.",
        capabilities=["technical_feasibility", "architecture", "implementation_planning"],
        system_prompt="You manage technical execution while preserving testability and scope control.",
        allowed_tools=["files", "terminal"],
        default_approval_required=True,
        max_parallel_subagents=3,
        subagent_templates=_templates(
            ("codebase_explorer", "Codebase Explorer Agent", "Inspect code and identify affected areas.", ["files"], "Code map and change risks."),
            ("implementation_agent", "Implementation Agent", "Implement scoped code changes.", ["files", "terminal"], "Patch summary and changed files."),
            ("verification_agent", "Verification Agent", "Run tests and verify behavior.", ["terminal"], "Verification report with commands."),
        ),
        benchmark_queries=["Can this be built safely in the current architecture?"],
    ),
    ExecutionAgent(
        id="security_lead",
        title="Security Lead Agent",
        execution_unit_id="security",
        role="Owns threat modeling, privacy, compliance, and attack-surface review.",
        capabilities=["threat_modeling", "data_privacy", "compliance"],
        system_prompt="You turn security board decisions into concrete mitigations and checks.",
        allowed_tools=["files"],
        default_approval_required=True,
        max_parallel_subagents=2,
        subagent_templates=_templates(
            ("threat_modeler", "Threat Modeler Agent", "Identify abuse paths and mitigations.", ["files"], "Threat model with mitigations."),
            ("privacy_reviewer", "Privacy Reviewer Agent", "Review data flows and privacy risks.", ["files"], "Privacy review and required controls."),
        ),
        benchmark_queries=["What must be true before exposing this surface?"],
    ),
    ExecutionAgent(
        id="operations_lead",
        title="Operations Lead Agent",
        execution_unit_id="operations",
        role="Owns release readiness, monitoring, runbooks, and incident posture.",
        capabilities=["operations", "release_readiness", "monitoring"],
        system_prompt="You convert board operations decisions into repeatable runbooks.",
        allowed_tools=["files", "terminal"],
        default_approval_required=True,
        max_parallel_subagents=2,
        subagent_templates=_templates(
            ("release_planner", "Release Planner Agent", "Plan release and rollback steps.", ["files"], "Release checklist and rollback plan."),
            ("monitoring_agent", "Monitoring Agent", "Define metrics, alerts, and dashboards.", ["files"], "Monitoring plan and alert thresholds."),
        ),
        benchmark_queries=["What has to exist before this can run safely?"],
    ),
    ExecutionAgent(
        id="marketing_lead",
        title="Marketing Lead Agent",
        execution_unit_id="marketing",
        role="Owns campaign planning, outreach drafts, distribution experiments, and result analysis.",
        capabilities=[
            "campaign_planning",
            "outreach_drafts",
            "content_planning",
            "distribution_experiments",
            "marketing_analytics",
        ],
        system_prompt="You convert strategy decisions into approval-gated marketing execution work.",
        allowed_tools=["files", "web_search"],
        default_approval_required=True,
        max_parallel_subagents=2,
        subagent_templates=_templates(
            ("campaign_planner", "Campaign Planner Agent", "Plan campaign steps and assets.", ["files"], "Campaign plan with channels, assets, and approval gates."),
            ("distribution_analyst", "Distribution Analyst Agent", "Analyze channels and experiment results.", ["web_search", "files"], "Distribution analysis with next experiment recommendation."),
        ),
        benchmark_queries=["What is the smallest marketing experiment that can produce signal?"],
    ),
    ExecutionAgent(
        id="finance_lead",
        title="Finance Lead Agent",
        execution_unit_id="finance",
        role="Reserved for pricing, runway, margin, and fundraising execution.",
        capabilities=["financial_analysis", "pricing", "runway"],
        system_prompt="Reserved until a durable finance capability is approved.",
        allowed_tools=["files"],
        default_approval_required=True,
        max_parallel_subagents=1,
        subagent_templates=[],
        active=False,
    ),
    ExecutionAgent(
        id="legal_lead",
        title="Legal Lead Agent",
        execution_unit_id="legal",
        role="Reserved for contracts, IP, liability, and regulated-data execution.",
        capabilities=["legal_review", "contracts", "ip"],
        system_prompt="Reserved until a durable legal capability is approved.",
        allowed_tools=["files"],
        default_approval_required=True,
        max_parallel_subagents=1,
        subagent_templates=[],
        active=False,
    ),
]

AGENTS_BY_ID = {agent.id: agent for agent in EXECUTION_AGENTS}
AGENTS_BY_UNIT = {agent.execution_unit_id: agent for agent in EXECUTION_AGENTS}


def list_execution_agents(*, active_only: bool = True) -> list[dict[str, Any]]:
    agents = EXECUTION_AGENTS
    if active_only:
        agents = [agent for agent in agents if agent.active]
    return [agent.to_dict() for agent in agents]


def get_execution_agent(agent_id: str) -> dict[str, Any] | None:
    agent = AGENTS_BY_ID.get(agent_id)
    return agent.to_dict() if agent else None
