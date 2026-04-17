import type { CSSProperties, FormEvent, RefObject } from 'react';
import {
  Activity,
  BarChart3,
  Bolt,
  FileText,
  Send,
  ShieldCheck,
  Terminal,
  Users,
} from 'lucide-react';
import tableTextureUrl from '../../../assets/council-table-texture.png';
import { AgentExecutionPanel } from '../execution';
import { FeedbackWidget, SotbCard } from '../memory';
import {
  ErrorMessage,
  MaterialCard,
  PanelHeading,
  PlainList,
  SectionLabel,
  StageIndicator,
} from '../../shared/components';
import {
  MEMBER_ICONS,
  MEMBER_IMAGES,
  STAGE_NAMES,
  compactList,
  getSynthesis,
  humanize,
  memberDossier,
  memberTone,
  renderMarkdown,
  roleShort,
  stageShortLabel,
  stripMarkdown,
  taskStatusClass,
} from '../../shared/presentation';
import type {
  BoardMember,
  BoardSession,
  DelegatedTask,
  ExecutionAgent,
  SeatState,
  StageEvent,
  TableStatus,
} from '../../shared/types';

export function GovernancePage({
  members,
  activeCouncilMembers,
  manualMemberIds,
  fullBoard,
  verify,
  setVerify,
  setFullBoard,
  query,
  setQuery,
  running,
  onSubmit,
  tableStatus,
  stageEvents,
  seatStates,
  session,
  error,
  routingLabel,
  sotb,
  executionAgents,
  onApproveTask,
  onPlanTask,
  resultRef,
}: {
  members: BoardMember[];
  activeCouncilMembers: BoardMember[];
  manualMemberIds: string[];
  fullBoard: boolean;
  verify: boolean;
  setVerify: (value: boolean) => void;
  setFullBoard: (value: boolean) => void;
  query: string;
  setQuery: (value: string) => void;
  running: boolean;
  onSubmit: (event: FormEvent) => void;
  tableStatus: TableStatus;
  stageEvents: StageEvent[];
  seatStates: Record<string, SeatState>;
  session: BoardSession | null;
  error: string;
  routingLabel: string;
  sotb: { content?: string; path?: string };
  executionAgents: ExecutionAgent[];
  onApproveTask: (taskId: string) => void;
  onPlanTask: (task: DelegatedTask) => void;
  resultRef: RefObject<HTMLDivElement | null>;
}) {
  const displayCouncil = activeCouncilMembers.length ? activeCouncilMembers : members;
  const latestQuery = session?.user_query || query || 'Awaiting board question';

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-surface">
      <div className="grid min-h-[calc(100vh-4rem)] grid-cols-12">
        <section className="col-span-12 flex flex-col gap-6 bg-surface-container-low p-6 xl:col-span-3">
          <SectionLabel>Meeting Insights</SectionLabel>
          <div className="grid gap-4">
            <StatusCard status={tableStatus} />
            <StageDigest stages={stageEvents} />
          </div>

          <div>
            <SectionLabel>Meeting Materials</SectionLabel>
            <div className="mt-4 grid gap-3">
              <MaterialCard icon={<FileText className="h-5 w-5" />} title="SOTB_Memory.md" subtitle="Board Memory - Live" />
              <MaterialCard icon={<BarChart3 className="h-5 w-5" />} title="Deliberation_Metrics.json" subtitle="Updated after each run" />
            </div>
          </div>

          <div className="mt-auto">
            <SotbCard sotb={sotb} />
          </div>
        </section>

        <section className="relative col-span-12 flex min-h-[720px] flex-col overflow-visible bg-surface p-8 xl:col-span-6">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(0,61,155,0.08)_0%,transparent_70%)]" />
          <div className="relative z-10 mx-auto mb-4 max-w-2xl text-center">
            <span className="inline-flex min-h-8 items-center rounded-lg bg-primary-container px-4 py-1.5 text-xs font-extrabold uppercase tracking-widest text-on-primary-container">
              Current Topic
            </span>
            <h1 className="mt-4 break-words font-headline text-3xl font-extrabold leading-tight tracking-tight text-primary md:text-4xl">
              {latestQuery}
            </h1>
            <div className="mt-3 flex flex-wrap items-center justify-center gap-3 text-sm font-semibold text-on-surface-variant">
              <span className="inline-flex items-center gap-2">
                <Users className="h-4 w-4 text-primary" />
                {activeCouncilMembers.length || (fullBoard ? members.length : 0) || 'Adaptive'} present
              </span>
              <span className="inline-flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-primary" />
                Verification {verify ? 'on' : 'off'}
              </span>
            </div>
          </div>

          <div className="flex flex-1 flex-col justify-center">
            <RoundTable
              members={members}
              displayCouncil={displayCouncil}
              seatStates={seatStates}
              tableStatus={tableStatus}
            />
          </div>

          <CeoComposer
            query={query}
            setQuery={setQuery}
            fullBoard={fullBoard}
            setFullBoard={setFullBoard}
            verify={verify}
            setVerify={setVerify}
            manualCount={manualMemberIds.length}
            running={running}
            onSubmit={onSubmit}
          />
        </section>

        <section className="col-span-12 bg-white p-6 xl:col-span-3">
          <SectionLabel>Action Items</SectionLabel>
          <div className="mt-6 grid gap-4">
            <SelectedDigest members={members} states={seatStates} activeCouncilMembers={activeCouncilMembers} fullBoard={fullBoard} />
            <DecisionPreview session={session} error={error} />
          </div>

          <div className="mt-8">
            <SectionLabel>Execution Roadmap</SectionLabel>
            <div className="mt-6">
              <AgentExecutionPanel
                delegationPlan={session?.delegation_plan || null}
                executionAgents={executionAgents}
                routingLabel={routingLabel}
                onApproveTask={onApproveTask}
                onPlanTask={onPlanTask}
              />
            </div>
          </div>

          <div className="mt-6 grid gap-4">
            <RunSettings fullBoard={fullBoard} manualCount={manualMemberIds.length} verify={verify} />
          </div>
        </section>
      </div>

      {(stageEvents.length > 0 || session || error) && (
        <section ref={resultRef} className="mx-auto grid w-full max-w-7xl gap-5 px-4 py-6 md:px-6">
          {stageEvents.length > 0 && (
            <section className="rounded-lg border border-[#e2e8f0] bg-white p-5 shadow-sm">
              <PanelHeading icon={<Activity className="h-4 w-4" />} kicker="Timeline" title="Deliberation" />
              <StageTimeline stages={stageEvents} />
            </section>
          )}

          {(session || error) && (
            <section className="rounded-lg border border-[#e2e8f0] bg-white p-5 shadow-sm">
              <PanelHeading icon={<FileText className="h-4 w-4" />} kicker="Board Decision" title="Decision Record" />
              {error ? <ErrorMessage message={error} /> : <DecisionRecord session={session} />}
            </section>
          )}
        </section>
      )}
    </div>
  );
}

function RoundTable({
  members,
  displayCouncil,
  seatStates,
}: {
  members: BoardMember[];
  displayCouncil: BoardMember[];
  seatStates: Record<string, SeatState>;
  tableStatus: TableStatus;
}) {
  const displayIds = new Set(displayCouncil.map((member) => member.id));

  return (
    <div className="mx-auto w-full max-w-[680px]">
      <div className="board-orbit relative mx-auto flex aspect-square w-full max-w-[640px] items-center justify-center">
        <div className="absolute inset-[12%] rounded-full border border-slate-100 bg-white shadow-[0_32px_80px_rgba(37,99,235,0.08)] transition-all duration-700" />
        <img
          src={tableTextureUrl}
          alt=""
          className="absolute w-[68%] select-none opacity-45 drop-shadow-xl saturate-0"
          aria-hidden="true"
        />
        <div className="relative z-10 text-center transition-transform duration-300 hover:scale-110">
          <div className="mx-auto mb-3 grid h-24 w-24 place-items-center rounded-full bg-primary/5 text-primary shadow-inner">
            <Bolt className="h-10 w-10 fill-primary" />
          </div>
          <p className="text-[10px] font-extrabold uppercase tracking-[0.3em] text-primary/40">Round Table Collective</p>
        </div>

        <div className="absolute inset-0 hidden md:block">
          {members.map((member, index) => {
            const angle = (index / Math.max(members.length, 1)) * 360 - 90;
            const state = seatStates[member.id] || {};
            const tone = memberTone(member.id);
            const isMuted = displayCouncil.length > 0 && !displayIds.has(member.id) && !state.selected && state.status !== 'done';
            const radius = 250;
            return (
              <BoardAvatar
                key={member.id}
                member={member}
                state={state}
                muted={isMuted}
                style={{
                  '--tone': tone,
                  left: `calc(50% + ${Math.cos((angle * Math.PI) / 180) * radius}px)`,
                  top: `calc(50% + ${Math.sin((angle * Math.PI) / 180) * radius}px)`,
                } as CSSProperties}
              />
            );
          })}
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 md:hidden">
        {members.map((member) => (
          <MobileMember key={member.id} member={member} state={seatStates[member.id]} />
        ))}
      </div>
    </div>
  );
}

function BoardAvatar({
  member,
  state = {},
  muted,
  style,
}: {
  member: BoardMember;
  state?: SeatState;
  muted?: boolean;
  style: CSSProperties;
}) {
  const Icon = MEMBER_ICONS[member.id] || Users;
  const status = state.status || (state.selected ? 'selected' : 'idle');
  const dossier = memberDossier(member);
  const imageUrl = MEMBER_IMAGES[member.id];
  const skills = [
    ...compactList(member.expertise).slice(0, 2),
    ...compactList(member.capabilities).slice(0, 1),
  ];

  return (
    <div
      className={`member-orbit-seat group absolute z-20 h-16 w-16 -translate-x-1/2 -translate-y-1/2 ${
        muted ? 'opacity-45' : 'opacity-100'
      }`}
      style={style}
    >
      <div className="avatar-pop relative h-16 w-16 cursor-pointer transition-all duration-200">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt=""
            aria-hidden="true"
            className={`h-16 w-16 rounded-full border-4 border-white object-cover shadow-lg ring-4 ${
              status === 'done' ? 'ring-emerald-100' : status === 'failed' ? 'ring-rose-100' : status === 'active' || status === 'selected' ? 'ring-primary-fixed' : 'ring-slate-100'
            }`}
          />
        ) : (
          <div className="grid h-16 w-16 place-items-center rounded-full border-4 border-white bg-primary/5 text-primary shadow-xl ring-4 ring-primary-fixed">
            <Icon className="h-7 w-7" />
          </div>
        )}

        <div className="pointer-events-none absolute bottom-full left-1/2 z-[100] mb-4 w-60 -translate-x-1/2 scale-95 opacity-0 transition-all duration-200 group-hover:scale-100 group-hover:opacity-100">
          <div className="glass-panel rounded-lg border border-white p-4 text-left shadow-2xl">
            <div className="mb-3 flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate font-headline text-sm font-extrabold text-primary">{member.title}</h3>
                <p className="text-[10px] font-extrabold uppercase tracking-wider text-on-surface-variant">{member.governance_seat || roleShort(member.role)}</p>
              </div>
              <div className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary-fixed text-primary">
                <Icon className="h-4 w-4" />
              </div>
            </div>
            <div className="mb-3 rounded-lg bg-surface-container p-3">
              <p className="mb-1 flex items-center gap-1 text-[9px] font-extrabold uppercase text-on-surface-variant">
                <Terminal className="h-3 w-3" />
                Strength
              </p>
              <p className="text-[11px] font-serif italic leading-relaxed text-on-surface">{dossier.strength}. {dossier.focus}</p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {skills.map((skill) => (
                <span key={skill} className="rounded bg-secondary-fixed px-1.5 py-0.5 text-[9px] font-extrabold text-on-secondary-fixed">
                  {humanize(skill)}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MobileMember({ member, state = {} }: { member: BoardMember; state?: SeatState }) {
  const Icon = MEMBER_ICONS[member.id] || Users;
  const imageUrl = MEMBER_IMAGES[member.id];
  return (
    <div className="rounded-lg border border-slate-100 bg-white p-3 shadow-sm">
      <div className="flex items-center gap-3">
        {imageUrl ? (
          <img src={imageUrl} alt="" aria-hidden="true" className="h-12 w-12 shrink-0 rounded-full border-2 border-white object-cover shadow-md ring-4 ring-primary-fixed" />
        ) : (
          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-primary/5 text-primary">
            <Icon className="h-5 w-5" />
          </span>
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-extrabold text-slate-900">{member.title}</p>
          <p className="truncate text-xs font-semibold uppercase text-primary">{state.label || 'available'}</p>
        </div>
      </div>
    </div>
  );
}

function CeoComposer({
  query,
  setQuery,
  fullBoard,
  setFullBoard,
  verify,
  setVerify,
  manualCount,
  running,
  onSubmit,
}: {
  query: string;
  setQuery: (value: string) => void;
  fullBoard: boolean;
  setFullBoard: (value: boolean) => void;
  verify: boolean;
  setVerify: (value: boolean) => void;
  manualCount: number;
  running: boolean;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="mx-auto mt-5 w-full max-w-3xl rounded-lg border border-[#e2e8f0] bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-3">
        <div className="grid h-11 w-11 place-items-center rounded-lg bg-[#0f172a] text-white">
          <Bolt className="h-5 w-5" />
        </div>
        <div>
          <p className="font-extrabold text-[#0f172a]">CEO Command</p>
          <p className="text-sm font-semibold text-[#64748b]">
            {fullBoard ? 'Full board selected' : manualCount ? `${manualCount} manual member${manualCount === 1 ? '' : 's'} selected` : 'Adaptive routing selected'}
          </p>
        </div>
      </div>

      <textarea
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            event.currentTarget.form?.requestSubmit();
          }
        }}
        placeholder="What should the board decide?"
        className="min-h-28 w-full resize-y rounded-lg border border-[#cbd5e1] bg-[#f8fafc] p-3 text-[#0f172a] outline-none transition focus:border-[#003d9b] focus:ring-4 focus:ring-[#dae2ff]"
        rows={4}
      />

      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Toggle checked={fullBoard} onChange={setFullBoard} label="Full board" />
        <Toggle checked={verify} onChange={setVerify} label="Verify" />
        <button
          type="submit"
          disabled={running || !query.trim()}
          className="ml-auto inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-[#0f172a] px-5 py-2 text-sm font-extrabold text-white transition hover:bg-[#003d9b] disabled:cursor-not-allowed disabled:opacity-55"
        >
          <Send className="h-4 w-4" />
          {running ? 'Deliberating' : 'Ask the Board'}
        </button>
      </div>
    </form>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <label className="inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-lg border border-[#cbd5e1] bg-[#f8fafc] px-3 text-sm font-bold text-[#475569]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4 accent-[#003d9b]"
      />
      {label}
    </label>
  );
}

function StatusCard({ status }: { status: TableStatus }) {
  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-white p-4 shadow-sm">
      <p className="text-xs font-extrabold uppercase text-[#003d9b]">{status.label}</p>
      <h3 className="mt-1 text-lg font-extrabold leading-tight text-[#0f172a]">{status.title}</h3>
      <p className="mt-2 text-sm leading-relaxed text-[#64748b]">{status.detail}</p>
    </article>
  );
}

function StageDigest({ stages }: { stages: StageEvent[] }) {
  const latest = stages.slice(-3).reverse();
  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-white p-4 shadow-sm">
      <p className="text-xs font-extrabold uppercase text-[#003d9b]">Conversation Updates</p>
      <div className="mt-3 grid gap-2">
        {latest.length ? latest.map((stage) => (
          <div key={stage.stage} className="grid min-h-10 grid-cols-[auto_1fr_auto] items-center gap-2 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2 text-sm">
            <StageIndicator active={stage.active} done={stage.done} />
            <span className="truncate font-bold text-[#475569]">Stage {stage.stage}</span>
            <strong className="text-xs uppercase text-[#0f172a]">{stage.count || stage.members.length || 0}</strong>
          </div>
        )) : (
          <p className="text-sm leading-relaxed text-[#64748b]">No live updates yet.</p>
        )}
      </div>
    </article>
  );
}

function SelectedDigest({
  members,
  states,
  activeCouncilMembers,
  fullBoard,
}: {
  members: BoardMember[];
  states: Record<string, SeatState>;
  activeCouncilMembers: BoardMember[];
  fullBoard: boolean;
}) {
  const selectedMembers = activeCouncilMembers.length
    ? activeCouncilMembers
    : fullBoard
      ? members
      : members.filter((member) => states[member.id]?.selected || ['active', 'done', 'failed'].includes(states[member.id]?.status || 'idle'));

  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4">
      <p className="text-xs font-extrabold uppercase text-[#003d9b]">At The Table</p>
      <div className="mt-3 grid gap-2">
        {selectedMembers.length ? selectedMembers.slice(0, 7).map((member) => (
          <div key={member.id} className="grid min-h-10 grid-cols-[auto_1fr_auto] items-center gap-2 rounded-lg border border-[#e2e8f0] bg-white px-3 py-2 text-sm">
            <span className="h-2.5 w-2.5 rounded-lg" style={{ backgroundColor: memberTone(member.id) }} />
            <span className="truncate font-bold text-[#475569]">{member.title}</span>
            <strong className="text-xs uppercase text-[#64748b]">{states[member.id]?.label || 'selected'}</strong>
          </div>
        )) : (
          <p className="text-sm leading-relaxed text-[#64748b]">Adaptive routing will select the council.</p>
        )}
      </div>
    </article>
  );
}

function DecisionPreview({ session, error }: { session: BoardSession | null; error: string }) {
  const decision = session?.decision || {};
  const summary = decision.executive_summary || getSynthesis(session)?.content || '';

  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4">
      <p className="text-xs font-extrabold uppercase text-[#003d9b]">Latest Decision</p>
      {error ? (
        <p className="mt-2 text-sm font-semibold text-[#b42318]">{error}</p>
      ) : summary ? (
        <p className="mt-2 line-clamp-6 text-sm leading-relaxed text-[#64748b]">{stripMarkdown(summary)}</p>
      ) : (
        <p className="mt-2 text-sm leading-relaxed text-[#64748b]">The chair memo will appear after synthesis.</p>
      )}
    </article>
  );
}

function RunSettings({ fullBoard, manualCount, verify }: { fullBoard: boolean; manualCount: number; verify: boolean }) {
  const rows = [
    ['Routing', fullBoard ? 'Full board' : manualCount ? 'Manual council' : 'Adaptive'],
    ['Manual seats', String(manualCount)],
    ['Verification', verify ? 'On' : 'Off'],
  ];
  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4">
      <p className="text-xs font-extrabold uppercase text-[#003d9b]">Run Settings</p>
      <dl className="mt-3 grid gap-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-3 border-b border-[#e2e8f0] pb-2 last:border-b-0 last:pb-0">
            <dt className="text-sm font-semibold text-[#64748b]">{label}</dt>
            <dd className="text-right text-sm font-extrabold text-[#0f172a]">{value}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

function StageTimeline({ stages }: { stages: StageEvent[] }) {
  return (
    <div className="mt-5 grid gap-3">
      {stages.map((stage) => (
        <article key={stage.stage} className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <StageIndicator active={stage.active} done={stage.done} />
              <h3 className="font-extrabold text-[#0f172a]">Stage {stage.stage}: {STAGE_NAMES[stage.stage] || 'Processing'}</h3>
            </div>
            <span className="rounded-lg bg-white px-2 py-1 text-xs font-bold uppercase text-[#64748b]">
              {stage.done ? 'Complete' : stage.active ? 'Active' : 'Queued'}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(stage.members || []).map((member, index) => (
              <div
                key={`${stage.stage}-${member.id || member.title}-${index}`}
                className={`inline-flex min-h-9 items-center gap-2 rounded-lg border bg-white px-3 text-sm font-semibold ${
                  member.failed ? 'border-[#f0c8c2] text-[#b42318]' : 'border-[#e2e8f0] text-[#475569]'
                }`}
              >
                <span>{member.failed ? 'Failed' : 'Done'}</span>
                <span>{member.title || member.id}</span>
                {member.model && <span className="text-xs text-[#003d9b]">{member.model}</span>}
                {member.elapsed !== undefined && <span className="text-xs text-[#64748b]">{Number(member.elapsed).toFixed(1)}s</span>}
              </div>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

function DecisionRecord({ session }: { session: BoardSession | null }) {
  const decision = session?.decision || {};
  const verification = session?.verification || {};
  const memory = session?.memory || {};
  const classification = session?.classification || {};
  const delegationPlan = session?.delegation_plan || null;
  const participation = session?.participation || [];
  const hasStructuredDecision = Boolean(
    decision.executive_summary ||
    decision.strategic_direction ||
    decision.architecture_design ||
    decision.security_posture ||
    decision.next_steps?.length,
  );

  if (!session) {
    return <p className="mt-4 text-sm text-[#64748b]">No decision returned.</p>;
  }

  if (!hasStructuredDecision) {
    const synthesis = getSynthesis(session);
    return (
      <>
        <div
          className="prose-lite mt-5 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(synthesis?.content || 'No decision returned.') }}
        />
        <FeedbackWidget sessionId={session.session_id} />
      </>
    );
  }

  return (
    <div className="mt-5 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
      <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4">
        <DecisionBlock title="Executive Summary" content={decision.executive_summary} />
        <DecisionBlock title="Strategic Direction" content={decision.strategic_direction} />
        <DecisionBlock title="Architecture & Design" content={decision.architecture_design} />
        <DecisionBlock title="Security Posture" content={decision.security_posture} />
      </article>

      <aside className="grid gap-4">
        <DecisionList title="Next Steps" items={decision.next_steps || decision.implementation_plan} />
        <DecisionList title="Top Risks" items={decision.risk_register} />
        <DecisionList title="Dissent" items={decision.dissenting_views} />
      </aside>

      {delegationPlan?.tasks?.length ? (
        <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4 lg:col-span-2">
          <h3 className="text-lg font-extrabold text-[#0f172a]">Delegation Plan</h3>
          <div className="mt-3 grid gap-3">
            {delegationPlan.tasks.map((task) => (
              <div key={task.id} className="rounded-lg border border-[#e2e8f0] bg-white p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong className="text-sm text-[#0f172a]">{task.title}</strong>
                  <span className={`rounded-lg px-2 py-1 text-[10px] font-extrabold uppercase ${taskStatusClass(task.status)}`}>{task.status}</span>
                </div>
                <p className="mt-2 text-sm leading-relaxed text-[#64748b]">{task.objective}</p>
                <p className="mt-2 text-xs font-bold uppercase text-[#003d9b]">
                  {humanize(task.manager_agent_id)} to {humanize(task.execution_unit_id)}
                </p>
              </div>
            ))}
          </div>
        </article>
      ) : null}

      <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4 lg:col-span-2">
        <h3 className="text-lg font-extrabold text-[#0f172a]">Verification</h3>
        <p className="mt-2 text-sm leading-relaxed text-[#64748b]">
          {verification.score !== undefined
            ? `Score ${verification.score}/10, ${verification.passed ? 'passed' : 'needs review'}`
            : 'Verification not run.'}
        </p>
        <PlainList items={verification.deficiencies} />
      </article>

      <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4 lg:col-span-2">
        <h3 className="text-lg font-extrabold text-[#0f172a]">Routing</h3>
        <p className="mt-2 text-sm leading-relaxed text-[#64748b]">
          {classification.query_type ? `${humanize(classification.query_type)} - ${classification.complexity || 'unscored'}` : 'Routing details unavailable.'}
        </p>
        <PlainList items={classification.relevant_member_ids} />
        {classification.role_gap_memo && <p className="mt-3 text-sm leading-relaxed text-[#64748b]">{classification.role_gap_memo}</p>}
        {participation.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {participation.slice(0, 9).map((item) => (
              <span key={item.member_id} className="rounded-lg border border-[#e2e8f0] bg-white px-2 py-1 text-xs font-bold text-[#475569]">
                {humanize(item.member_id)}: {item.mode}
              </span>
            ))}
          </div>
        ) : null}
      </article>

      <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4 lg:col-span-2">
        <h3 className="text-lg font-extrabold text-[#0f172a]">SOTB Proposal</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-[#64748b]">
          {memory.proposed_sotb_update || 'No memory update proposed.'}
        </p>
        {memory.requires_approval && <p className="mt-3 text-sm font-bold text-[#003d9b]">Human approval required before durable memory changes.</p>}
      </article>

      <div className="lg:col-span-2">
        <FeedbackWidget sessionId={session.session_id} />
      </div>
    </div>
  );
}

function DecisionBlock({ title, content }: { title: string; content?: string }) {
  if (!content) return null;
  return (
    <section className="mb-4 last:mb-0">
      <h3 className="text-lg font-extrabold text-[#0f172a]">{title}</h3>
      <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-[#64748b]">{content}</p>
    </section>
  );
}

function DecisionList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-4">
      <h3 className="text-lg font-extrabold text-[#0f172a]">{title}</h3>
      <PlainList items={items} />
    </article>
  );
}

