import { API } from '../../shared/api';
import type { BoardSession, DelegatedTask } from '../../shared/types';

export type InitiativeStatus = 'draft' | 'active' | 'closed';
export type FounderOutcome = 'success' | 'failure' | 'mixed';
export type InitiativeLinkTargetType =
  | 'sotb_entry'
  | 'initiative'
  | 'board_session'
  | 'delegated_task'
  | 'artifact';
export type InitiativeLinkRelationship =
  | 'context'
  | 'output'
  | 'carryover'
  | 'evidence'
  | 'artifact';

export type InitiativeLink = {
  id: string;
  initiative_id: string;
  target_type: InitiativeLinkTargetType;
  target_id: string;
  relationship: InitiativeLinkRelationship;
  created_at: string;
  metadata?: Record<string, unknown>;
};

export type CarryoverDecision = {
  task_id: string;
  decision: 'carry_over' | 'abandon' | 'backlog';
  target_initiative_id?: string | null;
};

export type InitiativeCloseout = {
  initiative_id: string;
  founder_outcome: FounderOutcome;
  founder_notes: string;
  retrospective_session_id?: string | null;
  memory_proposals: string[];
  carryover_decisions: CarryoverDecision[];
  created_at: string;
};

export type Initiative = {
  id: string;
  title: string;
  objective: string;
  status: InitiativeStatus;
  timebox_start: string;
  timebox_end: string;
  success_criteria: string[];
  departments: string[];
  approval_state: 'draft' | 'approved';
  created_from: 'manual' | 'founder_command' | 'board_suggestion';
  source_session_id?: string | null;
  created_at: string;
  updated_at: string;
  links?: InitiativeLink[];
  closeout?: InitiativeCloseout;
};

export type CreateInitiativeParams = {
  title: string;
  objective: string;
  success_criteria?: string[];
  departments?: string[];
  created_from?: 'manual' | 'founder_command' | 'board_suggestion';
  source_session_id?: string | null;
  timebox_start?: string | null;
  timebox_end?: string | null;
};

export type CloseInitiativeParams = {
  founder_outcome: FounderOutcome;
  founder_notes?: string;
  retrospective_session_id?: string | null;
  memory_proposals?: string[];
  carryover_decisions?: CarryoverDecision[];
};

export async function loadInitiatives(status?: InitiativeStatus): Promise<Initiative[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  const response = await fetch(`${API}/initiatives${query}`);
  if (!response.ok) throw new Error('Failed to load initiatives.');
  return response.json();
}

export async function createInitiative(params: CreateInitiativeParams): Promise<Initiative> {
  const response = await fetch(`${API}/initiatives`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!response.ok) throw new Error('Failed to create initiative.');
  return response.json();
}

export async function activateInitiative(initiativeId: string): Promise<Initiative> {
  const response = await fetch(`${API}/initiatives/${encodeURIComponent(initiativeId)}/activate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approve: true }),
  });
  if (!response.ok) throw new Error('Failed to activate initiative.');
  return response.json();
}

export async function closeInitiative(
  initiativeId: string,
  params: CloseInitiativeParams,
): Promise<Initiative> {
  const response = await fetch(`${API}/initiatives/${encodeURIComponent(initiativeId)}/closeout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      founder_outcome: params.founder_outcome,
      founder_notes: params.founder_notes ?? '',
      retrospective_session_id: params.retrospective_session_id,
      memory_proposals: params.memory_proposals ?? [],
      carryover_decisions: params.carryover_decisions ?? [],
    }),
  });
  if (!response.ok) throw new Error('Failed to close initiative.');
  return response.json();
}

export async function loadInitiativeSessions(
  initiativeId: string,
): Promise<{ initiative_id: string; session_ids: string[]; sessions?: BoardSession[] }> {
  const response = await fetch(`${API}/initiatives/${encodeURIComponent(initiativeId)}/sessions`);
  if (!response.ok) throw new Error('Failed to load initiative sessions.');
  return response.json();
}

export async function loadInitiativeTasks(
  initiativeId: string,
): Promise<{ initiative_id: string; tasks: DelegatedTask[] }> {
  const response = await fetch(`${API}/initiatives/${encodeURIComponent(initiativeId)}/tasks`);
  if (!response.ok) throw new Error('Failed to load initiative tasks.');
  return response.json();
}
