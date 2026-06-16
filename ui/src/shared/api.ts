import type {
  BoardMember,
  BoardSession,
  ConsolidationResult,
  DelegatedTask,
  ExecutionAgent,
  RollbackResult,
  SessionMetrics,
  SotbEntry,
  SotbSnapshot,
  StreamEvent,
} from './types';

export const API = '';

export async function loadMembers(): Promise<BoardMember[]> {
  const response = await fetch(`${API}/members`);
  if (!response.ok) throw new Error('Failed to load members.');
  return response.json();
}

export async function loadMetricsSummary(): Promise<{ session_id?: string | null; metrics?: SessionMetrics }> {
  const response = await fetch(`${API}/metrics/summary`);
  if (!response.ok) throw new Error('Failed to load metrics.');
  return response.json();
}

export async function loadSotb(): Promise<{ content?: string; path?: string }> {
  const response = await fetch(`${API}/sotb`);
  if (!response.ok) throw new Error('Failed to load SOTB.');
  return response.json();
}

// ─── SOTB memory audit (white-box) ──────────────────────────────────────────

export async function getSotbEntries(
  ventureId = 'default',
): Promise<SotbEntry[]> {
  const response = await fetch(`${API}/sotb/entries?venture_id=${encodeURIComponent(ventureId)}`);
  if (!response.ok) throw new Error('Failed to load SOTB entries.');
  const data: { venture_id: string; entries: SotbEntry[] } = await response.json();
  return data.entries ?? [];
}

export async function getSotbSnapshots(
  ventureId = 'default',
  limit = 20,
): Promise<SotbSnapshot[]> {
  const response = await fetch(
    `${API}/sotb/snapshots?venture_id=${encodeURIComponent(ventureId)}&limit=${limit}`,
  );
  if (!response.ok) throw new Error('Failed to load SOTB snapshots.');
  const data: { venture_id: string; snapshots: SotbSnapshot[] } = await response.json();
  return data.snapshots ?? [];
}

export async function rollbackSnapshot(snapshotId: string): Promise<RollbackResult> {
  const response = await fetch(
    `${API}/sotb/snapshots/${encodeURIComponent(snapshotId)}/rollback`,
    { method: 'POST' },
  );
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to roll back snapshot.');
  }
  return data as RollbackResult;
}

export async function consolidateMemory(
  ventureId = 'default',
  verify = false,
): Promise<ConsolidationResult> {
  const response = await fetch(`${API}/sotb/consolidate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ venture_id: ventureId, verify }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to consolidate memory.');
  }
  return data as ConsolidationResult;
}

export async function loadExecutionAgents(): Promise<ExecutionAgent[]> {
  const response = await fetch(`${API}/execution-agents`);
  if (!response.ok) throw new Error('Failed to load execution agents.');
  return response.json();
}

export async function approveTask(taskId: string, approve = true): Promise<DelegatedTask> {
  const response = await fetch(`${API}/delegated-tasks/${taskId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approve }),
  });
  if (!response.ok) throw new Error('Failed to approve delegated task.');
  return response.json();
}

export async function planTask(taskId: string, managerAgentId: string): Promise<DelegatedTask> {
  const response = await fetch(`${API}/delegated-tasks/${taskId}/plan`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ manager_agent_id: managerAgentId }),
  });
  if (!response.ok) throw new Error('Failed to plan delegated task.');
  return response.json();
}

export async function submitFeedback(
  sessionId: string,
  rating: string,
  note?: string,
): Promise<{ status: string; session_id: string }> {
  const response = await fetch(`${API}/sessions/${sessionId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating, note }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || 'Failed to submit feedback.');
  }
  return data;
}

export async function streamDeliberation(
  params: {
    query: string;
    full_board: boolean;
    verify: boolean;
    member_ids?: string[];
    discussion_mode?: 'staged' | 'live';
    initiative_id?: string | null;
    initiative_mode?: 'ad_hoc' | 'attach' | 'create_draft';
  },
  { onEvent }: { onEvent: (event: StreamEvent) => void },
) {
  const response = await fetch(`${API}/deliberate/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Server error: ${response.status} - ${err}`);
  }
  if (!response.body) {
    throw new Error('Server did not return a stream.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data: ')) continue;
      try {
        onEvent(JSON.parse(trimmed.slice(6)) as BoardSession & StreamEvent);
      } catch {
        // Ignore malformed partials and keepalives.
      }
    }
  }
}

export async function streamContinuation(
  sessionId: string,
  userInput: string,
  { onEvent }: { onEvent: (event: StreamEvent) => void },
) {
  const response = await fetch(`${API}/sessions/${encodeURIComponent(sessionId)}/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_input: userInput }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Server error: ${response.status} - ${err}`);
  }
  if (!response.body) {
    throw new Error('Server did not return a stream.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data: ')) continue;
      try {
        onEvent(JSON.parse(trimmed.slice(6)) as BoardSession & StreamEvent);
      } catch {
        // Ignore malformed partials and keepalives.
      }
    }
  }
}

// ─── Routing signal (Phase A-lite) ─────────────────────────────────────────

export type RoutingSignalSource = "manual_add" | "missing_voice_flag";

export async function recordRoutingSignal(
  sessionId: string,
  memberId: string,
  source: RoutingSignalSource,
): Promise<void> {
  const res = await fetch(`${API}/sessions/${sessionId}/routing-signal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_id: memberId, source }),
  });
  if (!res.ok) {
    // Best-effort — do not throw; caller continues UI state transitions.
    // eslint-disable-next-line no-console
    console.warn(`routing-signal failed: ${res.status}`);
  }
}

/**
 * Buffer for routing signals that occur before the session is ledger-persisted.
 * Flush via flushRoutingSignalBuffer() when the session reaches T6 completion.
 */
type BufferedSignal = { memberId: string; source: RoutingSignalSource; ts: string };
const routingSignalBuffer: Map<string, BufferedSignal[]> = new Map();

export function bufferRoutingSignal(
  sessionId: string,
  memberId: string,
  source: RoutingSignalSource,
): void {
  const list = routingSignalBuffer.get(sessionId) ?? [];
  list.push({ memberId, source, ts: new Date().toISOString() });
  routingSignalBuffer.set(sessionId, list);
}

export async function flushRoutingSignalBuffer(sessionId: string): Promise<void> {
  const list = routingSignalBuffer.get(sessionId);
  if (!list || list.length === 0) return;
  await Promise.all(
    list.map((sig) => recordRoutingSignal(sessionId, sig.memberId, sig.source)),
  );
  routingSignalBuffer.delete(sessionId);
}

export function dropRoutingSignalBuffer(sessionId: string): void {
  routingSignalBuffer.delete(sessionId);
}
