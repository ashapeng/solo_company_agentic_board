import type { FormEvent } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ChevronLeft, Landmark, LogIn, Settings, ShieldCheck, Users } from 'lucide-react';
import {
  GovernancePage,
  PortfolioPage,
  loadMembers,
  streamDeliberation,
  streamContinuation,
  type BoardMember,
  type BoardSession,
  type Classification,
  type ConversationMessage,
  type LiveFeedItem,
  type SeatState,
  type StageEvent,
  type StreamEvent,
  type TableStatus,
  type Tab,
} from './domains/board';
import {
  approveTask,
  loadExecutionAgents,
  planTask,
  type DelegatedTask,
  type ExecutionAgent,
} from './domains/execution';
import { PerformancePage, loadMetricsSummary, type SessionMetrics } from './domains/harness';
import { loadSotb } from './domains/memory';
import { recordRoutingSignal } from './shared/api';
import {
  STAGE_NAMES,
  addStageMember,
  humanize,
  initialSeatStates,
  orderMembers,
  resetSeatStates,
  stageShortLabel,
  statusForStageStart,
  upsertStage,
} from './shared/presentation';

type NavItem = { id: Tab; label: string; icon: typeof Users };

const NAV_ITEMS: NavItem[] = [
  { id: 'portfolio', label: 'Portfolio', icon: Users },
  { id: 'governance', label: 'Governance', icon: Landmark },
  { id: 'performance', label: 'Compliance', icon: ShieldCheck },
];

function upsertConversationMessage(
  messages: ConversationMessage[],
  patch: ConversationMessage,
): ConversationMessage[] {
  const index = messages.findIndex((message) => message.id === patch.id);
  if (index === -1) return [...messages, patch];
  return messages.map((message, currentIndex) => (
    currentIndex === index ? { ...message, ...patch } : message
  ));
}

const maxContinuations = Number(import.meta.env.VITE_MAX_CONTINUATIONS ?? 2);

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('governance');
  const [members, setMembers] = useState<BoardMember[]>([]);
  const [executionAgents, setExecutionAgents] = useState<ExecutionAgent[]>([]);
  const [manualMemberIds, setManualMemberIds] = useState<string[]>(['chairperson']);
  const [query, setQuery] = useState('');
  const [fullBoard, setFullBoard] = useState(false);
  const [verify, setVerify] = useState(false);
  const [running, setRunning] = useState(false);
  const [session, setSession] = useState<BoardSession | null>(null);
  const [stageEvents, setStageEvents] = useState<StageEvent[]>([]);
  const [seatStates, setSeatStates] = useState<Record<string, SeatState>>({});
  const [liveFeed, setLiveFeed] = useState<LiveFeedItem[]>([]);
  const [conversationMessages, setConversationMessages] = useState<ConversationMessage[]>([]);
  const [activeStreamMessageId, setActiveStreamMessageId] = useState<string | null>(null);
  const [activePhase, setActivePhase] = useState<string | null>(null);
  const liveFeedCounter = useRef(0);
  const pendingManualAdds = useRef<string[]>([]);
  const [tableStatus, setTableStatus] = useState<TableStatus>({
    label: 'Ready',
    title: 'Waiting for a CEO decision',
    detail: 'Adaptive routing will choose the smallest useful council.',
  });
  const [sessionLabel, setSessionLabel] = useState('No active session');
  const [error, setError] = useState('');
  const [metricsSummary, setMetricsSummary] = useState<{ session_id?: string | null; metrics?: SessionMetrics }>({});
  const [sotb, setSotb] = useState<{ content?: string; path?: string }>({});
  const resultRef = useRef<HTMLDivElement | null>(null);

  const [railExpanded, setRailExpanded] = useState<boolean>(() => {
    try {
      return localStorage.getItem('boardroom.railExpanded') === '1';
    } catch {
      return false;
    }
  });

  const [railCollapsed, setRailCollapsed] = useState<boolean>(() => {
    try {
      return localStorage.getItem('boardroom.railCollapsed') === '1';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem('boardroom.railExpanded', railExpanded ? '1' : '0');
    } catch {
      /* ignore quota */
    }
  }, [railExpanded]);

  useEffect(() => {
    try {
      localStorage.setItem('boardroom.railCollapsed', railCollapsed ? '1' : '0');
    } catch {
      /* ignore quota */
    }
  }, [railCollapsed]);

  useEffect(() => {
    loadMembers()
      .then((payload) => {
        const ordered = orderMembers(payload);
        setMembers(ordered);
        setSeatStates(initialSeatStates(ordered));
      })
      .catch((err: unknown) => {
        console.error(err);
        setError('Failed to load board members.');
      });

    loadMetricsSummary()
      .then(setMetricsSummary)
      .catch(() => setMetricsSummary({}));

    loadSotb()
      .then(setSotb)
      .catch(() => setSotb({}));

    loadExecutionAgents()
      .then(setExecutionAgents)
      .catch(() => setExecutionAgents([]));
  }, []);

  useEffect(() => {
    if (session && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [session]);

  const orderedMembers = useMemo(() => orderMembers(members), [members]);
  const selectedSet = useMemo(() => new Set(manualMemberIds), [manualMemberIds]);
  const activeCouncilMembers = useMemo(() => {
    if (fullBoard) return orderedMembers;
    if (!manualMemberIds.length) return [];
    return orderedMembers.filter((member) => selectedSet.has(member.id));
  }, [fullBoard, manualMemberIds.length, orderedMembers, selectedSet]);

  const currentMetrics = session?.metrics || metricsSummary.metrics || {};
  const routingLabel = fullBoard
    ? 'Full board'
    : manualMemberIds.length > 1
    ? 'Manual council'
    : 'Adaptive routing';

  function toggleManualMember(id: string) {
    // Chairperson (the user / CEO) is permanent — cannot be removed from the table.
    if (id === 'chairperson') return;
    setFullBoard(false);
    setManualMemberIds((current) => {
      const isAdding = !current.includes(id);
      if (isAdding) {
        // Manual-add routing signal: fire immediately if a session exists,
        // otherwise queue locally and flush once the session_id+decision land.
        const sessionId = session?.session_id;
        if (sessionId) {
          recordRoutingSignal(sessionId, id, 'manual_add').catch(() => {
            /* best-effort */
          });
        } else {
          pendingManualAdds.current.push(id);
        }
      }
      return isAdding ? [...current, id] : current.filter((memberId) => memberId !== id);
    });
  }

  // Flush the pending manual-add log once the session has a real id and a decision.
  useEffect(() => {
    const sid = session?.session_id;
    if (!sid || !session?.decision) return;
    const queued = pendingManualAdds.current.splice(0);
    queued.forEach((id) => {
      recordRoutingSignal(sid, id, 'manual_add').catch(() => {
        /* best-effort */
      });
    });
  }, [session?.session_id, session?.decision]);

  async function submitQuery(event: FormEvent) {
    event.preventDefault();
    const cleanQuery = query.trim();
    if (!cleanQuery || running) return;

    // If a meeting is already at the CEO-decision checkpoint and we have headroom,
    // route this submit as a follow-up instead of starting a new meeting.
    if (
      session?.session_id &&
      tableStatus.label === 'CEO decision' &&
      (session.continuation_count ?? 0) < maxContinuations
    ) {
      setRunning(true);
      setError('');
      setQuery('');
      try {
        await sendFollowup(cleanQuery);
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : 'Follow-up failed.';
        setError(message);
        setTableStatus({ label: 'Error', title: 'Follow-up stopped', detail: message });
      } finally {
        setRunning(false);
      }
      return;
    }

    setRunning(true);
    setError('');
    setSession(null);
    setStageEvents([]);
    setLiveFeed([]);
    setConversationMessages((current) => [...current, {
      id: `user-${Date.now()}`,
      turn_index: 0,
      member_id: 'chairperson',
      member_title: 'CEO / Chairperson',
      role: 'CEO',
      speaker: 'user',
      content: cleanQuery,
      created_at: new Date().toISOString(),
    }]);
    setActiveStreamMessageId(null);
    setActivePhase(null);
    liveFeedCounter.current = 0;
    setSessionLabel('Session in progress');
    setSeatStates(resetSeatStates(orderedMembers, fullBoard, manualMemberIds));
    setTableStatus({
      label: 'Routing',
      title: fullBoard ? 'Convening the full board' : manualMemberIds.length ? 'Convening the selected council' : 'Selecting board members',
      detail: fullBoard || manualMemberIds.length
        ? 'The board is preparing the first pass.'
        : 'The classifier will route the decision to the smallest useful council.',
    });

    try {
      await streamDeliberation({
        query: cleanQuery,
        full_board: fullBoard,
        verify,
        discussion_mode: 'live',
        // Chairperson is permanent; only switch to manual-council mode when the
        // user has picked additional members beyond the chairperson.
        member_ids: fullBoard || manualMemberIds.length <= 1 ? undefined : manualMemberIds,
      }, {
        onEvent: handleStreamEvent,
      });
      loadMetricsSummary().then(setMetricsSummary).catch(() => undefined);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Deliberation failed.';
      setError(message);
      setTableStatus({
        label: 'Error',
        title: 'Deliberation stopped',
        detail: message,
      });
    } finally {
      setRunning(false);
    }
  }

  function pushLiveFeed(item: Omit<LiveFeedItem, 'id' | 'timestamp'>) {
    liveFeedCounter.current += 1;
    const entry: LiveFeedItem = {
      ...item,
      id: `feed-${liveFeedCounter.current}`,
      timestamp: Date.now(),
    };
    setLiveFeed((current) => [entry, ...current].slice(0, 8));
  }

  function handleStreamEvent(data: StreamEvent) {
    if (data.event === 'council_selected' && Array.isArray(data.member_ids)) {
      const selected = new Set(data.member_ids);
      setSeatStates((states) => {
        const next = { ...states };
        for (const memberId of selected) {
          next[memberId] = {
            ...(next[memberId] || {}),
            selected: true,
            status: next[memberId]?.status === 'done' ? 'done' : 'selected',
            label: next[memberId]?.label === 'selected' || !next[memberId]?.label ? 'selected' : next[memberId]?.label,
          };
        }
        return next;
      });
      return;
    }

    if (data.event === 'conversation_started') {
      setActivePhase('live_discussion');
      setTableStatus({
        label: 'Live',
        title: 'Board discussion underway',
        detail: 'Members are responding to one another in sequence.',
      });
      pushLiveFeed({ kind: 'phase', text: 'Live board discussion started' });
      return;
    }

    if (data.event === 'turn_routed' && data.member_id) {
      const text = data.routing_reason || `${data.member_title || data.member_id} was routed into the discussion.`;
      setConversationMessages((current) => [
        ...current,
        {
          id: `route-${data.session_id || 'live'}-${data.turn_index || current.length}-${data.member_id}`,
          turn_index: data.turn_index,
          member_id: data.member_id,
          member_title: data.member_title,
          speaker: 'system',
          content: text,
          trigger: data.trigger,
          routing_reason: data.routing_reason,
          reply_to_message_id: data.reply_to_message_id,
          created_at: new Date().toISOString(),
        },
      ]);
      pushLiveFeed({ kind: 'phase', memberId: data.member_id, memberTitle: data.member_title, text });
      return;
    }

    if (data.event === 'chair_decision_required') {
      const text = data.routing_reason || 'Board input is ready. The CEO / Chairperson should make the final call.';
      setConversationMessages((current) => [
        ...current,
        {
          id: `chair-required-${data.session_id || Date.now()}`,
          turn_index: data.turn_index,
          member_id: 'chairperson',
          member_title: 'CEO / Chairperson',
          speaker: 'system',
          content: text,
          trigger: data.trigger,
          routing_reason: data.routing_reason,
          reply_to_message_id: data.reply_to_message_id,
          created_at: new Date().toISOString(),
        },
      ]);
      setTableStatus({
        label: 'CEO decision',
        title: 'Board input ready',
        detail: text,
      });
      pushLiveFeed({ kind: 'phase', text });
      return;
    }

    if (data.event === 'message_start' && data.message_id && data.member_id) {
      setActiveStreamMessageId(data.message_id);
      setConversationMessages((current) => upsertConversationMessage(current, {
        id: data.message_id!,
        turn_index: data.turn_index,
        member_id: data.member_id,
        member_title: data.member_title,
        speaker: 'agent',
        content: '',
        reply_to_message_id: data.reply_to_message_id,
        trigger: data.trigger,
        routing_reason: data.routing_reason,
        created_at: new Date().toISOString(),
      }));
      setSeatStates((states) => ({
        ...states,
        [data.member_id!]: {
          ...(states[data.member_id!] || {}),
          status: 'active',
          label: 'speaking live',
        },
      }));
      return;
    }

    if (data.event === 'message_delta' && data.message_id) {
      setConversationMessages((current) => upsertConversationMessage(current, {
        id: data.message_id!,
        turn_index: data.turn_index,
        member_id: data.member_id,
        member_title: data.member_title,
        speaker: 'agent',
        content: data.content || '',
        simulated_stream: data.simulated_stream,
      }));
      return;
    }

    if (data.event === 'message_done' && data.message_id) {
      setConversationMessages((current) => upsertConversationMessage(current, {
        id: data.message_id!,
        turn_index: data.turn_index,
        member_id: data.member_id,
        member_title: data.member_title,
        speaker: 'agent',
        content: data.content || '',
        model: data.model,
        elapsed_seconds: data.elapsed,
        input_tokens: data.input_tokens,
        output_tokens: data.output_tokens,
        finish_reason: data.finish_reason,
        simulated_stream: data.simulated_stream,
      }));
      setActiveStreamMessageId((current) => current === data.message_id ? null : current);
      if (data.member_id) {
        setSeatStates((states) => ({
          ...states,
          [data.member_id!]: {
            ...(states[data.member_id!] || {}),
            status: 'done',
            label: 'live done',
            model: data.model,
          },
        }));
      }
      pushLiveFeed({
        kind: 'done',
        memberId: data.member_id,
        memberTitle: data.member_title,
        text: `${data.member_title || data.member_id || 'Board member'} responded`,
      });
      return;
    }

    // ── Secretary Executive Brief (live discussion post-summary) ──────
    if (data.event === 'secretary_starting' && data.member_id) {
      const briefId = data.message_id || `secretary-brief-${data.session_id || Date.now()}`;
      const roundIndex = data.round_index ?? 0;
      setActiveStreamMessageId(briefId);
      setConversationMessages((current) => [
        ...current,
        {
          id: briefId,
          turn_index: -1,
          member_id: data.member_id,
          member_title: data.member_title || 'Board Secretary',
          speaker: 'agent',
          content: '',
          role: 'Secretary',
          created_at: new Date().toISOString(),
        },
      ]);
      setSeatStates((states) => ({
        ...states,
        [data.member_id!]: { status: 'active', label: 'summarizing...' },
      }));
      pushLiveFeed({ kind: 'speaking', memberId: data.member_id, text: `Secretary preparing brief for round ${roundIndex}...` });
      return;
    }

    if (data.event === 'secretary_delta' && data.message_id) {
      setConversationMessages((current) => upsertConversationMessage(current, {
        id: data.message_id!,
        turn_index: -1,
        member_id: data.member_id,
        member_title: data.member_title,
        speaker: 'agent',
        content: data.content || '',
        role: 'Secretary',
        simulated_stream: data.simulated_stream,
      }));
      return;
    }

    if (data.event === 'secretary_done' && data.message_id) {
      const roundIndex = data.round_index ?? 0;
      setConversationMessages((current) => upsertConversationMessage(current, {
        id: data.message_id!,
        turn_index: -1,
        member_id: data.member_id,
        member_title: data.member_title,
        speaker: 'agent',
        content: data.content || '',
        model: data.model,
        elapsed_seconds: data.elapsed,
        role: 'Secretary',
        simulated_stream: false,
      }));
      setActiveStreamMessageId((current) =>
        current === data.message_id ? null : current
      );
      if (data.member_id) {
        setSeatStates((states) => ({
          ...states,
          [data.member_id!]: { status: 'done', label: 'brief ready', model: data.model },
        }));
      }
      pushLiveFeed({
        kind: 'done',
        memberId: data.member_id,
        text: `${data.member_title || 'Secretary'} completed brief for round ${roundIndex}`,
      });
      return;
    }

    if (data.event === 'secretary_failed') {
      setActiveStreamMessageId(null);
      pushLiveFeed({ kind: 'failed', text: `Secretary brief failed: ${data.error || 'unknown error'}` });
      return;
    }

    if (data.event === 'meeting_capped') {
      pushLiveFeed({
        kind: 'failed',
        text: `Continuation cap reached (${data.continuation_count}/${data.max_continuations}). Start a new meeting to continue.`,
      });
      setTableStatus({ label: 'CEO decision', title: 'Cap reached — start new meeting to continue', detail: '' });
      return;
    }

    if (data.event === 'conversation_done') {
      setActiveStreamMessageId(null);
      if (data.status === 'awaiting_chair_decision') {
        setTableStatus({
          label: 'CEO decision',
          title: 'Board input ready',
          detail: 'Review the discussion and make the final call as CEO / Chairperson.',
        });
      } else {
        setTableStatus({
          label: 'Complete',
          title: 'Discussion complete',
          detail: `${data.message_count || conversationMessages.length} conversation messages captured.`,
        });
      }
      return;
    }

    if (data.event === 'phase_change' && data.phase) {
      setActivePhase(data.phase);
      const message = data.message || humanize(data.phase);
      pushLiveFeed({ kind: 'phase', text: message });
      setTableStatus((current) => ({
        ...current,
        label: 'Post synthesis',
        title: humanize(data.phase),
        detail: message,
      }));
      return;
    }

    if (data.event === 'member_speaking' && data.stage && data.member_id) {
      setSeatStates((states) => ({
        ...states,
        [data.member_id!]: {
          ...(states[data.member_id!] || {}),
          status: 'active',
          label: data.stage === 3 ? 'synthesizing' : `speaking • ${stageShortLabel(data.stage)}`,
        },
      }));
      pushLiveFeed({
        kind: 'speaking',
        memberId: data.member_id,
        memberTitle: data.member_title,
        stage: data.stage,
        text: `${data.member_title || data.member_id} is ${data.stage === 3 ? 'synthesizing' : stageShortLabel(data.stage) === 'analysis' ? 'giving an independent read' : 'challenging peers'}`,
      });
      return;
    }

    if (data.event === 'stage_start' && data.stage) {
      setTableStatus(statusForStageStart(data.stage, data.name));
      setStageEvents((events) => upsertStage(events, data.stage!, {
        active: true,
        done: false,
        count: 0,
        members: [],
      }));
      pushLiveFeed({
        kind: 'stage',
        stage: data.stage,
        text: `Stage ${data.stage}: ${STAGE_NAMES[data.stage] || data.name || 'in progress'}`,
      });
      if (data.stage === 3) {
        setSeatStates((states) => ({
          ...states,
          chairperson: {
            ...(states.chairperson || {}),
            status: 'active',
            label: 'synthesizing',
          },
        }));
      }
      return;
    }

    if (data.event === 'member_done' && data.stage && data.member_id) {
      setStageEvents((events) => addStageMember(events, data.stage!, {
        id: data.member_id,
        title: data.member_title,
        model: data.model,
        elapsed: data.elapsed,
        content: data.content,
        failed: false,
      }));
      setSeatStates((states) => ({
        ...states,
        [data.member_id!]: {
          ...(states[data.member_id!] || {}),
          status: 'done',
          label: `${stageShortLabel(data.stage)} done`,
          model: data.model,
        },
      }));
      setTableStatus((current) => ({
        ...current,
        detail: `${data.member_title || data.member_id} completed ${stageShortLabel(data.stage)}.`,
      }));
      pushLiveFeed({
        kind: 'done',
        memberId: data.member_id,
        memberTitle: data.member_title,
        stage: data.stage,
        text: `${data.member_title || data.member_id} finished ${stageShortLabel(data.stage)}`,
      });
      return;
    }

    if (data.event === 'member_failed' && data.stage && data.member_id) {
      setStageEvents((events) => addStageMember(events, data.stage!, {
        id: data.member_id,
        title: data.member_title,
        error: data.error,
        failed: true,
      }));
      setSeatStates((states) => ({
        ...states,
        [data.member_id!]: {
          ...(states[data.member_id!] || {}),
          status: 'failed',
          label: 'failed',
        },
      }));
      pushLiveFeed({
        kind: 'failed',
        memberId: data.member_id,
        memberTitle: data.member_title,
        stage: data.stage,
        text: `${data.member_title || data.member_id} failed ${stageShortLabel(data.stage)}`,
      });
      return;
    }

    if (data.event === 'stage_done' && data.stage) {
      setStageEvents((events) => upsertStage(events, data.stage!, {
        active: false,
        done: true,
        count: data.count,
      }));
      setTableStatus({
        label: `Stage ${data.stage}`,
        title: `${STAGE_NAMES[data.stage] || 'Stage'} complete`,
        detail: `${data.count || 0} response${data.count === 1 ? '' : 's'} collected.`,
      });
      return;
    }

    if (data.event === 'complete') {
      const nextSession = data.session || null;
      setSession(nextSession);
      setSessionLabel(nextSession?.session_id || 'Session complete');
      markSelectedMembers(nextSession?.classification);
      setActivePhase(null);
      if (nextSession?.status === 'awaiting_chair_decision' && !nextSession?.decision) {
        pushLiveFeed({ kind: 'phase', text: 'Board input ready for CEO decision' });
        setTableStatus({
          label: 'CEO decision',
          title: 'Board input ready',
          detail: 'No automatic chair decision was generated. Review the conversation and make the call.',
        });
      } else {
        pushLiveFeed({ kind: 'phase', text: 'Board decision ready' });
        setTableStatus({
          label: 'Complete',
          title: 'Board decision ready',
          detail: 'Review the direction, risks, dissent, verification, and memory proposal.',
        });
      }
      return;
    }

    if (data.event === 'error') {
      const message = data.message || 'Deliberation failed.';
      setError(message);
      setTableStatus({
        label: 'Error',
        title: 'Deliberation stopped',
        detail: message,
      });
    }
  }

  async function approveDelegatedTask(taskId: string) {
    try {
      const task = await approveTask(taskId, true);
      mergeDelegatedTask(task);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve task.');
    }
  }

  async function planDelegatedTask(task: DelegatedTask) {
    try {
      const planned = await planTask(task.id, task.manager_agent_id);
      mergeDelegatedTask(planned);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to plan task.');
    }
  }

  async function sendFollowup(text: string) {
    const sessionId = session?.session_id;
    if (!sessionId) return;
    setActiveStreamMessageId(null);
    try {
      await streamContinuation(sessionId, text, { onEvent: handleStreamEvent });
      loadMetricsSummary().then(setMetricsSummary).catch(() => undefined);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Follow-up failed.';
      pushLiveFeed({ kind: 'failed', text: `Follow-up rejected: ${message}` });
    }
  }

  function mergeDelegatedTask(task: DelegatedTask) {
    setSession((current) => {
      if (!current?.delegation_plan) return current;
      return {
        ...current,
        delegation_plan: {
          ...current.delegation_plan,
          tasks: current.delegation_plan.tasks.map((item) => item.id === task.id ? task : item),
        },
      };
    });
  }

  function markSelectedMembers(classification?: Classification) {
    const selected = new Set(classification?.relevant_member_ids || manualMemberIds);
    if (fullBoard) {
      orderedMembers.forEach((member) => selected.add(member.id));
    }
    if (!selected.size) return;
    setSeatStates((states) => {
      const next = { ...states };
      for (const memberId of selected) {
        next[memberId] = {
          ...(next[memberId] || {}),
          selected: true,
          label: next[memberId]?.label || 'selected',
        };
      }
      return next;
    });
  }

  return (
    <div className="min-h-screen flex bg-background text-on-surface">
      <IconRail
        active={activeTab}
        onSelect={setActiveTab}
        expanded={railExpanded}
        collapsed={railCollapsed}
        onToggleExpand={() => setRailExpanded((v) => !v)}
        onToggleCollapse={() => setRailCollapsed((v) => !v)}
        sessionLabel={sessionLabel}
      />

      {/* Collapsed rail tab — shown only when fully collapsed */}
      {railCollapsed && (
        <div
          className="fixed left-0 top-0 bottom-0 z-40 flex w-10 flex-col items-center bg-surface-container-low shadow-[4px_0_16px_-10px_rgba(26,22,20,0.24)]"
          aria-label="Collapsed navigation"
        >
          <button
            type="button"
            onClick={() => setRailCollapsed(false)}
            className="mt-4 grid h-9 w-9 place-items-center rounded-full bg-surface-container-high hover:bg-surface-container-highest transition-colors"
            aria-label="Open navigation"
            title="Open navigation"
          >
            <Landmark className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />
          </button>
          <div className="flex flex-1 items-center justify-center py-4">
            <span className="rotate-180 text-[10px] font-body font-semibold uppercase tracking-wider text-on-surface-variant [writing-mode:vertical-rl]">
              Menu
            </span>
          </div>
        </div>
      )}

      <main
        className="flex-1 min-h-screen min-w-0"
        style={{ marginLeft: railCollapsed ? 40 : railExpanded ? 240 : 72 }}
      >
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.18 }}
          >
            {activeTab === 'governance' && (
              <GovernancePage
                members={orderedMembers}
                activeCouncilMembers={activeCouncilMembers}
                manualMemberIds={manualMemberIds}
                toggleManualMember={toggleManualMember}
                fullBoard={fullBoard}
                verify={verify}
                setVerify={setVerify}
                setFullBoard={setFullBoard}
                query={query}
                setQuery={setQuery}
                running={running}
                onSubmit={submitQuery}
                tableStatus={tableStatus}
                stageEvents={stageEvents}
                seatStates={seatStates}
                session={session}
                error={error}
                routingLabel={routingLabel}
                sotb={sotb}
                executionAgents={executionAgents}
                onApproveTask={approveDelegatedTask}
                onPlanTask={planDelegatedTask}
                resultRef={resultRef}
                liveFeed={liveFeed}
                activePhase={activePhase}
                conversationMessages={conversationMessages}
                activeStreamMessageId={activeStreamMessageId}
                awaitingFollowup={
                  tableStatus.label === 'CEO decision' &&
                  (session?.continuation_count ?? 0) < maxContinuations
                }
                capReached={
                  tableStatus.label === 'CEO decision' &&
                  (session?.continuation_count ?? 0) >= maxContinuations
                }
              />
            )}
            {activeTab === 'performance' && (
              <PerformancePage metrics={currentMetrics} session={session} />
            )}
            {activeTab === 'portfolio' && (
              <PortfolioPage members={orderedMembers} seatStates={seatStates} executionAgents={executionAgents} />
            )}
          </motion.div>
        </AnimatePresence>

        <footer className="px-8 py-3 text-[10px] text-on-surface-variant/50">
          The Executive Atelier &copy; 2026. Authority and Craftsmanship.
        </footer>
      </main>
    </div>
  );
}

function IconRail({
  active,
  onSelect,
  expanded,
  collapsed,
  onToggleExpand,
  onToggleCollapse,
  sessionLabel,
}: {
  active: Tab;
  onSelect: (tab: Tab) => void;
  expanded: boolean;
  collapsed: boolean;
  onToggleExpand: () => void;
  onToggleCollapse: () => void;
  sessionLabel: string;
}) {
  if (collapsed) return null;

  return (
    <nav
      className={`fixed left-0 top-0 h-screen z-40 flex flex-col py-4 transition-[width] duration-200 bg-surface-container-low ${
        expanded ? 'w-[240px]' : 'w-[72px]'
      }`}
      aria-label="Primary"
    >
      {/* Logo / Brand row — toggles expand/collapse width */}
      <div className="flex items-center gap-3 px-4 py-3">
        <button
          type="button"
          onClick={onToggleExpand}
          className="flex items-center gap-3 hover:bg-surface-container-high transition-colors rounded-lg -ml-2 px-2 py-1"
          aria-label="Toggle navigation width"
        >
          <div className="w-10 h-10 flex items-center justify-center font-headline text-lg font-bold text-primary-container italic">
            EA
          </div>
          {expanded && (
            <span className="font-headline italic text-lg text-on-surface">
              The Executive Atelier
            </span>
          )}
        </button>
        {/* Full collapse button (chevron) */}
        <button
          type="button"
          onClick={onToggleCollapse}
          className="grid h-7 w-7 shrink-0 place-items-center rounded-full hover:bg-surface-container-high transition-colors ml-auto"
          aria-label="Collapse navigation"
          title="Collapse to arrow tab"
        >
          <ChevronLeft className="h-3.5 w-3.5 text-on-surface-variant" />
        </button>
      </div>

      <ul className="flex flex-col gap-1 mt-6 px-2">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
          const isActive = id === active;
          return (
            <li key={id}>
              <button
                type="button"
                onClick={() => onSelect(id)}
                aria-current={isActive ? 'page' : undefined}
                className={`w-full flex items-center gap-3 px-3 py-3 rounded-lg transition-colors ${
                  isActive
                    ? 'accent-bar-left bg-surface-container-high text-on-surface'
                    : 'text-on-surface-variant/60 hover:bg-surface-container-low hover:text-on-surface'
                }`}
                title={expanded ? undefined : label}
              >
                <Icon className="w-5 h-5 shrink-0" />
                {expanded && <span className="font-body text-sm">{label}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto px-2 pb-2 flex flex-col gap-1">
        {expanded && sessionLabel && (
          <div
            className="mx-1 mb-2 truncate rounded-lg bg-surface-container-lowest px-3 py-2 text-[11px] font-medium text-on-surface-variant"
            title={sessionLabel}
          >
            {sessionLabel}
          </div>
        )}
        <button
          type="button"
          className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-on-surface-variant/60 hover:bg-surface-container-low hover:text-on-surface"
          title={expanded ? undefined : 'Settings'}
        >
          <Settings className="w-5 h-5 shrink-0" />
          {expanded && <span className="font-body text-sm">Settings</span>}
        </button>
        <button
          type="button"
          className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-on-surface-variant/60 hover:bg-surface-container-low hover:text-on-surface"
          title={expanded ? undefined : 'Account'}
        >
          <LogIn className="w-5 h-5 shrink-0" />
          {expanded && <span className="font-body text-sm">Account</span>}
        </button>
      </div>
    </nav>
  );
}
