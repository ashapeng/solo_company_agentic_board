import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, FormEvent, ReactNode, RefObject } from 'react';
import {
  Activity,
  AudioLines,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  FileText,
  MoreHorizontal,
  Pin,
  PinOff,
  Plus,
  Send,
  Sparkles,
  Users,
  X,
} from 'lucide-react';
import { AnimatePresence, motion } from 'motion/react';
import { AgentExecutionPanel } from '../execution';
import { FeedbackWidget, SotbCard, SotbMemoryPanel } from '../memory';
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
  ConversationMessage,
  DelegatedTask,
  ExecutionAgent,
  LiveFeedItem,
  SeatState,
  StageEvent,
  StageMember,
  TableStatus,
} from '../../shared/types';
import { recordRoutingSignal } from '../../shared/api';

const STAGE_PIPS: Array<{ stage: number; label: string }> = [
  { stage: 1, label: 'Independent' },
  { stage: 2, label: 'Peer review' },
  { stage: 3, label: 'Synthesis' },
  { stage: 4, label: 'Verify' },
];

type StagePhase = 'pending' | 'active' | 'complete' | 'verified' | 'failed' | 'skipped';

/**
 * Choose up to `max` visible seats. Chairperson is always included.
 * Remaining slots filled by stable MEMBER_ORDER (used as an implicit
 * priority — BoardMember has no numeric `priority` field), with any
 * `promotedIds` forcibly bubbled above other non-chair candidates.
 */
function selectVisibleSeats(
  candidates: BoardMember[],
  promotedIds: Set<string>,
  max: number = 5,
): { visible: BoardMember[]; overflow: BoardMember[] } {
  if (candidates.length <= max) return { visible: candidates, overflow: [] };

  const chair = candidates.find((m) => m.id === 'chairperson');
  const others = candidates.filter((m) => m.id !== 'chairperson');

  // Stable-sort: promoted first (keep their relative MEMBER_ORDER rank),
  // then others by their MEMBER_ORDER position (unknown ids fall to the end).
  const orderIndex = (id: string) => {
    const i = MEMBER_ORDER.indexOf(id);
    return i === -1 ? Number.MAX_SAFE_INTEGER : i;
  };
  const sorted = [...others].sort((a, b) => {
    const aPromoted = promotedIds.has(a.id) ? 1 : 0;
    const bPromoted = promotedIds.has(b.id) ? 1 : 0;
    if (aPromoted !== bPromoted) return bPromoted - aPromoted;
    return orderIndex(a.id) - orderIndex(b.id);
  });

  const slots = max - (chair ? 1 : 0);
  const visibleOthers = sorted.slice(0, slots);
  const overflowOthers = sorted.slice(slots);
  const visible = chair ? [chair, ...visibleOthers] : visibleOthers;
  return { visible, overflow: overflowOthers };
}

function computeStagePhase(
  stage: number,
  stageEvents: StageEvent[],
  session: BoardSession | null,
  verifyEnabled: boolean,
): StagePhase {
  if (stage === 4) {
    if (!verifyEnabled) return 'skipped';
    const verification = session?.verification;
    if (verification?.passed) return 'verified';
    if (verification?.passed === false) return 'failed';
    if (session) return 'complete';
    return 'pending';
  }
  if (session) {
    if (stage === 1 && session.stage1?.length) return 'complete';
    if (stage === 2 && session.stage2) return 'complete';
    if (stage === 3 && getSynthesis(session)?.content) return 'complete';
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
  conversationMessages = [],
  activeStreamMessageId = null,
  awaitingFollowup = false,
  capReached = false,
  initiativeCockpit,
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
  conversationMessages?: ConversationMessage[];
  activeStreamMessageId?: string | null;
  awaitingFollowup?: boolean;
  capReached?: boolean;
  initiativeCockpit?: ReactNode;
}) {
  const displayCouncil = activeCouncilMembers.length ? activeCouncilMembers : members;
  const stagePhases = STAGE_PIPS.map((pip) => (
    pip.stage === 4 && activePhase === 'verifying'
      ? 'active'
      : computeStagePhase(pip.stage, stageEvents, session, verify)
  ));
  const hasActiveSession = Boolean(session || stageEvents.length || activePhase);
  const hasLeftDrawerActivity = stageEvents.length > 0 || Boolean(activePhase);
  const verified = Boolean(session?.verification?.passed);
  const [rosterOpen, setRosterOpen] = useState(false);
  const [promotedIds, setPromotedIds] = useState<Set<string>>(new Set());

  const promoteSeat = (memberId: string) => {
    setPromotedIds((current) => {
      const next = new Set(current);
      next.add(memberId);
      return next;
    });
  };

  // Track recently-added manual members for a transient "+" badge
  const [justAddedIds, setJustAddedIds] = useState<Set<string>>(new Set());
  const prevManualRef = useRef<string[]>(manualMemberIds);

  useEffect(() => {
    const prev = prevManualRef.current;
    const added = manualMemberIds.filter((id) => !prev.includes(id));
    if (added.length > 0) {
      setJustAddedIds((current) => {
        const next = new Set(current);
        added.forEach((id) => next.add(id));
        return next;
      });
      const timeouts = added.map((id) =>
        setTimeout(() => {
          setJustAddedIds((current) => {
            const next = new Set(current);
            next.delete(id);
            return next;
          });
        }, 2000),
      );
      prevManualRef.current = manualMemberIds;
      return () => {
        timeouts.forEach(clearTimeout);
      };
    }
    prevManualRef.current = manualMemberIds;
  }, [manualMemberIds]);

  // BriefingDrawer (left) open/pin state
  const [leftOpen, setLeftOpen] = useState(false);
  const [leftPinned, setLeftPinned] = useState(() => {
    try { return localStorage.getItem('boardroom.pinLeft') === '1'; } catch { return false; }
  });

  useEffect(() => {
    try { localStorage.setItem('boardroom.pinLeft', leftPinned ? '1' : '0'); } catch { /* ignore */ }
  }, [leftPinned]);

  const stage3DrawerPhase = computeStagePhase(3, stageEvents, session, verify);
  const rightDrawerHasPriority = stage3DrawerPhase === 'active' || stage3DrawerPhase === 'complete' || Boolean(session?.decision);

  // Auto-open on the EDGE: when activity first appears, not while it persists.
  // State-based predicate fights the mutual-exclusion effect below and causes
  // the left drawer to flash open/close once Stage 3 becomes active.
  const prevHadActivityRef = useRef(false);
  useEffect(() => {
    const hasActivity = hasLeftDrawerActivity;
    if (hasActivity && !prevHadActivityRef.current && !rightDrawerHasPriority) {
      setLeftOpen(true);
    }
    prevHadActivityRef.current = hasActivity;
  }, [hasLeftDrawerActivity, rightDrawerHasPriority]);

  // OutlookDrawer (right) open/pin state
  const [rightOpen, setRightOpen] = useState(false);
  const [rightPinned, setRightPinned] = useState(() => {
    try { return localStorage.getItem('boardroom.pinRight') === '1'; } catch { return false; }
  });

  useEffect(() => {
    try { localStorage.setItem('boardroom.pinRight', rightPinned ? '1' : '0'); } catch { /* ignore */ }
  }, [rightPinned]);

  // Auto-open on the EDGE: when Stage 3 first becomes active or a decision
  // first arrives — not while either condition persists. Mirrors the left
  // drawer fix above so a user-dismissed drawer stays dismissed.
  const prevRightTriggerRef = useRef(false);
  useEffect(() => {
    if (rightDrawerHasPriority && !prevRightTriggerRef.current) {
      setRightOpen(true);
    }
    prevRightTriggerRef.current = rightDrawerHasPriority;
  }, [rightDrawerHasPriority]);

  // Unread indicators — set when the auto-open trigger fires for a drawer
  // that is currently closed (user or mutual-exclusion kept it shut).
  const [leftUnread, setLeftUnread] = useState(false);
  const [rightUnread, setRightUnread] = useState(false);
  const prevStageEventCountRef = useRef(0);

  useEffect(() => {
    if (leftOpen) {
      setLeftUnread(false);
      prevStageEventCountRef.current = stageEvents.length;
      return;
    }
    if (stageEvents.length > prevStageEventCountRef.current) {
      setLeftUnread(true);
    }
    prevStageEventCountRef.current = stageEvents.length;
  }, [stageEvents.length, leftOpen]);

  useEffect(() => {
    if (rightDrawerHasPriority && !rightOpen) {
      setRightUnread(true);
    }
    if (rightOpen) setRightUnread(false);
  }, [rightDrawerHasPriority, rightOpen]);

  const openLeftDrawer = () => {
    setLeftOpen(true);
  };

  const openRightDrawer = () => {
    setRightOpen(true);
  };

  // Esc dismisses drawer (respect pin — do nothing if pinned).
  // Right drawer takes precedence since it holds higher value content.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (rightOpen && !rightPinned) { setRightOpen(false); return; }
      if (leftOpen && !leftPinned) setLeftOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [leftOpen, leftPinned, rightOpen, rightPinned]);

  const workspaceInsetClass = [
    leftOpen ? 'md:pl-[320px]' : hasLeftDrawerActivity ? 'md:pl-12' : '',
    rightOpen ? 'md:pr-[384px]' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className="h-[calc(100vh-3rem)] overflow-hidden bg-background text-on-surface">
      <div className={`flex h-full flex-col gap-0 transition-[padding] duration-200 ${workspaceInsetClass}`}>
        <section className="relative grid h-full min-h-0 w-full grid-cols-1 gap-4 overflow-hidden p-4 md:p-6 xl:grid-cols-[minmax(360px,520px)_minmax(420px,1fr)]">
          <div className="flex min-h-0 flex-col items-center justify-start gap-4 overflow-y-auto overflow-x-hidden">
            <CenterArena
              members={members}
              displayCouncil={displayCouncil}
              manualMemberIds={manualMemberIds}
              seatStates={seatStates}
              session={session}
              query={query}
              stagePhases={stagePhases}
              verified={verified}
              running={running}
              justAddedIds={justAddedIds}
              promotedIds={promotedIds}
              promoteSeat={promoteSeat}
            />

            {initiativeCockpit}

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
              session={session}
              verified={verified}
              awaitingFollowup={awaitingFollowup}
              capReached={capReached}
            />

            <div className="flex shrink-0 flex-col items-center gap-3">
              {!rosterOpen && (
                <button
                  type="button"
                  onClick={() => setRosterOpen(true)}
                  className="flex items-center gap-1.5 font-body text-sm text-on-surface-variant hover:text-primary-container transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  Add members
                </button>
              )}
              {rosterOpen && (
                <>
                  <MemberRosterPicker
                    members={members}
                    manualMemberIds={manualMemberIds}
                    fullBoard={fullBoard}
                    toggleManualMember={toggleManualMember}
                  />
                  <button
                    type="button"
                    onClick={() => setRosterOpen(false)}
                    className="text-xs font-body text-on-surface-variant/70 hover:text-on-surface-variant"
                  >
                    Hide roster
                  </button>
                </>
              )}
            </div>
          </div>

          <div ref={resultRef} className="min-h-0">
            <LiveBoardTranscript
              messages={conversationMessages}
              members={members}
              activeStreamMessageId={activeStreamMessageId}
              running={running}
              error={error}
              session={session}
              stageEvents={stageEvents}
            />
          </div>
        </section>

      </div>

      <BriefingDrawer
        open={leftOpen}
        pinned={leftPinned}
        onClose={() => setLeftOpen(false)}
        onTogglePin={() => setLeftPinned((v) => !v)}
      >
        <LeftInsights
          tableStatus={tableStatus}
          activePhase={activePhase}
          stageEvents={stageEvents}
          liveFeed={liveFeed}
          sotb={sotb}
        />
      </BriefingDrawer>

      {!leftOpen && hasLeftDrawerActivity && (
        <CollapsedBriefingRail
          unread={leftUnread}
          onOpen={openLeftDrawer}
        />
      )}

      <OutlookDrawer
        open={rightOpen}
        pinned={rightPinned}
        onClose={() => setRightOpen(false)}
        onTogglePin={() => setRightPinned((v) => !v)}
      >
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
      </OutlookDrawer>

      {!rightOpen && (stageEvents.length > 0 || activePhase) && (
        <CollapsedOutlookRail
          unread={rightUnread}
          onOpen={openRightDrawer}
        />
      )}
    </div>
  );
}

function BriefingDrawer({
  open,
  pinned,
  onClose,
  onTogglePin,
  children,
}: {
  open: boolean;
  pinned: boolean;
  onClose: () => void;
  onTogglePin: () => void;
  children: ReactNode;
}) {
  return (
    <motion.aside
      key="briefing-drawer"
      initial={false}
      animate={{ x: open ? 0 : -320, opacity: open ? 1 : 0 }}
      transition={{ ease: 'easeOut', duration: 0.2 }}
      className="fixed left-[72px] top-0 bottom-0 z-40 w-[320px] overflow-x-hidden overflow-y-auto bg-surface-container-low p-6 shadow-[8px_0_32px_-8px_rgba(26,22,20,0.10)]"
      style={{ pointerEvents: open ? 'auto' : 'none' }}
      aria-label="Briefing Room"
      aria-hidden={!open}
    >
      <header className="mb-4 flex items-start justify-between gap-2">
        <div>
          <p className="text-[10px] tracking-wider uppercase text-primary">Strategic Materials</p>
          <h2 className="font-headline text-xl text-on-surface">Briefing Room</h2>
        </div>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={onTogglePin}
            className="grid h-8 w-8 place-items-center rounded-full hover:bg-surface-container-high transition-colors"
            aria-label={pinned ? 'Unpin drawer' : 'Pin drawer'}
            title={pinned ? 'Unpin' : 'Pin open'}
          >
            {pinned ? <PinOff className="h-4 w-4 text-primary-container" aria-hidden="true" /> : <Pin className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-full hover:bg-surface-container-high transition-colors"
            aria-label="Collapse drawer"
          >
            <X className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />
          </button>
        </div>
      </header>
      {children}
    </motion.aside>
  );
}

function CollapsedBriefingRail({
  unread,
  onOpen,
}: {
  unread: boolean;
  onOpen: () => void;
}) {
  return (
    <aside
      className="fixed left-[72px] top-0 bottom-0 z-40 flex w-12 flex-col items-center border-r border-outline-variant/50 bg-surface-container-low shadow-[4px_0_16px_-10px_rgba(26,22,20,0.24)]"
      aria-label="Collapsed Briefing Room"
    >
      <button
        type="button"
        onClick={onOpen}
        className="relative mt-4 grid h-9 w-9 place-items-center rounded-full bg-surface-container-high hover:bg-surface-container-highest transition-colors"
        aria-label="Open Briefing Room"
        title="Open Briefing Room"
      >
        <ChevronRight className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />
        {unread && (
          <span
            aria-hidden="true"
            className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-primary"
          />
        )}
      </button>
      <div className="mt-5 grid h-9 w-9 place-items-center rounded-full bg-surface-container-high text-primary">
        <FileText className="h-4 w-4" aria-hidden="true" />
      </div>
      <div className="flex flex-1 items-center justify-center py-4">
        <span className="rotate-180 text-[10px] font-body font-semibold uppercase tracking-wider text-on-surface-variant [writing-mode:vertical-rl]">
          Briefing Room
        </span>
      </div>
    </aside>
  );
}

function OutlookDrawer({
  open,
  pinned,
  onClose,
  onTogglePin,
  children,
}: {
  open: boolean;
  pinned: boolean;
  onClose: () => void;
  onTogglePin: () => void;
  children: ReactNode;
}) {
  return (
    <motion.aside
      key="outlook-drawer"
      initial={false}
      animate={{ x: open ? 0 : 384, opacity: open ? 1 : 0 }}
      transition={{ ease: 'easeOut', duration: 0.2 }}
      className="fixed right-0 top-0 bottom-0 z-40 w-[384px] overflow-x-hidden overflow-y-auto bg-surface-container-low p-6 shadow-[-8px_0_32px_-8px_rgba(26,22,20,0.10)]"
      style={{ pointerEvents: open ? 'auto' : 'none' }}
      aria-label="Strategic Outlook"
      aria-hidden={!open}
    >
      <header className="mb-4 flex items-start justify-between gap-2">
        <h2 className="font-headline text-xl text-on-surface">Strategic Outlook</h2>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={onTogglePin}
            className="grid h-8 w-8 place-items-center rounded-full hover:bg-surface-container-high transition-colors"
            aria-label={pinned ? 'Unpin drawer' : 'Pin drawer'}
            title={pinned ? 'Unpin' : 'Pin open'}
          >
            {pinned ? <PinOff className="h-4 w-4 text-primary-container" aria-hidden="true" /> : <Pin className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-full hover:bg-surface-container-high transition-colors"
            aria-label="Collapse drawer"
          >
            <X className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />
          </button>
        </div>
      </header>
      {children}
    </motion.aside>
  );
}

function CollapsedOutlookRail({
  unread,
  onOpen,
}: {
  unread: boolean;
  onOpen: () => void;
}) {
  return (
    <aside
      className="fixed right-0 top-0 bottom-0 z-40 flex w-12 flex-col items-center border-l border-outline-variant/50 bg-surface-container-low shadow-[-4px_0_16px_-10px_rgba(26,22,20,0.24)]"
      aria-label="Collapsed Strategic Outlook"
    >
      <button
        type="button"
        onClick={onOpen}
        className="relative mt-4 grid h-9 w-9 place-items-center rounded-full bg-surface-container-high hover:bg-surface-container-highest transition-colors"
        aria-label="Open Strategic Outlook"
        title="Open Strategic Outlook"
      >
        <ChevronLeft className="h-4 w-4 text-on-surface-variant" aria-hidden="true" />
        {unread && (
          <span
            aria-hidden="true"
            className="absolute left-1.5 top-1.5 h-2 w-2 rounded-full bg-primary"
          />
        )}
      </button>
      <div className="mt-5 grid h-9 w-9 place-items-center rounded-full bg-surface-container-high text-primary">
        <FileText className="h-4 w-4" aria-hidden="true" />
      </div>
      <div className="flex flex-1 items-center justify-center py-4">
        <span className="rotate-180 text-[10px] font-body font-semibold uppercase tracking-wider text-on-surface-variant [writing-mode:vertical-rl]">
          Outlook
        </span>
      </div>
    </aside>
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
  const [auditOpen, setAuditOpen] = useState(false);

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
        <button
          type="button"
          onClick={() => setAuditOpen((v) => !v)}
          aria-expanded={auditOpen}
          className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-lg bg-surface-container-high px-3 py-2 text-xs font-body font-semibold text-on-surface-variant transition-colors hover:bg-surface-container-highest hover:text-on-surface"
        >
          {auditOpen ? (
            <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {auditOpen ? 'Hide memory audit' : 'Open memory audit'}
        </button>
        {auditOpen && (
          <div className="mt-2">
            <SotbMemoryPanel ventureId="default" />
          </div>
        )}
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

      <DecisionPreview session={session} error={error} verify={verify} routingLabel={routingLabel} />

      {session?.decision && (
        <MissingVoiceRow
          sessionId={session.session_id ?? null}
          routedIds={new Set(session.classification?.relevant_member_ids ?? [])}
          allMembers={members}
        />
      )}

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
  manualMemberIds,
  seatStates,
  session,
  query,
  stagePhases,
  verified,
  running,
  justAddedIds,
  promotedIds,
  promoteSeat,
}: {
  members: BoardMember[];
  displayCouncil: BoardMember[];
  manualMemberIds: string[];
  seatStates: Record<string, SeatState>;
  session: BoardSession | null;
  query: string;
  stagePhases: StagePhase[];
  verified: boolean;
  running: boolean;
  justAddedIds: Set<string>;
  promotedIds: Set<string>;
  promoteSeat: (memberId: string) => void;
}) {
  const activeQuery = session?.user_query || query || '';
  const hasQuery = Boolean(activeQuery.trim());

  return (
    <div className="flex w-full max-w-3xl flex-col items-center justify-center p-0">
      <RoundTable
        members={members}
        displayCouncil={displayCouncil}
        manualMemberIds={manualMemberIds}
        seatStates={seatStates}
        session={session}
        activeQuery={activeQuery}
        hasQuery={hasQuery}
        stagePhases={stagePhases}
        verified={verified}
        running={running}
        justAddedIds={justAddedIds}
        promotedIds={promotedIds}
        promoteSeat={promoteSeat}
      />
    </div>
  );
}

function RoundTable({
  members,
  displayCouncil,
  manualMemberIds,
  seatStates,
  session,
  activeQuery,
  hasQuery,
  stagePhases,
  verified,
  running,
  justAddedIds,
  promotedIds,
  promoteSeat,
}: {
  members: BoardMember[];
  displayCouncil: BoardMember[];
  manualMemberIds: string[];
  seatStates: Record<string, SeatState>;
  session: BoardSession | null;
  activeQuery: string;
  hasQuery: boolean;
  stagePhases: StagePhase[];
  verified: boolean;
  running: boolean;
  justAddedIds: Set<string>;
  promotedIds: Set<string>;
  promoteSeat: (memberId: string) => void;
}) {
  const displayIds = new Set(displayCouncil.map((member) => member.id));
  const manualSet = new Set(manualMemberIds);
  const orderedMembers = MEMBER_ORDER
    .map((id) => members.find((member) => member.id === id))
    .filter((member): member is BoardMember => Boolean(member));
  const radius = 180;

  // Chairperson (the user / CEO) is always present at the table.
  // Other members appear when the CEO adds them manually, when the classifier
  // routes them, or when their seat is otherwise active.
  const sessionLive =
    session !== null ||
    hasQuery ||
    stagePhases.some((phase) => phase !== 'pending') ||
    Object.values(seatStates).some((state) => state?.status && state.status !== 'idle');

  const visibleOrbitMembers = orderedMembers.filter((member) => {
    if (member.id === 'chairperson') return true;
    if (manualSet.has(member.id)) return true;
    const status = seatStates[member.id]?.status;
    if (status && status !== 'idle') return true;
    if (sessionLive && displayIds.has(member.id)) return true;
    return false;
  });

  const { visible, overflow } = selectVisibleSeats(visibleOrbitMembers, promotedIds, 5);
  const pillAngle =
    overflow.length > 0 ? (visible.length / (visible.length + 1)) * 360 - 90 : null;
  const slotCount = visible.length + (pillAngle !== null ? 1 : 0);

  return (
    <div className="board-orbit relative mx-auto hidden w-full max-w-[440px] shrink-0 max-h-[45%] aspect-square items-center justify-center md:flex">
      <div className="absolute inset-0">
        <AnimatePresence>
          {visible.map((member, index) => {
            const angle = (index / Math.max(slotCount, 1)) * 360 - 90;
            const state = seatStates[member.id] || {};
            const isMuted = displayCouncil.length > 0 && !displayIds.has(member.id) && !state.selected && state.status !== 'done';
            const left = `calc(50% + ${Math.cos((angle * Math.PI) / 180) * radius}px)`;
            const top = `calc(50% + ${Math.sin((angle * Math.PI) / 180) * radius}px)`;
            return (
              <motion.div
                key={member.id}
                initial={{ opacity: 0, scale: 0.6 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.6 }}
                transition={{
                  duration: 0.24,
                  ease: 'easeOut',
                  delay: index * 0.12,
                }}
                layout
                className="absolute"
                style={{ left, top, transform: 'translate(-50%, -50%)' }}
              >
                <BoardAvatar
                  member={member}
                  state={state}
                  muted={isMuted}
                  isManualAdd={justAddedIds.has(member.id)}
                />
              </motion.div>
            );
          })}
        </AnimatePresence>

        {pillAngle !== null && (
          <div
            className="absolute"
            style={{
              left: `calc(50% + ${Math.cos((pillAngle * Math.PI) / 180) * radius}px)`,
              top: `calc(50% + ${Math.sin((pillAngle * Math.PI) / 180) * radius}px)`,
              transform: 'translate(-50%, -50%)',
            }}
          >
            <OverflowSeat overflow={overflow} onPromote={promoteSeat} />
          </div>
        )}
      </div>

      <MobileRoster members={visibleOrbitMembers} seatStates={seatStates} />
    </div>
  );
}

function OverflowSeat({
  overflow,
  onPromote,
}: {
  overflow: BoardMember[];
  onPromote: (memberId: string) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-12 w-12 items-center justify-center rounded-full bg-surface-container-high text-sm font-headline text-on-surface hover:bg-surface-container-highest transition-colors"
        aria-label={`${overflow.length} more member${overflow.length === 1 ? '' : 's'}`}
        title={`${overflow.length} more`}
      >
        +{overflow.length}
      </button>
      {open && (
        <div
          role="dialog"
          className="absolute top-full mt-2 left-1/2 -translate-x-1/2 z-30 w-56 rounded-lg bg-surface-container-lowest p-2 shadow-[0_8px_32px_rgba(26,22,20,0.15)]"
          onMouseLeave={() => setOpen(false)}
        >
          <ul className="flex flex-col gap-1">
            {overflow.map((member) => {
              const imageUrl = MEMBER_IMAGES[member.id];
              return (
                <li key={member.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onPromote(member.id);
                      setOpen(false);
                    }}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-surface-container-low transition-colors"
                  >
                    {imageUrl ? (
                      <img src={imageUrl} alt="" className="h-6 w-6 shrink-0 rounded-full object-cover" />
                    ) : (
                      <span className="h-6 w-6 shrink-0 rounded-full bg-surface-container-highest" />
                    )}
                    <span className="font-body text-sm text-on-surface">{member.title}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
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

function TopicBar({
  activeQuery,
  hasQuery,
  running,
  verified,
  session,
}: {
  activeQuery: string;
  hasQuery: boolean;
  running: boolean;
  verified: boolean;
  session: BoardSession | null;
}) {
  const hasDecision = Boolean(session?.decision);
  const label = !hasQuery
    ? 'Awaiting board question'
    : hasDecision
    ? verified ? 'Decision ready · verified' : 'Decision ready'
    : running
    ? 'Deliberating…'
    : activeQuery;

  const icon = !hasQuery ? (
    <AudioLines className="h-3.5 w-3.5 text-primary-container" aria-hidden="true" />
  ) : running ? (
    <AudioLines className="h-3.5 w-3.5 text-primary-container animate-pulse" aria-hidden="true" />
  ) : hasDecision ? (
    <Check className="h-3.5 w-3.5 text-primary-container" aria-hidden="true" />
  ) : (
    <Sparkles className="h-3.5 w-3.5 text-primary-container" aria-hidden="true" />
  );

  return (
    <div className="flex items-center gap-2 px-1 text-on-surface-variant">
      {icon}
      <p className={`flex-1 truncate font-headline italic text-sm ${hasQuery && !hasDecision && !running ? 'text-on-surface' : ''}`}>
        {label}
      </p>
    </div>
  );
}

function BoardAvatar({
  member,
  state = {},
  muted,
  isManualAdd = false,
}: {
  member: BoardMember;
  state?: SeatState;
  muted?: boolean;
  isManualAdd?: boolean;
}) {
  const status = state.status || (state.selected ? 'selected' : 'idle');
  const isSpeaking = status === 'active';
  const isDone = status === 'done';
  const isFailed = status === 'failed';
  const isSelected = status === 'selected' || Boolean(state.selected);
  const isChairperson = member.id === 'chairperson';

  const tone = memberTone(member.id);
  const size = isDone || isFailed ? 48 : 64;
  const baseOpacity = muted ? 0.45 : isFailed ? 0.55 : isDone ? 0.7 : isSelected ? 0.9 : 1;

  const ringClass =
    muted
      ? ''
      : isSpeaking
      ? 'ring-2 ring-primary ring-offset-4 ring-offset-background'
      : isFailed
      ? 'ring-2 ring-error'
      : isSelected
      ? 'ring-2 ring-secondary-container ring-offset-2 ring-offset-background'
      : '';

  const doneChairRingClass = isDone && isChairperson ? 'ring-1 ring-primary/50' : '';

  const imageUrl = MEMBER_IMAGES[member.id];
  const MemberIcon = MEMBER_ICONS[member.id] || Users;

  const toneRingStyle: CSSProperties | undefined =
    isDone && !isFailed && !isSpeaking && !isSelected && !isChairperson
      ? { boxShadow: `0 0 0 2px ${tone}` }
      : undefined;

  return (
    <div className="relative flex flex-col items-center gap-1" style={{ opacity: baseOpacity }}>
      <div className="relative" style={{ width: size, height: size }}>
        {isSpeaking && !muted && <div className="speaking-halo" aria-hidden="true" />}

        {imageUrl ? (
          <img
            src={imageUrl}
            alt=""
            aria-hidden="true"
            className={`relative z-10 h-full w-full rounded-full object-cover transition-[width,height] duration-200 ${ringClass} ${doneChairRingClass}`}
            style={toneRingStyle}
          />
        ) : (
          <div
            className={`relative z-10 grid h-full w-full place-items-center rounded-full bg-surface-container-highest text-primary ${ringClass} ${doneChairRingClass}`}
            style={toneRingStyle}
          >
            <MemberIcon className="h-5 w-5" aria-hidden="true" />
          </div>
        )}

        {isSpeaking && !muted && (
          <div
            aria-hidden="true"
            className="absolute bottom-0 right-0 z-20 h-3.5 w-3.5 rounded-full bg-primary ring-2 ring-background animate-pulse"
          />
        )}

        {isDone && !isFailed && (
          <div className="absolute -bottom-0.5 -right-0.5 z-20 grid h-4 w-4 place-items-center rounded-full bg-surface-container-lowest ring-2 ring-background">
            <Check className="h-2.5 w-2.5 text-primary-container" aria-hidden="true" />
          </div>
        )}

        {isFailed && (
          <div className="absolute -bottom-0.5 -right-0.5 z-20 grid h-4 w-4 place-items-center rounded-full bg-error-container ring-2 ring-background">
            <X className="h-2.5 w-2.5 text-error" aria-hidden="true" />
          </div>
        )}

        <AnimatePresence>
          {isManualAdd && (
            <motion.div
              key="manual-badge"
              initial={{ opacity: 1, scale: 1 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 1.3 }}
              transition={{ duration: 0.5 }}
              className="absolute -top-0.5 -right-0.5 z-20 grid h-4 w-4 place-items-center rounded-full bg-secondary-container text-on-secondary font-body text-[10px] font-semibold"
              aria-hidden="true"
            >
              +
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <span className="text-[10px] font-body text-on-surface-variant">{roleLabelFor(member)}</span>
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
  session,
  verified,
  awaitingFollowup = false,
  capReached = false,
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
  session: BoardSession | null;
  verified: boolean;
  awaitingFollowup?: boolean;
  capReached?: boolean;
}) {
  const inputDisabled = capReached || running;
  const isDisabled = inputDisabled || !query.trim();
  const activeQuery = session?.user_query || query || '';
  const hasQuery = Boolean(activeQuery.trim());
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  const placeholder = awaitingFollowup
    ? 'Follow up with the board… (Enter to send, Shift+Enter for new line)'
    : capReached
      ? 'Continuation cap reached. Start a new meeting to ask more.'
      : 'What should the board decide? (Enter to send, Shift+Enter for a new line)';

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 224)}px`;
    textarea.style.overflowY = textarea.scrollHeight > 224 ? 'auto' : 'hidden';
  }, [query]);

  return (
    <form
      onSubmit={onSubmit}
      className="mt-12 flex w-full max-w-2xl flex-col gap-4 rounded-xl bg-surface-container-lowest p-6"
    >
      <TopicBar
        activeQuery={activeQuery}
        hasQuery={hasQuery}
        running={running}
        verified={verified}
        session={session}
      />

      <StageProgressRow stagePhases={stagePhases} />

      <div className="relative">
        <textarea
          ref={textareaRef}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          disabled={inputDisabled}
          placeholder={placeholder}
          className="min-h-14 max-h-56 w-full resize-none rounded-lg bg-surface-container-highest py-4 pl-4 pr-14 font-body leading-relaxed text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-0 focus:border-b-2 focus:border-b-secondary-container disabled:opacity-50 disabled:cursor-not-allowed"
          rows={1}
        />
        <button
          type="submit"
          disabled={isDisabled}
          className={`absolute bottom-2 right-2 grid h-10 w-10 place-items-center rounded-full text-on-primary transition ${
            isDisabled ? 'bg-surface-container-high opacity-40 cursor-not-allowed' : 'metallic-gradient'
          }`}
          aria-label={capReached ? 'Cap reached' : awaitingFollowup ? 'Send follow-up' : 'Send question'}
          title={capReached ? 'Cap reached' : awaitingFollowup ? 'Send follow-up' : 'Send question'}
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
          ) : capReached ? (
            <>
              <Sparkles className="h-3 w-3 text-on-surface-variant/40" aria-hidden="true" />
              <span>Cap reached</span>
            </>
          ) : awaitingFollowup ? (
            <>
              <Sparkles className="h-3 w-3 text-primary" aria-hidden="true" />
              <span>Send follow-up</span>
            </>
          ) : (
            <>
              <Sparkles className="h-3 w-3 text-primary" aria-hidden="true" />
              <span>{routingLabel}</span>
            </>
          )}
        </div>
      </div>
    </form>
  );
}

function StageProgressRow({ stagePhases }: { stagePhases: StagePhase[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {STAGE_PIPS.map((pip, index) => {
        const phase = stagePhases[index];
        const dotClass =
          phase === 'verified'
            ? 'bg-primary'
            : phase === 'complete' || phase === 'active'
            ? 'bg-secondary-container'
            : phase === 'failed'
            ? 'bg-error'
            : phase === 'skipped'
            ? 'bg-surface-container-high'
            : 'bg-surface-container-highest';
        const statusLabel =
          phase === 'verified'
            ? 'Verified'
            : phase === 'complete'
            ? 'Complete'
            : phase === 'active'
            ? 'Active'
            : phase === 'failed'
            ? 'Failed'
            : phase === 'skipped'
            ? 'Skipped'
            : 'Pending';
        return (
          <div key={pip.stage} className="rounded-lg bg-surface-container-low px-3 py-2">
            <div className="flex items-center gap-2">
              <span
                className={`h-2.5 w-2.5 rounded-full ${dotClass} ${phase === 'active' ? 'animate-pulse' : ''}`}
                aria-hidden="true"
              />
              <span className="min-w-0 truncate text-xs font-body font-semibold text-on-surface">{pip.label}</span>
            </div>
            <p className="mt-1 text-[10px] font-body tracking-wider text-on-surface-variant">{statusLabel}</p>
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

function LiveBoardTranscript({
  messages,
  members,
  activeStreamMessageId,
  running,
  error,
  session,
  stageEvents,
}: {
  messages: ConversationMessage[];
  members: BoardMember[];
  activeStreamMessageId: string | null;
  running: boolean;
  error: string;
  session: BoardSession | null;
  stageEvents: StageEvent[];
}) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const memberMap = new Map(members.map((member) => [member.id, member]));
  const hasConversation = messages.length > 0;

  // Track whether the user is "stuck to the bottom". Default true on mount.
  // If the user scrolls up, we stop auto-following. If they scroll back to the
  // bottom, we resume.
  const stuckToBottomRef = useRef(true);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const handleScroll = () => {
      const distance = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight;
      stuckToBottomRef.current = distance < 32; // within 32px of bottom counts as "at bottom"
    };
    scroller.addEventListener('scroll', handleScroll, { passive: true });
    return () => scroller.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    if (stuckToBottomRef.current) {
      scroller.scrollTop = scroller.scrollHeight;
    }
  }, [messages, activeStreamMessageId]);

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl bg-surface-container-low p-4 md:p-5">
      <header className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-outline-variant/60 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
            <p className="text-xs font-medium tracking-wider text-on-surface-variant">Live Boardroom</p>
          </div>
          <h2 className="mt-1 font-headline text-xl text-on-surface">Discussion Transcript</h2>
        </div>
        <span className="rounded-lg bg-surface-container-high px-2 py-1 text-[10px] font-body tracking-wider text-on-surface-variant">
          {running ? 'Streaming' : session ? 'Complete' : 'Standby'}
        </span>
      </header>

      <div
        ref={scrollerRef}
        className="mt-4 flex-1 overflow-y-auto pr-1 no-scrollbar"
        aria-live="polite"
      >
        {error ? (
          <ErrorMessage message={error} />
        ) : hasConversation ? (
          <ol className="flex min-h-full flex-col gap-3">
            {messages.map((message) => (
              <TranscriptMessage
                key={message.id}
                message={message}
                member={message.member_id ? memberMap.get(message.member_id) : undefined}
                active={message.id === activeStreamMessageId}
              />
            ))}
          </ol>
        ) : stageEvents.length || session ? (
          <BoardDiscussion session={session} stageEvents={stageEvents} members={members} />
        ) : (
          <div className="flex h-full min-h-[360px] items-center justify-center rounded-lg bg-surface-container-lowest p-6 text-center">
            <p className="max-w-sm text-sm font-body leading-relaxed text-on-surface-variant">
              Ask the board a question. The CEO prompt and each member response will stream here without leaving the boardroom view.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

function TranscriptMessage({
  message,
  member,
  active,
}: {
  message: ConversationMessage;
  member?: BoardMember;
  active: boolean;
}) {
  if (message.speaker === 'system') {
    return (
      <li className="flex justify-center">
        <div className="max-w-xl rounded-full bg-surface-container-high px-3 py-1.5 text-center text-[11px] font-body leading-relaxed text-on-surface-variant">
          {message.content}
        </div>
      </li>
    );
  }

  const isUser = message.speaker === 'user';
  const isSecretary = message.role === 'Secretary';
  const memberId = message.member_id || member?.id || 'chairperson';
  const imageUrl = MEMBER_IMAGES[memberId];
  const Icon = isSecretary ? FileText : (MEMBER_ICONS[memberId] || Users);
  const tone = isSecretary ? '#1E3A5F' : memberTone(memberId);
  const title = message.member_title || member?.title || (isUser ? 'CEO / Chairperson' : humanize(memberId));
  const role = message.role || (member ? roleLabelFor(member) : '');
  let roleLabel: string | null = role;
  if (isSecretary) roleLabel = 'Executive Brief';

  return (
    <li className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="mt-1 h-10 w-10 shrink-0">
          {isSecretary ? (
            <span
              className="grid h-10 w-10 place-items-center rounded-full bg-primary/10 text-primary ring-2 ring-background"
              style={{ boxShadow: `0 0 0 2px ${tone}` }}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
            </span>
          ) : imageUrl ? (
            <img
              src={imageUrl}
              alt=""
              aria-hidden="true"
              className="h-10 w-10 rounded-full object-cover ring-2 ring-background"
              style={{ boxShadow: `0 0 0 2px ${tone}` }}
            />
          ) : (
            <span
              className="grid h-10 w-10 place-items-center rounded-full bg-surface-container-highest text-primary ring-2 ring-background"
              style={{ boxShadow: `0 0 0 2px ${tone}` }}
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
            </span>
          )}
        </div>
      )}

      <article
        className={`max-w-[min(100%,720px)] rounded-lg px-4 py-3 shadow-[0_8px_24px_-20px_rgba(26,22,20,0.25)] ${
          isUser
            ? 'bg-secondary-container text-on-secondary-container'
            : isSecretary
              ? 'border-l-[3px] border-l-primary/60 bg-primary/[0.04] text-on-surface'
              : 'bg-surface-container-lowest text-on-surface'
        }`}
      >
        <header className="mb-2 flex flex-wrap items-center gap-2">
          <h3 className={`font-body text-sm font-semibold ${isUser ? 'text-on-secondary-container' : isSecretary ? 'text-primary' : 'text-on-surface'}`}>
            {title}
          </h3>
          {roleLabel && !isUser ? (
            <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-body tracking-wider ${isSecretary ? 'bg-primary/10 text-primary font-semibold' : 'text-on-surface-variant'}`}>
              {roleLabel}
            </span>
          ) : null}
          {message.created_at ? (
            <span className={`ml-auto text-[10px] font-body ${isUser ? 'text-on-secondary-container/70' : 'text-on-surface-variant'}`}>
              {formatMessageTime(message.created_at)}
            </span>
          ) : null}
        </header>

        {message.content ? (
          isUser ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-on-secondary-container">
              {message.content}
            </p>
          ) : (
            <div
              className="prose-lite text-sm"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
            />
          )
        ) : (
          <div className="flex items-center gap-1.5 py-1 text-xs text-on-surface-variant">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:120ms]" />
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary [animation-delay:240ms]" />
          </div>
        )}

        {active && (
          <p className="mt-2 inline-flex items-center gap-1 text-[10px] font-body tracking-wider text-primary">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" aria-hidden="true" />
            streaming
          </p>
        )}
      </article>
    </li>
  );
}

function formatMessageTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

type DiscussionCardData = {
  key: string;
  stage: number;
  memberId?: string;
  memberTitle: string;
  status?: string;
  headline: string;
  body: string;
  bullets: string[];
  failed?: boolean;
};

function BoardDiscussion({
  session,
  stageEvents,
  members,
}: {
  session: BoardSession | null;
  stageEvents: StageEvent[];
  members: BoardMember[];
}) {
  const cards = buildDiscussionCards(session, stageEvents, members);

  if (!cards.length) {
    return (
      <p className="mt-4 rounded-lg bg-surface-container-lowest p-4 text-sm font-body text-on-surface-variant">
        Member positions will appear as the board responds.
      </p>
    );
  }

  return (
    <div className="mt-5 grid gap-3">
      {cards.map((card) => (
        <article
          key={card.key}
          className={`rounded-lg bg-surface-container-lowest p-4 ${card.failed ? 'border border-error/30' : ''}`}
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[10px] font-body tracking-wider text-primary">
                {discussionStageLabel(card.stage)}
              </p>
              <h3 className="mt-1 font-body text-sm font-semibold text-on-surface">
                {card.memberTitle}
              </h3>
            </div>
            <span
              className={`rounded-lg px-2 py-1 text-[10px] font-body tracking-wider ${
                card.failed ? 'bg-error-container text-error' : 'bg-surface-container-high text-on-surface-variant'
              }`}
            >
              {card.status || (card.failed ? 'Failed' : 'Position')}
            </span>
          </div>
          <h4 className="mt-3 font-headline text-base leading-snug text-on-surface">
            {card.headline}
          </h4>
          {card.body && (
            <div
              className="prose-lite mt-2 text-sm"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(card.body) }}
            />
          )}
          {card.bullets.length ? (
            <ul className="mt-3 grid gap-2">
              {card.bullets.slice(0, 3).map((item, index) => (
                <li key={`${card.key}-bullet-${index}`} className="flex gap-2 text-sm font-body leading-relaxed text-on-surface-variant">
                  <span aria-hidden="true" className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-primary" />
                  <div
                    className="min-w-0 flex-1"
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(item) }}
                  />
                </li>
              ))}
            </ul>
          ) : null}
        </article>
      ))}
    </div>
  );
}

function buildDiscussionCards(
  session: BoardSession | null,
  stageEvents: StageEvent[],
  members: BoardMember[],
): DiscussionCardData[] {
  const titles = new Map(members.map((member) => [member.id, member.title]));
  const byKey = new Map<string, StageMember & { stage: number }>();

  const add = (stage: number, response?: StageMember | null) => {
    if (!response) return;
    const memberId = response.id || response.member_id || (stage === 3 ? 'chairperson' : undefined);
    const key = `${stage}:${memberId || response.title || response.member_title || byKey.size}`;
    const existing = byKey.get(key);
    if (existing?.content && !response.content) return;
    byKey.set(key, { ...existing, ...response, id: memberId, stage });
  };

  stageEvents.forEach((stage) => stage.members?.forEach((member) => add(stage.stage, member)));
  session?.stage1?.forEach((member) => add(1, member));
  session?.stage2?.forEach((member) => add(2, member));
  if (session?.stage3?.content || session?.stage3_synthesis?.content) {
    add(3, {
      id: 'chairperson',
      title: titles.get('chairperson') || 'Chairperson',
      content: session.stage3?.content || session.stage3_synthesis?.content,
    });
  }

  return [...byKey.values()]
    .filter((item) => item.failed || item.content)
    .sort((a, b) => a.stage - b.stage)
    .map((item, index) => {
      const memberId = item.id || item.member_id;
      const memberTitle = item.title || item.member_title || (memberId ? titles.get(memberId) : '') || humanize(memberId || 'Board member');
      return discussionCardFromResponse(item, memberTitle, index);
    });
}

function discussionCardFromResponse(
  response: StageMember & { stage: number },
  memberTitle: string,
  index: number,
): DiscussionCardData {
  const content = response.content || '';
  if (response.failed) {
    return {
      key: `${response.stage}-${response.id || response.member_id || index}`,
      stage: response.stage,
      memberId: response.id || response.member_id,
      memberTitle,
      status: 'Failed',
      headline: response.error || 'This member could not respond.',
      body: '',
      bullets: [],
      failed: true,
    };
  }

  const parsed = parseDiscussionJson(content);
  const section = (name: string) => extractMarkdownSection(content, name);

  if (response.stage === 1) {
    const risks = Array.isArray(parsed?.risks)
      ? parsed.risks.map((risk: unknown) => typeof risk === 'string' ? risk : String((risk as { description?: unknown })?.description || '')).filter(Boolean)
      : [];
    return {
      key: `${response.stage}-${response.id || response.member_id || index}`,
      stage: response.stage,
      memberId: response.id || response.member_id,
      memberTitle,
      status: parsed?.confidence ? `${parsed.confidence} confidence` : 'Independent',
      headline: conciseText(String(parsed?.tldr || section('TL;DR') || section('Recommendation') || 'Independent position')),
      body: conciseMarkdown(String(parsed?.recommendation || section('Recommendation') || parsed?.analysis || section('Analysis') || fallbackExcerpt(content))),
      bullets: risks.length ? risks : splitListish(section('Risks')),
    };
  }

  if (response.stage === 2) {
    const challenges = Array.isArray(parsed?.peer_challenges) ? parsed.peer_challenges.map(String) : splitListish(section('Peer Challenges'));
    return {
      key: `${response.stage}-${response.id || response.member_id || index}`,
      stage: response.stage,
      memberId: response.id || response.member_id,
      memberTitle,
      status: parsed?.confidence ? `${parsed.confidence} confidence` : 'Peer review',
      headline: conciseText(String(parsed?.updated_position || section('Updated Position') || 'Peer challenge')),
      body: conciseMarkdown(String(parsed?.updated_position || section('Updated Position') || fallbackExcerpt(content))),
      bullets: challenges,
    };
  }

  return {
    key: `${response.stage}-${response.id || response.member_id || index}`,
    stage: response.stage,
    memberId: response.id || response.member_id,
    memberTitle,
    status: 'Synthesis',
    headline: 'Chair synthesis',
    body: conciseMarkdown(section('Executive Summary') || fallbackExcerpt(content), 900),
    bullets: splitListish(section('Next Steps')).slice(0, 3),
  };
}

function discussionStageLabel(stage: number) {
  if (stage === 1) return 'Independent Analysis';
  if (stage === 2) return 'Peer Review';
  if (stage === 3) return 'Synthesis';
  return `Stage ${stage}`;
}

function parseDiscussionJson(content: string): Record<string, unknown> | null {
  const fenced = content.match(/```(?:json)?\s*([\s\S]*?)```/i)?.[1];
  const candidates = [fenced, content].filter(Boolean) as string[];
  for (const candidate of candidates) {
    const start = candidate.indexOf('{');
    const end = candidate.lastIndexOf('}');
    if (start === -1 || end <= start) continue;
    try {
      const parsed = JSON.parse(candidate.slice(start, end + 1));
      if (parsed && typeof parsed === 'object') return parsed as Record<string, unknown>;
    } catch {
      continue;
    }
  }
  return null;
}

function extractMarkdownSection(markdown: string, heading: string) {
  const lines = markdown.split(/\r?\n/);
  const target = normalizeHeading(heading);
  const collected: string[] = [];
  let active = false;
  for (const line of lines) {
    const match = line.match(/^\s{0,3}#{2,3}\s+(.+?)\s*$/);
    if (match) {
      const normalized = normalizeHeading(match[1]);
      if (active && normalized !== target) break;
      active = normalized === target;
      continue;
    }
    if (active) collected.push(line);
  }
  return collected.join('\n').trim();
}

function normalizeHeading(value: string) {
  return value.replace(/[*_`]/g, '').replace(/\s+/g, ' ').trim().toLowerCase();
}

function splitListish(markdown: string) {
  if (!markdown.trim()) return [];
  return markdown
    .split(/\r?\n/)
    .map((line) => line.replace(/^\s*(?:[-*]|\d+[.)])\s+/, '').trim())
    .filter(Boolean)
    .filter((line) => !/^[-|:\s]+$/.test(line));
}

function fallbackExcerpt(markdown: string) {
  return stripMarkdown(markdown).slice(0, 420);
}

function conciseText(text: string, max = 180) {
  const clean = stripMarkdown(text).replace(/\s+/g, ' ').trim();
  if (!clean) return 'Board position';
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}…` : clean;
}

function conciseMarkdown(markdown: string, max = 700) {
  const clean = markdown.trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max - 1).trimEnd()}…`;
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

function MissingVoiceRow({
  sessionId,
  routedIds,
  allMembers,
}: {
  sessionId: string | null;
  routedIds: Set<string>;
  allMembers: BoardMember[];
}) {
  const [flagged, setFlagged] = useState<Set<string>>(new Set());

  // Candidates: any known member NOT routed in this session AND not chairperson
  // (chairperson is always at the table by convention).
  const candidates = allMembers.filter(
    (m) => m.id !== 'chairperson' && !routedIds.has(m.id),
  );

  if (candidates.length === 0 || !sessionId) return null;

  const handleFlag = (memberId: string) => {
    if (flagged.has(memberId)) return;
    setFlagged((current) => {
      const next = new Set(current);
      next.add(memberId);
      return next;
    });
    recordRoutingSignal(sessionId, memberId, 'missing_voice_flag').catch(() => {
      // Best-effort — leave the chip flagged locally even if network failed.
    });
  };

  return (
    <section className="mt-6">
      <p className="mb-3 text-xs italic font-body text-on-surface-variant">
        Should any voice have been at the table?
      </p>
      <div className="flex flex-wrap gap-2">
        {candidates.map((member) => {
          const isFlagged = flagged.has(member.id);
          const imageUrl = MEMBER_IMAGES[member.id];
          return (
            <button
              key={member.id}
              type="button"
              disabled={isFlagged}
              onClick={() => handleFlag(member.id)}
              className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-body transition-colors ${
                isFlagged
                  ? 'bg-error-container text-error cursor-default'
                  : 'bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
              }`}
              aria-label={isFlagged ? `Flagged ${member.title}` : `Flag ${member.title} as missing voice`}
            >
              {imageUrl ? (
                <img src={imageUrl} alt="" aria-hidden="true" className="h-5 w-5 rounded-full object-cover" />
              ) : (
                <span className="h-5 w-5 rounded-full bg-surface-container-highest" aria-hidden="true" />
              )}
              <span>{isFlagged ? 'Flagged' : member.title}</span>
            </button>
          );
        })}
      </div>
    </section>
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
      <div
        className="prose-lite mt-2 text-sm"
        dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
      />
    </section>
  );
}

function DecisionList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  const tableLike = items.length === 1 && /\|.+\|/.test(items[0]);
  return (
    <article className="rounded-lg bg-surface-container-lowest p-4">
      <h3 className="font-headline text-lg text-on-surface">{title}</h3>
      {tableLike ? (
        <div
          className="prose-lite mt-3 overflow-x-auto text-sm"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(items[0]) }}
        />
      ) : (
        <ul className="mt-3 space-y-2 pl-1 text-sm leading-relaxed text-on-surface">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className="flex gap-2">
              <span aria-hidden="true" className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-primary" />
              <div
                className="prose-lite min-w-0 flex-1 text-sm"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(item) }}
              />
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
