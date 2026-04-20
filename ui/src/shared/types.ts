export type Tab = 'governance' | 'portfolio' | 'performance';

export type BoardMember = {
  id: string;
  title: string;
  role: string;
  expertise: string[];
  tags: string[];
  governance_seat?: string | null;
  capabilities?: string[];
  activation?: Record<string, unknown>;
};

export type SeatStatus = 'idle' | 'selected' | 'active' | 'done' | 'failed';

export type SeatState = {
  status?: SeatStatus;
  label?: string;
  model?: string;
  selected?: boolean;
};

export type StageMember = {
  id?: string;
  title?: string;
  model?: string;
  elapsed?: number;
  failed?: boolean;
  error?: string;
};

export type StageEvent = {
  stage: number;
  active?: boolean;
  done?: boolean;
  count?: number;
  members: StageMember[];
};

export type Classification = {
  query_type?: string;
  complexity?: string;
  relevant_member_ids?: string[];
  required_capabilities?: string[];
  role_gap_memo?: string | null;
  reasoning?: string;
};

export type Decision = {
  prepared_by?: string;
  decision_authority?: string;
  participants?: string[];
  decision_date?: string;
  session_id?: string;
  status?: string;
  assumptions?: string[];
  accountable_owners?: string[];
  executive_summary?: string;
  critical_findings?: string[];
  strategic_direction?: string;
  architecture_design?: string;
  security_posture?: string;
  implementation_plan?: string[];
  risk_register?: string[];
  dissenting_views?: string[];
  next_steps?: string[];
  raw_sections?: Record<string, string>;
};

export type SubAgentTemplate = {
  id: string;
  title: string;
  purpose: string;
  allowed_tools: string[];
  output_contract: string;
};

export type ExecutionAgent = {
  id: string;
  title: string;
  execution_unit_id: string;
  role: string;
  capabilities: string[];
  allowed_tools: string[];
  default_approval_required: boolean;
  max_parallel_subagents: number;
  subagent_templates: SubAgentTemplate[];
  active: boolean;
};

export type Subtask = {
  id: string;
  title: string;
  objective: string;
  assigned_subagent_template_id: string;
  required_inputs: string[];
  output_contract: string;
  status: 'planned' | 'running' | 'completed' | 'blocked' | 'failed';
};

export type SubtaskPlan = {
  manager_agent_id: string;
  subtasks: Subtask[];
  coordination_notes: string;
};

export type DelegatedTask = {
  id: string;
  session_id: string;
  title: string;
  objective: string;
  execution_unit_id: string;
  manager_agent_id: string;
  accountable_board_member_id: string;
  priority: 'p0' | 'p1' | 'p2';
  status: 'proposed' | 'approved' | 'running' | 'completed' | 'blocked' | 'rejected';
  acceptance_criteria: string[];
  dependencies: string[];
  approval_required: boolean;
  subtask_plan?: SubtaskPlan | null;
  artifacts: string[];
  source: 'board_synthesis';
  result_summary?: string;
  status_detail?: string;
};

export type DelegationPlan = {
  session_id: string;
  tasks: DelegatedTask[];
  warnings: string[];
  requires_approval: boolean;
};

export type ParticipationDecision = {
  member_id: string;
  mode: 'participate' | 'observe' | 'abstain';
  reason: string;
  confidence: 'high' | 'medium' | 'low';
  triggered_capabilities: string[];
};

export type Verification = {
  score?: number;
  passed?: boolean;
  deficiencies?: string[];
  notes?: string[];
};

export type SessionMetrics = {
  total_calls?: number;
  total_tokens?: number;
  total_cost_estimate_usd?: number;
  by_stage?: Record<string, { calls?: number; tokens?: number }>;
};

export type BoardSession = {
  session_id?: string;
  user_query?: string;
  classification?: Classification;
  decision?: Decision | null;
  delegation_plan?: DelegationPlan | null;
  verification?: Verification | null;
  memory?: {
    proposed_sotb_update?: string | null;
    requires_approval?: boolean;
    source?: string;
    warnings?: string[];
  };
  status?: string;
  intake_cards?: Array<Record<string, unknown>>;
  clarification?: {
    status?: string;
    questions?: Array<Record<string, unknown>>;
    answers?: Record<string, unknown>;
  };
  structured_output_warnings?: string[];
  metrics?: SessionMetrics;
  stage3?: { content?: string };
  stage3_synthesis?: { content?: string };
  participation?: ParticipationDecision[];
};

export type StreamEvent = {
  event: string;
  stage?: number;
  name?: string;
  member_id?: string;
  member_title?: string;
  model?: string;
  elapsed?: number;
  count?: number;
  session?: BoardSession;
  error?: string;
  message?: string;
};

export type TableStatus = {
  label: string;
  title: string;
  detail: string;
};
