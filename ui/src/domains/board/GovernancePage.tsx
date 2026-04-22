import type { CSSProperties, FormEvent, RefObject } from 'react';
import {
  Activity,
  AudioLines,
  Check,
  FileText,
  MoreHorizontal,
  Send,
  Sparkles,
  Users,
  X,
} from 'lucide-react';
import tableTextureUrl from '../../../assets/council-table-texture.png';
import { AgentExecutionPanel } from '../execution';
import { FeedbackWidget, SotbCard } from '../memory';
import {
  ErrorMessage,
  Fact,
  PlainList,
  StageIndicator,
} from '../../shared/components';
import {
  MEMBER_ICONS,
  MEMBER_IMAGES,
  MEMBER_ORDER,
  STAGE_NAMES,
  getSynthesis,
  humanize,
  memberTone,
  renderMarkdown,
  stageShortLabel,
  stripMarkdown,
  taskStatusClass,
} from '../../shared/presentation';
import type {
  BoardMember,
  BoardSession,
  DelegatedTask,
  ExecutionAgent,
  LiveFeedItem,
  SeatState,
  StageEvent,
  TableStatus,
} from '../../shared/types';

const STAGE_PIPS: Array<{ stage: number; label: string }> = [
  { stage: 1, label: 'Independent' },
  { stage: 2, label: 'Peer review' },
  { stage: 3, label: 'Synthesis' },
  { stage: 4, label: 'Verify' },
];

type StagePhase = 'pending' | 'active' | 'complete' | 'verified' | 'failed';

function computeStagePhase(
  stage: number,
  stageEvents: StageEvent[],
  session: BoardSession | null,
  verifyEnabled: boolean,
): StagePhase {
  if (stage === 4) {
    if (!verifyEnabled) return 'pending';
    const verification = session?.verification;
    if (verification?.passed) return 'verified';
    if (verification?.passed === false) return 'failed';
    if (session) return 'complete';
    return 'pending';
  }
  const event = stageEvents.find((item) => item.stage === stage);
  if (!event) return 'pending';
  if (event.done) return 'complete';
  if (event.active) return 'active';
  return 'pending';
}

export function GovernancePage({
  members,
  activeCouncilMembers,
  manualMemberIds,
  toggleManualMember,
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
  liveFeed = [],
  activePhase = null,
}: {
  members: BoardMember[];
  activeCouncilMembers: BoardMember[];
  manualMemberIds: string[];
  toggleManualMember?: (id: string) => void;
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
  liveFeed?: LiveFeedItem[];
  activePhase?: string | null;
}) {
  const displayCouncil = activeCouncilMembers.length ? activeCouncilMembers : members;
  const stagePhases = STAGE_PIPS.map((pip) => computeStagePhase(pip.stage, stageEvents, session, verify));
  const hasActiveSession = Boolean(session || stageEvents.length || activePhase);
  const verified = Boolean(session?.verification?.passed);

  return (
    <div className="min-h-[calc(100vh-5rem)] bg-background text-on-surface">
      <div className="flex flex-col gap-0 lg:flex-row">
        <aside className="flex w-full flex-col gap-8 bg-surface-container-low/50 p-8 lg:w-80">
          <LeftInsights
            tableStatus={tableStatus}
            activePhase={activePhase}
            stageEvents={stageEvents}
            liveFeed={liveFeed}
            sotb={sotb}
          />
        </aside>

        <section className="relative flex flex-1 flex-col items-center justify-start gap-6 p-6 md:p-8">
          <CenterArena
            members={members}
            displayCouncil={displayCouncil}
            seatStates={seatStates}
            session={session}
            query={query}
            stagePhases={stagePhases}
            verified={verified}
            running={running}
          />

          <CeoComposer
            query={query}
            setQuery={setQuery}
            fullBoard={fullBoard}
            setFullBoard={setFullBoard}
            verify={verify}
            setVerify={setVerify}
            running={running}
            onSubmit={onSubmit}
            stagePhases={stagePhases}
            routingLabel={routingLabel}
          />

          <MemberRosterPicker
            members={members}
            manualMemberIds={manualMemberIds}
            fullBoard={fullBoard}
            toggleManualMember={toggleManualMember}
          />

          <StageResponseDeck stageEvents={stageEvents} />

          <div ref={resultRef} className="w-full max-w-3xl">
            {(stageEvents.length > 0 || session || error) && (
              <div className="grid gap-5">
                {stageEvents.length > 0 && (
                  <section className="rounded-xl bg-surface-container-low p-6">
                    <div className="mb-4 flex items-center gap-2">
                      <Activity className="h-4 w-4 text-primary" />
                      <p className="text-xs font-medium tracking-wider text-on-surface-variant">Timeline</p>
                    </div>
                    <h2 className="font-headline text-xl text-on-surface">Deliberation</h2>
                    <StageTimeline stages={stageEvents} />
                  </section>
                )}

                {(session || error) && (
                  <section className="rounded-xl bg-surface-container-low p-6">
                    <div className="mb-4 flex items-center gap-2">
                      <FileText className="h-4 w-4 text-primary" />
                      <p className="text-xs font-medium tracking-wider text-on-surface-variant">Board Decision</p>
                    </div>
                    <h2 className="font-headline text-xl text-on-surface">Decision Record</h2>
                    {error ? <ErrorMessage message={error} /> : <DecisionRecord session={session} />}
                  </section>
                )}
              </div>
            )}
          </div>
        </section>

        <aside className="flex w-full flex-col gap-8 bg-surface-container-low p-8 lg:w-96">
          <RightOutlook
            members={members}
            seatStates={seatStates}
            activeCouncilMembers={activeCouncilMembers}
            fullBoard={fullBoard}
            session={session}
            error={error}
            verify={verify}
            routingLabel={routingLabel}
            manualCount={manualMemberIds.length}
            executionAgents={executionAgents}
            onApproveTask={onApproveTask}
            onPlanTask={onPlanTask}
            hasActiveSession={hasActiveSession}
          />
        </aside>
      </div>
    </div>
  );
}

function LeftInsights({
  tableStatus,
  activePhase,
  stageEvents,
  liveFeed,
  sotb,
}: {
  tableStatus: TableStatus;
  activePhase: string | null;
  stageEvents: StageEvent[];
  liveFeed: LiveFeedItem[];
  sotb: { content?: string; path?: string };
}) {
  return (
    <>
      <div>
        <p className="text-xs font-medium tracking-wider text-primary">Briefing Room</p>
        <h2 className="mt-2 font-headline text-2xl leading-tight text-on-surface">Strategic Materials</h2>
      </div>

      <StatusCard status={tableStatus} activePhase={activePhase} />
      <StageDigest stages={stageEvents} />
      <LiveConversation feed={liveFeed} activePhase={activePhase} tableStatus={tableStatus} />

      <div>
        <h3 className="mb-3 font-headline text-lg text-on-surface">Board Memory</h3>
        <div className="rounded-lg bg-surface-container-lowest p-4">
          <SotbCard sotb={sotb} />
        </div>
      </div>
    </>
  );
}

function RightOutlook({
  members,
  seatStates,
  activeCouncilMembers,
  fullBoard,
  session,
  error,
  verify,
  routingLabel,
  manualCount,
  executionAgents,
  onApproveTask,
  onPlanTask,
  hasActiveSession,
}: {
  members: BoardMember[];
  seatStates: Record<string, SeatState>;
  activeCouncilMembers: BoardMember[];
  fullBoard: boolean;
  session: BoardSession | null;
  error: string;
  verify: boolean;
  routingLabel: string;
  manualCount: number;
  executionAgents: ExecutionAgent[];
  onApproveTask: (taskId: string) => void;
  onPlanTask: (task: DelegatedTask) => void;
  hasActiveSession: boolean;
}) {
  return (
    <>
      <div>
        <h2 className="font-headline text-2xl tracking-tight text-on-surface">Strategic Outlook</h2>
      </div>

      <SelectedDigest
        members={members}
        states={seatStates}
        activeCouncilMembers={activeCouncilMembers}
        fullBoard={fullBoard}
      />

      <DecisionPreview session={session} error={error} verify={verify} routingLabel={routingLabel} />

      <div>
        <h3 className="mb-3 font-headline text-lg text-on-surface">Execution Roadmap</h3>
        <AgentExecutionPanel
          delegationPlan={session?.delegation_plan || null}
          executionAgents={executionAgents}
          routingLabel={routingLabel}
          onApproveTask={onApproveTask}
          onPlanTask={onPlanTask}
        />
      </div>

      <RunSettings
        fullBoard={fullBoard}
        manualCount={manualCount}
        verify={verify}
        hasActiveSession={hasActiveSession}
      />
    </>
  );
}

function CenterArena({
  members,
  displayCouncil,
  seatStates,
  session,
  query,
  stagePhases,
  verified,
  running,
}: {
  members: BoardMember[];
  displayCouncil: BoardMember[];
  seatStates: Record<string, SeatState>;
  session: BoardSession | null;
  query: string;
  stagePhases: StagePhase[];
  verified: boolean;
  running: boolean;
}) {
  const activeQuery = session?.user_query || query || '';
  const hasQuery = Boolean(activeQuery.trim());

  return (
    <div className="flex w-full max-w-3xl flex-col items-center justify-center p-0">
      <RoundTable
        members={members}
        displayCouncil={displayCouncil}
        seatStates={seatStates}
        session={session}
        activeQuery={activeQuery}
        hasQuery={hasQuery}
        stagePhases={stagePhases}
        verified={verified}
        running={running}
      />
    </div>
  );
}

function RoundTable({
  members,
  displayCouncil,
  seatStates,
  session,
  activeQuery,
  hasQuery,
  stagePhases,
  verified,
  running,
}: {
  members: BoardMember[];
  displayCouncil: BoardMember[];
  seatStates: Record<string, SeatState>;
  session: BoardSession | null;
  activeQuery: string;
  hasQuery: boolean;
  stagePhases: StagePhase[];
  verified: boolean;
  running: boolean;
}) {
  const displayIds = new Set(displayCouncil.map((member) => member.id));
  const orderedMembers = MEMBER_ORDER
    .map((id) => members.find((member) => member.id === id))
    .filter((member): member is BoardMember => Boolean(member));
  // User IS the Chairperson/CEO. No avatar represents them at the table —
  // the board is convened around the user, who sits outside the visible orbit.
  const orbitMembers = orderedMembers.filter((member) => member.id !== 'chairperson');
  const radius = 180;

  return (
    <div className="board-orbit relative mx-auto hidden w-full max-w-[520px] aspect-square items-center justify-center md:flex">
      <div
        className="relative h-full w-full overflow-hidden rounded-[100%]"
        style={{
          background:
            'radial-gradient(ellipse at center, #F4EFE6 0%, #E8DFCC 60%, #DDD2BA 100%)',
          boxShadow: '0 20px 60px -20px rgba(184, 134, 11, 0.25)',
        }}
      >
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-[0.12]"
          style={{
            backgroundImage: `url(${tableTextureUrl})`,
            backgroundSize: 'cover',
            mixBlendMode: 'multiply',
          }}
        />
        <div
          className="pointer-events-none absolute left-1/2 top-1/2 h-3/4 w-3/4 -translate-x-1/2 -translate-y-1/2 rounded-full blur-[100px]"
          style={{ background: 'rgba(184, 134, 11, 0.05)' }}
          aria-hidden="true"
        />

        <TopicCard
          session={session}
          activeQuery={activeQuery}
          hasQuery={hasQuery}
          stagePhases={stagePhases}
          verified={verified}
          running={running}
        />

        <div className="absolute inset-0">
          {orbitMembers.map((member, index) => {
            const angle = (index / Math.max(orbitMembers.length, 1)) * 360 - 90;
            const state = seatStates[member.id] || {};
            const isMuted = displayCouncil.length > 0 && !displayIds.has(member.id) && !state.selected && state.status !== 'done';
            return (
              <BoardAvatar
                key={member.id}
                member={member}
                state={state}
                muted={isMuted}
                style={{
                  left: `calc(50% + ${Math.cos((angle * Math.PI) / 180) * radius}px)`,
                  top: `calc(50% + ${Math.sin((angle * Math.PI) / 180) * radius}px)`,
                } as CSSProperties}
              />
            );
          })}
        </div>
      </div>

      <MobileRoster members={orbitMembers} seatStates={seatStates} />
    </div>
  );
}

function MobileRoster({
  members,
  seatStates,
}: {
  members: BoardMember[];
  seatStates: Record<string, SeatState>;
}) {
  return (
    <div className="mt-4 grid w-full grid-cols-2 gap-2 md:hidden">
      {members.map((member) => (
        <MobileMember key={member.id} member={member} state={seatStates[member.id]} />
      ))}
    </div>
  );
}

function TopicCard({
  session,
  activeQuery,
  hasQuery,
  stagePhases,
  verified,
  running,
}: {
  session: BoardSession | null;
  activeQuery: string;
  hasQuery: boolean;
  stagePhases: StagePhase[];
  verified: boolean;
  running: boolean;
}) {
  const haloClass = verified
    ? 'shadow-[0_0_40px_-10px_rgba(184,134,11,0.35)]'
    : 'shadow-[0_0_40px_-10px_rgba(184,134,11,0.20)]';

  return (
    <div
      className={`glass-panel absolute left-1/2 top-1/2 z-10 -translate-x-1/2 -translate-y-1/2 w-72 h-36 rounded-xl ${haloClass}`}
    >
      <div className="flex h-full w-full flex-col items-center justify-center gap-3 px-6 py-4">
        {hasQuery ? (
          <>
            <blockquote className="line-clamp-2 text-center font-headline text-sm italic leading-snug text-on-surface">
              &ldquo;{activeQuery}&rdquo;
            </blockquote>
            <div className="flex items-center gap-2">
              {stagePhases.map((phase, idx) => (
                <span
                  key={`stage-pip-${idx}`}
                  className={`h-1.5 w-1.5 rounded-full ${
                    phase === 'verified'
                      ? 'bg-primary'
                      : phase === 'complete'
                      ? 'bg-secondary-container'
                      : phase === 'active'
                      ? 'bg-secondary-container animate-pulse'
                      : phase === 'failed'
                      ? 'bg-error'
                      : 'bg-surface-container-highest'
                  }`}
                  aria-hidden="true"
                />
              ))}
            </div>
            {session?.classification?.query_type && (
              <p className="text-[10px] tracking-wider text-on-surface-variant/70">
                {humanize(session.classification.query_type)}
              </p>
            )}
          </>
        ) : (
          <>
            <AudioLines className={`h-7 w-7 text-primary ${running ? 'animate-pulse' : ''}`} aria-hidden="true" />
            <p className="font-body text-sm text-on-surface">Awaiting board question</p>
            <p className="text-[10px] tracking-wider text-on-surface-variant/70">CEO composer ready</p>
          </>
        )}
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
  const imageUrl = MEMBER_IMAGES[member.id];
  const tone = memberTone(member.id);
  const isSpeaking = status === 'active';
  const isDone = status === 'done';
  const isFailed = status === 'failed';
  const isSelected = status === 'selected';

  let ringClass = '';
  if (isSpeaking) {
    ringClass = 'ring-2 ring-primary ring-offset-4 ring-offset-background';
  } else if (isSelected) {
    ringClass = 'ring-2 ring-primary-fixed-dim ring-offset-2 ring-offset-background';
  } else if (isDone) {
    ringClass = 'ring-2 ring-offset-2 ring-offset-background';
  } else if (isFailed) {
    ringClass = 'ring-2 ring-error ring-offset-2 ring-offset-background';
  }

  const opacityClass = muted
    ? 'opacity-40'
    : isSpeaking
    ? 'opacity-100'
    : isDone
    ? 'opacity-85'
    : isSelected
    ? 'opacity-90'
    : 'opacity-70';

  const doneRingStyle: CSSProperties = isDone ? { '--tw-ring-color': tone } as CSSProperties : {};

  return (
    <div
      className={`member-orbit-seat group absolute z-20 h-16 w-16 -translate-x-1/2 -translate-y-1/2 transition-opacity ${opacityClass}`}
      style={style}
    >
      {isSpeaking && (
        <span className="speaking-halo pointer-events-none absolute inset-[-10px] rounded-full" aria-hidden="true" />
      )}
      <div className="avatar-pop relative h-16 w-16 cursor-pointer">
        {imageUrl ? (
          <img
            src={imageUrl}
            alt=""
            aria-hidden="true"
            className={`h-16 w-16 rounded-full bg-surface-container-highest p-1 object-cover ${ringClass}`}
            style={doneRingStyle}
          />
        ) : (
          <div
            className={`grid h-16 w-16 place-items-center rounded-full bg-surface-container-highest p-1 text-primary ${ringClass}`}
            style={doneRingStyle}
          >
            <Icon className="h-6 w-6" />
          </div>
        )}

        {isSpeaking && (
          <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-primary">
            <span className="h-2 w-2 rounded-full bg-background" aria-hidden="true" />
          </span>
        )}

        {isDone && (
          <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-surface-container-highest">
            <Check className="h-2.5 w-2.5 text-primary" aria-hidden="true" />
          </span>
        )}

        {isFailed && (
          <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-error-container">
            <X className="h-2.5 w-2.5 text-error" aria-hidden="true" />
          </span>
        )}
      </div>
      <div className="pointer-events-none absolute left-1/2 top-full mt-2 -translate-x-1/2 text-center whitespace-nowrap">
        <p className="text-xs font-body text-on-surface-variant">{roleLabelFor(member)}</p>
      </div>
    </div>
  );
}

function roleLabelFor(member: BoardMember) {
  const label = member.governance_seat || member.title || member.id;
  return humanize(String(label).split('/')[0].trim());
}

function MobileMember({ member, state = {} }: { member: BoardMember; state?: SeatState }) {
  const Icon = MEMBER_ICONS[member.id] || Users;
  const imageUrl = MEMBER_IMAGES[member.id];
  const status = state.status || 'idle';
  const toneBarColor = memberTone(member.id);
  const isActive = status === 'active' || status === 'done' || state.selected;

  return (
    <div
      className={`relative rounded-xl bg-surface-container-lowest p-3 ${isActive ? 'accent-bar-left' : ''}`}
    >
      <div className="flex items-center gap-3">
        {imageUrl ? (
          <img src={imageUrl} alt="" aria-hidden="true" className="h-12 w-12 shrink-0 rounded-full bg-surface-container-highest p-1 object-cover" />
        ) : (
          <span className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-surface-container-highest text-primary">
            <Icon className="h-5 w-5" />
          </span>
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-on-surface">{member.title}</p>
          <p className="truncate text-xs font-medium text-on-surface-variant">{state.label || 'available'}</p>
        </div>
      </div>
      {isActive && (
        <span
          className="absolute bottom-0 left-0 right-0 h-0.5 rounded-b-xl"
          style={{ backgroundColor: toneBarColor }}
          aria-hidden="true"
        />
      )}
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
  running,
  onSubmit,
  stagePhases,
  routingLabel,
}: {
  query: string;
  setQuery: (value: string) => void;
  fullBoard: boolean;
  setFullBoard: (value: boolean) => void;
  verify: boolean;
  setVerify: (value: boolean) => void;
  running: boolean;
  onSubmit: (event: FormEvent) => void;
  stagePhases: StagePhase[];
  routingLabel: string;
}) {
  const isDisabled = running || !query.trim();
  return (
    <form
      onSubmit={onSubmit}
      className="mt-12 flex w-full max-w-2xl flex-col gap-4 rounded-xl bg-surface-container-lowest p-6"
    >
      <StagePipRow stagePhases={stagePhases} />

      <div className="relative">
        <textarea
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="What should the board decide? (Enter to send, Shift+Enter for a new line)"
          className="min-h-14 max-h-40 w-full resize-none rounded-lg bg-surface-container-highest py-4 pl-4 pr-14 font-body text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-0 focus:border-b-2 focus:border-b-secondary-container"
          rows={2}
        />
        <button
          type="submit"
          disabled={isDisabled}
          className={`absolute right-2 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-full text-on-primary transition ${
            isDisabled ? 'bg-surface-container-high opacity-40 cursor-not-allowed' : 'metallic-gradient'
          }`}
          aria-label="Send question"
        >
          <Send className="h-4 w-4" />
        </button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Toggle checked={fullBoard} onChange={setFullBoard} label="Full board" />
          <Toggle checked={verify} onChange={setVerify} label="Verify" />
        </div>
        <div className="flex items-center gap-2 font-body text-xs text-on-surface-variant">
          {running ? (
            <>
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" aria-hidden="true" />
              <span>Deliberating…</span>
            </>
          ) : (
            <>
              <Sparkles className="h-3 w-3 text-primary" aria-hidden="true" />
              <span>{routingLabel} &middot; ~$0.02 est</span>
            </>
          )}
        </div>
      </div>
    </form>
  );
}

function StagePipRow({ stagePhases }: { stagePhases: StagePhase[] }) {
  return (
    <div className="grid grid-cols-4 items-start gap-2">
      {STAGE_PIPS.map((pip, index) => {
        const phase = stagePhases[index];
        const dotClass =
          phase === 'verified'
            ? 'bg-primary'
            : phase === 'complete' || phase === 'active'
            ? 'bg-secondary-container'
            : phase === 'failed'
            ? 'bg-error'
            : 'bg-surface-container-highest';
        return (
          <div key={pip.stage} className="flex flex-col items-center gap-1.5">
            <span
              className={`h-2 w-2 rounded-full ${dotClass} ${phase === 'active' ? 'animate-pulse' : ''}`}
              aria-hidden="true"
            />
            <span className="text-[10px] font-body text-on-surface-variant/70">{pip.label}</span>
          </div>
        );
      })}
    </div>
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
    <button
      type="button"
      onClick={() => onChange(!checked)}
      aria-pressed={checked}
      className="inline-flex items-center gap-2 font-body text-xs text-on-surface"
    >
      <span
        className={`relative inline-flex h-5 w-10 items-center rounded-full transition-colors ${
          checked ? 'bg-secondary-container/20' : 'bg-surface-container-high'
        }`}
      >
        <span
          className={`absolute top-1 h-3 w-3 rounded-full transition-all ${
            checked ? 'left-6 bg-secondary-container' : 'left-1 bg-on-surface-variant'
          }`}
          aria-hidden="true"
        />
      </span>
      <span className="text-on-surface-variant">{label}</span>
    </button>
  );
}

function MemberRosterPicker({
  members,
  manualMemberIds,
  fullBoard,
  toggleManualMember,
}: {
  members: BoardMember[];
  manualMemberIds: string[];
  fullBoard: boolean;
  toggleManualMember?: (id: string) => void;
}) {
  if (!toggleManualMember) return null;
  const manualSet = new Set(manualMemberIds);
  const orderedMembers = MEMBER_ORDER
    .map((id) => members.find((member) => member.id === id))
    .filter((member): member is BoardMember => Boolean(member));

  return (
    <div className="flex w-full max-w-3xl flex-col gap-3">
      <p className="text-xs font-body tracking-wider text-on-surface-variant">
        {fullBoard ? 'Full board selected' : manualMemberIds.length ? `${manualMemberIds.length} manual seat${manualMemberIds.length === 1 ? '' : 's'}` : 'Adaptive routing will select the council'}
      </p>
      <div className="flex flex-wrap gap-2">
        {orderedMembers.map((member) => {
          const imageUrl = MEMBER_IMAGES[member.id];
          const Icon = MEMBER_ICONS[member.id] || Users;
          const isSelected = manualSet.has(member.id);
          const tone = memberTone(member.id);
          return (
            <button
              key={member.id}
              type="button"
              onClick={() => toggleManualMember(member.id)}
              className={`relative flex items-center gap-2 rounded-lg px-3 py-2 font-body text-xs transition-all ${
                isSelected
                  ? 'accent-bar-left bg-surface-container-high text-on-surface'
                  : 'bg-surface-container-lowest text-on-surface-variant opacity-50 hover:opacity-100'
              }`}
              aria-pressed={isSelected}
            >
              {imageUrl ? (
                <img src={imageUrl} alt="" aria-hidden="true" className="h-8 w-8 rounded-full bg-surface-container-highest object-cover" />
              ) : (
                <span className="grid h-8 w-8 place-items-center rounded-full bg-surface-container-highest text-primary">
                  <Icon className="h-4 w-4" />
                </span>
              )}
              <span className="font-medium">{member.title}</span>
              {isSelected && (
                <span
                  className="absolute bottom-0 left-0 right-0 h-0.5 rounded-b-lg"
                  style={{ backgroundColor: tone }}
                  aria-hidden="true"
                />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StageResponseDeck({ stageEvents }: { stageEvents: StageEvent[] }) {
  const stageOne = stageEvents.find((event) => event.stage === 1);
  if (!stageOne?.members?.length) return null;

  return (
    <div className="w-full max-w-3xl rounded-xl bg-surface-container-low p-6">
      <div className="mb-4 flex items-center gap-2">
        <Activity className="h-4 w-4 text-primary" />
        <h3 className="font-headline text-xl text-on-surface">Stage 1 Responses</h3>
      </div>
      <div className="grid gap-3">
        {stageOne.members.map((member, index) => (
          <div
            key={`stage1-${member.id || member.title || index}`}
            className={`rounded-lg bg-surface-container-lowest p-4 ${member.failed ? 'accent-bar-left' : ''}`}
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate font-body text-sm font-semibold text-on-surface">
                  {member.title || humanize(member.id)}
                </p>
                {member.model && (
                  <p className="truncate text-[10px] font-body tracking-wider text-on-surface-variant/70">
                    {member.model}
                  </p>
                )}
              </div>
              <span
                className={`text-[10px] font-body tracking-wider ${
                  member.failed ? 'text-error' : 'text-on-surface-variant'
                }`}
              >
                {member.failed ? 'Failed' : `${member.elapsed ? member.elapsed.toFixed(1) : '0.0'}s`}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StatusCard({ status, activePhase }: { status: TableStatus; activePhase?: string | null }) {
  const isWorking = Boolean(activePhase) || (status.label !== 'Ready' && status.label !== 'Complete' && status.label !== 'Error');
  return (
    <article className="rounded-lg bg-surface-container-lowest p-4">
      <div className="flex items-center gap-2">
        <span
          className={`h-2 w-2 rounded-full ${isWorking ? 'bg-primary animate-pulse' : 'bg-surface-container-highest'}`}
          aria-hidden="true"
        />
        <p className="text-xs font-body tracking-wider text-on-surface-variant">{status.label}</p>
      </div>
      <h3 className="mt-2 font-headline text-base leading-tight text-on-surface">{status.title}</h3>
      <p className="mt-2 text-sm font-body leading-relaxed text-on-surface-variant">{status.detail}</p>
    </article>
  );
}

function StageDigest({ stages }: { stages: StageEvent[] }) {
  const rows = [1, 2, 3].map((stage) => {
    const event = stages.find((item) => item.stage === stage) || { stage, active: false, done: false, members: [], count: 0 };
    return event;
  });
  return (
    <article className="rounded-lg bg-surface-container-lowest p-4">
      <p className="text-xs font-body tracking-wider text-on-surface-variant">Stage Digest</p>
      <div className="mt-3 grid gap-2">
        {rows.map((stage) => (
          <div key={stage.stage} className="grid grid-cols-[auto_1fr_auto] items-center gap-3">
            <StageIndicator active={stage.active} done={stage.done} />
            <div className="min-w-0">
              <p className="truncate font-body text-sm text-on-surface">{stageShortLabel(stage.stage)}</p>
              <p className="truncate text-xs font-body text-on-surface-variant">
                {stage.count || stage.members?.length || 0} of {stage.members?.length ? stage.count || stage.members.length : '—'} members
              </p>
            </div>
            <span className="text-[10px] font-body tracking-wider text-on-surface-variant">
              {stage.done ? 'Done' : stage.active ? 'Active' : 'Idle'}
            </span>
          </div>
        ))}
      </div>
    </article>
  );
}

function LiveConversation({
  feed,
  activePhase,
  tableStatus,
}: {
  feed: LiveFeedItem[];
  activePhase?: string | null;
  tableStatus: TableStatus;
}) {
  const running = Boolean(activePhase) || (tableStatus.label !== 'Ready' && tableStatus.label !== 'Complete' && tableStatus.label !== 'Error');
  return (
    <article className="rounded-lg bg-surface-container-lowest p-4">
      <div className="flex items-center gap-2">
        <p className="text-xs font-body tracking-wider text-on-surface-variant">Live Conversation</p>
        {running && (
          <span className="ml-auto inline-flex items-center gap-1 text-[10px] font-body tracking-wider text-primary">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" aria-hidden="true" />
            live
          </span>
        )}
      </div>
      <ul className="mt-3 grid max-h-72 gap-2 overflow-y-auto pr-1 no-scrollbar">
        {feed.length ? (
          feed.slice(0, 8).map((item) => {
            const toneClass =
              item.kind === 'speaking'
                ? 'bg-primary/5'
                : item.kind === 'failed'
                ? 'bg-error-container/20 text-error'
                : item.kind === 'done'
                ? 'bg-surface-container-lowest'
                : item.kind === 'stage'
                ? 'bg-secondary-container/10 text-secondary'
                : 'bg-surface-container-high';
            return (
              <li key={item.id} className={`rounded-lg px-3 py-2 text-xs font-body ${toneClass}`}>
                <p className="truncate text-on-surface">{item.text}</p>
                {item.stage ? (
                  <p className="mt-0.5 text-[10px] tracking-wider text-on-surface-variant">Stage {item.stage}</p>
                ) : null}
              </li>
            );
          })
        ) : (
          <li className="rounded-lg bg-surface-container-low px-3 py-3 text-xs font-body text-on-surface-variant">
            Waiting for the board to convene.
          </li>
        )}
      </ul>
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
    <article>
      <h3 className="mb-3 font-headline text-lg text-on-surface">At the Table</h3>
      <div className="grid gap-2">
        {selectedMembers.length ? (
          selectedMembers.slice(0, 7).map((member) => {
            const state = states[member.id] || {};
            const status = state.status || 'idle';
            const tone = memberTone(member.id);
            const isActive = status === 'active' || status === 'done';
            const imageUrl = MEMBER_IMAGES[member.id];
            return (
              <div
                key={member.id}
                className={`relative flex items-center gap-3 rounded-lg px-3 py-2 ${isActive ? 'bg-surface-container-high accent-bar-left' : 'bg-surface-container-lowest'}`}
              >
                {imageUrl ? (
                  <img src={imageUrl} alt="" aria-hidden="true" className="h-8 w-8 shrink-0 rounded-full bg-surface-container-highest object-cover" />
                ) : (
                  <span className="h-8 w-8 shrink-0 rounded-full bg-surface-container-highest" aria-hidden="true" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate font-body text-sm font-semibold text-on-surface">{member.title}</p>
                  <p className="truncate text-xs font-body text-on-surface-variant">{state.label || 'selected'}</p>
                </div>
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: tone }}
                  aria-hidden="true"
                />
              </div>
            );
          })
        ) : (
          <p className="rounded-lg bg-surface-container-lowest p-3 text-sm font-body italic text-on-surface-variant">
            Adaptive routing will select the council.
          </p>
        )}
      </div>
    </article>
  );
}

function DecisionPreview({
  session,
  error,
  verify,
  routingLabel,
}: {
  session: BoardSession | null;
  error: string;
  verify: boolean;
  routingLabel: string;
}) {
  const decision = session?.decision || {};
  const summary = decision.executive_summary || getSynthesis(session)?.content || '';
  const verified = Boolean(session?.verification?.passed);
  const cost = session?.metrics?.total_cost_estimate_usd;

  return (
    <article className="rounded-lg bg-surface-container-lowest p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-body tracking-wider text-primary">LATEST DECISION</p>
        <MoreHorizontal className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />
      </div>
      {error ? (
        <p className="mt-3 text-sm font-body text-error">{error}</p>
      ) : summary ? (
        <>
          <p className="mt-3 line-clamp-5 text-sm font-body leading-relaxed text-on-surface">
            {stripMarkdown(summary)}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {verify && (
              <span
                className={`rounded-lg px-2 py-1 text-[10px] font-body ${
                  verified ? 'bg-primary/10 text-primary' : 'bg-surface-container-high text-on-surface-variant'
                }`}
              >
                {verified ? 'Verified' : 'Verify pending'}
              </span>
            )}
            <span className="rounded-lg bg-surface-container-high px-2 py-1 text-[10px] font-body text-on-surface-variant">
              Routing: {routingLabel}
            </span>
            {cost !== undefined && (
              <span className="rounded-lg bg-surface-container-high px-2 py-1 text-[10px] font-body text-on-surface-variant">
                Budget: ~${Number(cost).toFixed(2)}
              </span>
            )}
          </div>
        </>
      ) : (
        <p className="mt-3 text-sm font-body italic text-on-surface-variant">
          Chair memo will appear after deliberation
        </p>
      )}
    </article>
  );
}

function RunSettings({
  fullBoard,
  manualCount,
  verify,
  hasActiveSession,
}: {
  fullBoard: boolean;
  manualCount: number;
  verify: boolean;
  hasActiveSession: boolean;
}) {
  const routing = fullBoard ? 'Full board' : manualCount ? 'Manual council' : 'Adaptive';
  const rows: Array<[string, string]> = [
    ['Routing', routing],
    ['Manual seats', String(manualCount)],
    ['Verification', verify ? 'On' : 'Off'],
    ['Session', hasActiveSession ? 'In progress' : 'Standby'],
  ];
  return (
    <article className="rounded-lg bg-surface-container-lowest p-4">
      <h3 className="font-headline text-lg text-on-surface">Run Settings</h3>
      <dl className="mt-3 grid gap-0">
        {rows.map(([label, value]) => (
          <Fact key={label} label={label} value={value} />
        ))}
      </dl>
    </article>
  );
}

function StageTimeline({ stages }: { stages: StageEvent[] }) {
  return (
    <div className="mt-5 grid gap-3">
      {stages.map((stage) => (
        <article key={stage.stage} className="rounded-lg bg-surface-container-lowest p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <StageIndicator active={stage.active} done={stage.done} />
              <h3 className="font-headline text-base text-on-surface">
                Stage {stage.stage}: {STAGE_NAMES[stage.stage] || 'Processing'}
              </h3>
            </div>
            <span className="rounded-lg bg-surface-container-high px-2 py-1 text-[10px] font-body tracking-wider text-on-surface-variant">
              {stage.done ? 'Complete' : stage.active ? 'Active' : 'Queued'}
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {(stage.members || []).map((member, index) => (
              <div
                key={`${stage.stage}-${member.id || member.title}-${index}`}
                className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-body ${
                  member.failed
                    ? 'bg-error-container/20 text-error'
                    : 'bg-surface-container-high text-on-surface'
                }`}
              >
                <span>{member.failed ? 'Failed' : 'Done'}</span>
                <span>{member.title || member.id}</span>
                {member.model && <span className="text-on-surface-variant">{member.model}</span>}
                {member.elapsed !== undefined && (
                  <span className="text-on-surface-variant">{Number(member.elapsed).toFixed(1)}s</span>
                )}
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
    return <p className="mt-4 text-sm font-body text-on-surface-variant">No decision returned.</p>;
  }

  if (!hasStructuredDecision) {
    const synthesis = getSynthesis(session);
    return (
      <>
        <div
          className="prose-lite mt-5 rounded-lg bg-surface-container-lowest p-4"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(synthesis?.content || 'No decision returned.') }}
        />
        <FeedbackWidget sessionId={session.session_id} />
      </>
    );
  }

  return (
    <div className="mt-5 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
      <article className="rounded-lg bg-surface-container-lowest p-4 lg:col-span-2">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-body tracking-wider text-primary">Board Resolution</p>
            <h3 className="mt-1 font-headline text-2xl text-on-surface">{session.user_query || 'Board decision'}</h3>
          </div>
          <span className="rounded-lg bg-surface-container-high px-3 py-1 text-[10px] font-body tracking-wider text-on-surface-variant">
            {decision.status || session.status || 'completed'}
          </span>
        </div>
        <dl className="mt-4 grid gap-3 md:grid-cols-2">
          <FormalRow label="Prepared by" value={decision.prepared_by || 'Chairperson'} />
          <FormalRow label="Decision authority" value={decision.decision_authority || 'Chairperson'} />
          <FormalRow label="Session" value={decision.session_id || session.session_id || 'unrecorded'} />
          <FormalRow label="Decision date" value={decision.decision_date || 'Not recorded'} />
        </dl>
        {decision.participants?.length ? (
          <div className="mt-4">
            <p className="text-xs font-body tracking-wider text-primary">Contributors</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {decision.participants.map((participant) => (
                <span key={participant} className="rounded-lg bg-surface-container-high px-2 py-1 text-xs font-body text-on-surface">
                  {participant}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </article>

      {session.clarification?.status === 'required' ? (
        <article className="rounded-lg bg-error-container/15 p-4 lg:col-span-2">
          <h3 className="font-headline text-lg text-on-surface">Clarification Required</h3>
          <PlainList items={(session.clarification.questions || []).map((item) => String(item.question || 'Clarification needed.'))} />
        </article>
      ) : null}

      <article className="rounded-lg bg-surface-container-lowest p-4">
        <DecisionBlock title="Executive Summary" content={decision.executive_summary} />
        <DecisionBlock title="Strategic Direction" content={decision.strategic_direction} />
        <DecisionBlock title="Architecture & Design" content={decision.architecture_design} />
        <DecisionBlock title="Security Posture" content={decision.security_posture} />
      </article>

      <aside className="grid gap-4">
        <DecisionList title="Next Steps" items={decision.next_steps || decision.implementation_plan} />
        <DecisionList title="Top Risks" items={decision.risk_register} />
        <DecisionList title="Dissent" items={decision.dissenting_views} />
        <DecisionList title="Assumptions" items={decision.assumptions} />
        <DecisionList title="Accountable Owners" items={decision.accountable_owners} />
      </aside>

      {delegationPlan?.tasks?.length ? (
        <article className="rounded-lg bg-surface-container-lowest p-4 lg:col-span-2">
          <h3 className="font-headline text-lg text-on-surface">Delegation Plan</h3>
          <div className="mt-3 grid gap-3">
            {delegationPlan.tasks.map((task) => (
              <div key={task.id} className="rounded-lg bg-surface-container-high p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <strong className="font-body text-sm text-on-surface">{task.title}</strong>
                  <span className={`rounded-lg px-2 py-1 text-[10px] font-body tracking-wider ${taskStatusClass(task.status)}`}>
                    {task.status}
                  </span>
                </div>
                <p className="mt-2 text-sm font-body leading-relaxed text-on-surface-variant">{task.objective}</p>
                <p className="mt-2 text-xs font-body tracking-wider text-primary">
                  {humanize(task.manager_agent_id)} to {humanize(task.execution_unit_id)}
                </p>
              </div>
            ))}
          </div>
        </article>
      ) : null}

      {delegationPlan?.warnings?.length || session.structured_output_warnings?.length ? (
        <article className="rounded-lg bg-error-container/15 p-4 lg:col-span-2">
          <h3 className="font-headline text-lg text-on-surface">Delegation Status</h3>
          <PlainList items={[...(delegationPlan?.warnings || []), ...(session.structured_output_warnings || [])]} />
        </article>
      ) : null}

      <article className="rounded-lg bg-surface-container-lowest p-4 lg:col-span-2">
        <h3 className="font-headline text-lg text-on-surface">Verification</h3>
        <p className="mt-2 text-sm font-body leading-relaxed text-on-surface-variant">
          {verification.score !== undefined
            ? `Score ${verification.score}/10, ${verification.passed ? 'passed' : 'needs review'}`
            : 'Verification not run.'}
        </p>
        <PlainList items={verification.deficiencies} />
      </article>

      <article className="rounded-lg bg-surface-container-lowest p-4 lg:col-span-2">
        <h3 className="font-headline text-lg text-on-surface">Routing</h3>
        <p className="mt-2 text-sm font-body leading-relaxed text-on-surface-variant">
          {classification.query_type ? `${humanize(classification.query_type)} - ${classification.complexity || 'unscored'}` : 'Routing details unavailable.'}
        </p>
        <PlainList items={classification.relevant_member_ids} />
        {classification.role_gap_memo && (
          <p className="mt-3 text-sm font-body leading-relaxed text-on-surface-variant">{classification.role_gap_memo}</p>
        )}
        {participation.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {participation.slice(0, 9).map((item) => (
              <span key={item.member_id} className="rounded-lg bg-surface-container-high px-2 py-1 text-xs font-body text-on-surface">
                {humanize(item.member_id)}: {item.mode}
              </span>
            ))}
          </div>
        ) : null}
      </article>

      <article className="rounded-lg bg-surface-container-lowest p-4 lg:col-span-2">
        <h3 className="font-headline text-lg text-on-surface">SOTB Proposal</h3>
        <p className="mt-2 whitespace-pre-wrap text-sm font-body leading-relaxed text-on-surface-variant">
          {memory.proposed_sotb_update || 'No memory update proposed.'}
        </p>
        {memory.requires_approval && (
          <p className="mt-3 text-sm font-body text-primary">Human approval required before durable memory changes.</p>
        )}
      </article>

      <div className="lg:col-span-2">
        <FeedbackWidget sessionId={session.session_id} />
      </div>
    </div>
  );
}

function FormalRow({ label, value }: { label: string; value?: string }) {
  return (
    <div className="rounded-lg bg-surface-container-high px-3 py-2">
      <dt className="text-[10px] font-body tracking-wider text-on-surface-variant">{label}</dt>
      <dd className="mt-1 text-sm font-body text-on-surface">{value || 'Not recorded'}</dd>
    </div>
  );
}

function DecisionBlock({ title, content }: { title: string; content?: string }) {
  if (!content) return null;
  return (
    <section className="mb-4 last:mb-0">
      <h3 className="font-headline text-lg text-on-surface">{title}</h3>
      <p className="mt-2 whitespace-pre-wrap text-sm font-body leading-relaxed text-on-surface-variant">{content}</p>
    </section>
  );
}

function DecisionList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <article className="rounded-lg bg-surface-container-lowest p-4">
      <h3 className="font-headline text-lg text-on-surface">{title}</h3>
      <PlainList items={items} />
    </article>
  );
}
