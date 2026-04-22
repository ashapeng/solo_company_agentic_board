import type { FormEvent } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Landmark, LogIn, Settings, ShieldCheck, Users } from 'lucide-react';
import {
  GovernancePage,
  PortfolioPage,
  loadMembers,
  streamDeliberation,
  type BoardMember,
  type BoardSession,
  type Classification,
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

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('governance');
  const [members, setMembers] = useState<BoardMember[]>([]);
  const [executionAgents, setExecutionAgents] = useState<ExecutionAgent[]>([]);
  const [manualMemberIds, setManualMemberIds] = useState<string[]>([]);
  const [query, setQuery] = useState('');
  const [fullBoard, setFullBoard] = useState(false);
  const [verify, setVerify] = useState(false);
  const [running, setRunning] = useState(false);
  const [session, setSession] = useState<BoardSession | null>(null);
  const [stageEvents, setStageEvents] = useState<StageEvent[]>([]);
  const [seatStates, setSeatStates] = useState<Record<string, SeatState>>({});
  const [liveFeed, setLiveFeed] = useState<LiveFeedItem[]>([]);
  const [activePhase, setActivePhase] = useState<string | null>(null);
  const liveFeedCounter = useRef(0);
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

  useEffect(() => {
    try {
      localStorage.setItem('boardroom.railExpanded', railExpanded ? '1' : '0');
    } catch {
      /* ignore quota */
    }
  }, [railExpanded]);

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
  const routingLabel = fullBoard ? 'Full board' : manualMemberIds.length ? 'Manual council' : 'Adaptive routing';

  function toggleManualMember(id: string) {
    setFullBoard(false);
    setManualMemberIds((current) => (
      current.includes(id) ? current.filter((memberId) => memberId !== id) : [...current, id]
    ));
  }

  async function submitQuery(event: FormEvent) {
    event.preventDefault();
    const cleanQuery = query.trim();
    if (!cleanQuery || running) return;

    setRunning(true);
    setError('');
    setSession(null);
    setStageEvents([]);
    setLiveFeed([]);
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
        member_ids: fullBoard || !manualMemberIds.length ? undefined : manualMemberIds,
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
      pushLiveFeed({ kind: 'phase', text: 'Board decision ready' });
      setTableStatus({
        label: 'Complete',
        title: 'Board decision ready',
        detail: 'Review the direction, risks, dissent, verification, and memory proposal.',
      });
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
        onToggleExpand={() => setRailExpanded((v) => !v)}
        sessionLabel={sessionLabel}
      />

      <main
        className="flex-1 min-h-screen min-w-0"
        style={{ marginLeft: railExpanded ? 240 : 72 }}
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
  onToggleExpand,
  sessionLabel,
}: {
  active: Tab;
  onSelect: (tab: Tab) => void;
  expanded: boolean;
  onToggleExpand: () => void;
  sessionLabel: string;
}) {
  return (
    <nav
      className={`fixed left-0 top-0 h-screen z-40 flex flex-col py-4 transition-[width] duration-200 bg-surface-container-low ${
        expanded ? 'w-[240px]' : 'w-[72px]'
      }`}
      aria-label="Primary"
    >
      <button
        type="button"
        onClick={onToggleExpand}
        className="flex items-center gap-3 px-4 py-3 hover:bg-surface-container-high transition-colors"
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
