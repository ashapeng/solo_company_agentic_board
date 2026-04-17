import type { BoardMember, BoardSession, DelegatedTask, ExecutionAgent, SessionMetrics, StreamEvent } from './types';

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
  params: { query: string; full_board: boolean; verify: boolean; member_ids?: string[] },
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
