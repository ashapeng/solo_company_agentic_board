import type { FormEvent } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Bell, Check, Circle, Rocket, Settings, Users } from 'lucide-react';
import {
  GovernancePage,
  PortfolioPage,
  loadMembers,
  streamDeliberation,
  type BoardMember,
  type BoardSession,
  type Classification,
  type SeatState,
  type StageEvent,
  type StageMember,
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
  MEMBER_ICONS,
  MEMBER_IMAGES,
  STAGE_NAMES,
  addStageMember,
  initialSeatStates,
  orderMembers,
  resetSeatStates,
  roleShort,
  stageShortLabel,
  statusForStageStart,
  upsertStage,
} from './shared/presentation';

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

  function handleStreamEvent(data: StreamEvent) {
    if (data.event === 'stage_start' && data.stage) {
      setTableStatus(statusForStageStart(data.stage, data.name));
      setStageEvents((events) => upsertStage(events, data.stage!, {
        active: true,
        done: false,
        count: 0,
        members: [],
      }));
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
    <div className="min-h-screen bg-[#f8fafc] text-[#0f172a] selection:bg-[#dae2ff] selection:text-[#001848]">
      <Navbar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        sessionLabel={sessionLabel}
        memberCount={orderedMembers.length}
      />

      <div className="flex min-h-screen pt-16">
        <Sidebar
          members={orderedMembers}
          selectedMemberIds={manualMemberIds}
          fullBoard={fullBoard}
          onToggleMember={toggleManualMember}
          onClear={() => setManualMemberIds([])}
        />

        <main className="min-w-0 flex-1 md:ml-20">
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
        </main>
      </div>
    </div>
  );
}

function Navbar({
  activeTab,
  setActiveTab,
  sessionLabel,
  memberCount,
}: {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  sessionLabel: string;
  memberCount: number;
}) {
  const tabs: Array<{ id: Tab; label: string }> = [
    { id: 'portfolio', label: 'Portfolio' },
    { id: 'governance', label: 'Governance' },
    { id: 'performance', label: 'Compliance' },
  ];

  return (
    <nav className="fixed top-0 z-50 flex h-16 w-full items-center justify-between border-b border-[#e2e8f0] bg-white/80 px-4 shadow-sm backdrop-blur-xl md:px-8">
      <div className="flex min-w-0 items-center gap-8">
        <div className="min-w-0">
          <p className="truncate font-headline text-xl font-extrabold tracking-tight text-primary md:text-2xl">The Executive Atelier</p>
          <p className="sr-only">{memberCount} board members loaded</p>
        </div>
        <div className="hidden h-16 items-center gap-1 md:flex">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`h-full border-b-2 px-3 text-sm font-bold transition-colors ${
                activeTab === tab.id
                  ? 'border-primary text-primary'
                  : 'border-transparent text-slate-500 hover:text-slate-900'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex min-w-0 items-center gap-2">
        <span className="hidden max-w-[260px] truncate rounded-lg border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2 text-sm font-semibold text-slate-500 lg:inline">
          {sessionLabel}
        </span>
        <button className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900" type="button" aria-label="Notifications">
          <Bell className="h-5 w-5" />
        </button>
        <button className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-slate-50 hover:text-slate-900" type="button" aria-label="Settings">
          <Settings className="h-5 w-5" />
        </button>
        <img
          src={MEMBER_IMAGES.product}
          alt=""
          aria-hidden="true"
          className="hidden h-10 w-10 rounded-full border-2 border-primary-container bg-surface-container-high object-cover p-0.5 sm:block"
        />
      </div>
    </nav>
  );
}

function Sidebar({
  members,
  selectedMemberIds,
  fullBoard,
  onToggleMember,
  onClear,
}: {
  members: BoardMember[];
  selectedMemberIds: string[];
  fullBoard: boolean;
  onToggleMember: (id: string) => void;
  onClear: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <aside
      onMouseEnter={() => setExpanded(true)}
      onMouseLeave={() => setExpanded(false)}
      className={`fixed left-0 top-16 z-40 hidden h-[calc(100vh-4rem)] flex-col gap-2 overflow-hidden bg-slate-50 p-4 transition-[width] duration-300 md:flex ${
        expanded ? 'w-72' : 'w-20'
      }`}
    >
      <div className="mb-2 flex items-center gap-3 overflow-hidden px-1 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-container text-on-primary-container">
          <Users className="h-5 w-5" />
        </div>
        {expanded && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="min-w-0">
            <h2 className="truncate font-headline text-sm font-extrabold text-primary">Execution Units</h2>
            <p className="mt-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Agentic Teams</p>
          </motion.div>
        )}
      </div>

      <div className="no-scrollbar flex-1 space-y-1 overflow-y-auto">
        {members.map((member) => {
          const selected = fullBoard || selectedMemberIds.includes(member.id);
          const Icon = MEMBER_ICONS[member.id] || Circle;
          return (
            <button
              key={member.id}
              type="button"
              onClick={() => onToggleMember(member.id)}
              className={`group flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left transition-colors ${
                selected ? 'bg-white text-primary shadow-sm' : 'text-slate-600 hover:bg-slate-100'
              }`}
              aria-pressed={selected}
            >
              <span className="flex shrink-0 items-center justify-center">
                {selected ? <Check className="h-5 w-5" /> : <Icon className="h-5 w-5" />}
              </span>
              {expanded && (
                <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-bold">{member.title}</span>
                  <span className={`block truncate text-xs ${selected ? 'text-primary/70' : 'text-slate-500'}`}>
                    {member.governance_seat || roleShort(member.role)}
                  </span>
                </motion.div>
              )}
            </button>
          );
        })}
      </div>

      {expanded && (
        <div className="mt-auto border-t border-slate-200 pt-4">
          <button
            type="button"
            onClick={onClear}
            className="flex h-12 w-full items-center justify-center gap-2 rounded-lg bg-primary px-3 text-sm font-bold text-white shadow-lg shadow-primary/20 transition hover:bg-primary-container"
          >
            <Rocket className="h-4 w-4" />
            Deploy Agent
          </button>
          <p className="mt-3 px-2 text-xs font-semibold text-slate-500">Adaptive routing when no unit is locked.</p>
        </div>
      )}
    </aside>
  );
}
