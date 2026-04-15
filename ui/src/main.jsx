import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import './styles.css';

const API = '';

const STAGE_NAMES = {
  1: 'Independent analysis',
  2: 'Peer review',
  3: 'Chair synthesis',
};

const SEAT_ORDER = [
  'chairperson',
  'strategist',
  'product',
  'researcher',
  'critic',
  'architect',
  'builder',
  'guardian',
  'operator',
];

const SEAT_POSITIONS = [
  'seat-chair',
  'seat-left-high',
  'seat-right-high',
  'seat-left-mid',
  'seat-right-mid',
  'seat-left-low',
  'seat-right-low',
  'seat-left-far',
  'seat-right-far',
];

const MEMBER_COLORS = {
  chairperson: 'emerald',
  strategist: 'blue',
  product: 'coral',
  researcher: 'green',
  critic: 'ink',
  architect: 'gold',
  builder: 'teal',
  guardian: 'red',
  operator: 'violet',
};

function App() {
  const [members, setMembers] = useState([]);
  const [query, setQuery] = useState('');
  const [fullBoard, setFullBoard] = useState(false);
  const [verify, setVerify] = useState(false);
  const [running, setRunning] = useState(false);
  const [session, setSession] = useState(null);
  const [stageEvents, setStageEvents] = useState([]);
  const [seatStates, setSeatStates] = useState({});
  const [tableStatus, setTableStatus] = useState({
    label: 'Ready',
    title: 'Waiting for a CEO decision',
    detail: 'Ask the board to classify, deliberate, review, and synthesize.',
  });
  const [sessionLabel, setSessionLabel] = useState('No active session');
  const [error, setError] = useState('');
  const resultRef = useRef(null);

  useEffect(() => {
    loadMembers()
      .then((payload) => {
        setMembers(payload);
        setSeatStates(initialSeatStates(payload));
      })
      .catch((err) => {
        console.error(err);
        setError('Failed to load board members.');
      });
  }, []);

  const orderedMembers = useMemo(() => orderMembers(members), [members]);

  useEffect(() => {
    if (session && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [session]);

  async function submitQuery(event) {
    event.preventDefault();
    const cleanQuery = query.trim();
    if (!cleanQuery || running) return;

    setRunning(true);
    setError('');
    setSession(null);
    setStageEvents([]);
    setSessionLabel('Session in progress');
    setSeatStates(resetSeatStates(members, fullBoard));
    setTableStatus({
      label: 'Routing',
      title: 'Selecting board members',
      detail: 'The chair will route the decision to the smallest useful council.',
    });

    try {
      await streamDeliberation({
        query: cleanQuery,
        full_board: fullBoard,
        verify,
      }, {
        onEvent: handleStreamEvent,
      });
    } catch (err) {
      const message = err?.message || 'Deliberation failed.';
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

  function handleStreamEvent(data) {
    if (data.event === 'stage_start') {
      setTableStatus(statusForStageStart(data.stage, data.name));
      setStageEvents((events) => upsertStage(events, data.stage, {
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

    if (data.event === 'member_done') {
      setStageEvents((events) => addStageMember(events, data.stage, {
        id: data.member_id,
        title: data.member_title,
        model: data.model,
        elapsed: data.elapsed,
        failed: false,
      }));
      setSeatStates((states) => ({
        ...states,
        [data.member_id]: {
          ...(states[data.member_id] || {}),
          status: 'done',
          label: `${stageShortLabel(data.stage)} done`,
          model: data.model,
        },
      }));
      setTableStatus((current) => ({
        ...current,
        detail: `${data.member_title} completed ${stageShortLabel(data.stage)}.`,
      }));
      return;
    }

    if (data.event === 'member_failed') {
      setStageEvents((events) => addStageMember(events, data.stage, {
        id: data.member_id,
        title: data.member_title,
        error: data.error,
        failed: true,
      }));
      setSeatStates((states) => ({
        ...states,
        [data.member_id]: {
          ...(states[data.member_id] || {}),
          status: 'failed',
          label: 'failed',
        },
      }));
      return;
    }

    if (data.event === 'stage_done') {
      setStageEvents((events) => upsertStage(events, data.stage, {
        active: false,
        done: true,
        count: data.count,
      }));
      setTableStatus({
        label: `Stage ${data.stage}`,
        title: `${STAGE_NAMES[data.stage] || 'Stage'} complete`,
        detail: `${data.count} response${data.count === 1 ? '' : 's'} collected.`,
      });
      return;
    }

    if (data.event === 'complete') {
      const nextSession = data.session;
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

  function markSelectedMembers(classification) {
    const selected = new Set(classification?.relevant_member_ids || []);
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
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Agentic board members</p>
          <h1>Agentic Board</h1>
        </div>
        <div className="session-chip">{sessionLabel}</div>
      </header>

      <main>
        <section className="boardroom" aria-label="Agentic Board round table">
          <div className="boardroom-copy">
            <p className="eyebrow">Boardroom</p>
            <h2>Bring the decision to the table.</h2>
          </div>

          <div className="council-table" aria-label="Board member seats">
            <img className="table-texture" src="/ui/assets/council-table-texture.png" alt="" aria-hidden="true" />
            <TableStatus status={tableStatus} />
            <div className="members-ring">
              {orderedMembers.map((member, index) => (
                <BoardSeat
                  key={member.id}
                  member={member}
                  index={index}
                  state={seatStates[member.id]}
                />
              ))}
            </div>
            <CeoComposer
              query={query}
              setQuery={setQuery}
              fullBoard={fullBoard}
              setFullBoard={setFullBoard}
              verify={verify}
              setVerify={setVerify}
              running={running}
              onSubmit={submitQuery}
            />
          </div>
        </section>

        {stageEvents.length > 0 && (
          <section className="progress-section">
            <SectionHeading eyebrow="Live run" title="Deliberation Timeline" />
            <StageTimeline stages={stageEvents} />
          </section>
        )}

        {(session || error) && (
          <section className="result-section" ref={resultRef}>
            <SectionHeading eyebrow="Board decision" title="Decision Record" />
            {error ? <div className="error-msg">{error}</div> : <DecisionRecord session={session} />}
          </section>
        )}

        {session && (
          <section className="inspector-section">
            <SectionHeading eyebrow="Inspector" title="Session Details" />
            <Metrics metrics={session.metrics} />
            <details>
              <summary>Full chair memo</summary>
              <div className="decision-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(getSynthesis(session)?.content || '') }} />
            </details>
          </section>
        )}
      </main>
    </div>
  );
}

function CeoComposer({ query, setQuery, fullBoard, setFullBoard, verify, setVerify, running, onSubmit }) {
  return (
    <form className="ceo-seat" onSubmit={onSubmit} aria-label="CEO decision input">
      <div className="ceo-identity">
        <Avatar label="CEO" tone="ink" />
        <div>
          <strong>You</strong>
          <span>CEO</span>
        </div>
      </div>

      <textarea
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            onSubmit(event);
          }
        }}
        placeholder="What should the board decide?"
        rows={4}
      />

      <div className="ceo-controls">
        <label>
          <input type="checkbox" checked={fullBoard} onChange={(event) => setFullBoard(event.target.checked)} />
          Full board
        </label>
        <label>
          <input type="checkbox" checked={verify} onChange={(event) => setVerify(event.target.checked)} />
          Verify
        </label>
        <button type="submit" disabled={running || !query.trim()}>
          {running ? 'Deliberating...' : 'Ask the Board'}
        </button>
      </div>
    </form>
  );
}

function BoardSeat({ member, index, state = {} }) {
  const positionClass = SEAT_POSITIONS[index % SEAT_POSITIONS.length];
  const statusClass = state.status || (state.selected ? 'selected' : 'idle');
  const modelOrSeat = state.model || member.governance_seat || roleShort(member.role);
  return (
    <button
      className={`member-seat ${positionClass} ${statusClass} ${state.selected ? 'selected' : ''}`}
      type="button"
      aria-label={`${member.title}, ${member.role}`}
    >
      <Avatar label={initials(member.title)} tone={MEMBER_COLORS[member.id] || 'teal'} />
      <span className="seat-copy">
        <span className="seat-title">{member.title}</span>
        <span className="seat-role">{roleShort(member.role)}</span>
        <span className="seat-model">{modelOrSeat}</span>
        <span className="seat-state">{state.label || 'idle'}</span>
      </span>
    </button>
  );
}

function Avatar({ label, tone }) {
  return (
    <span className={`avatar avatar-${tone}`} aria-hidden="true">
      <span className="avatar-head" />
      <span className="avatar-body" />
      <span className="avatar-label">{label}</span>
    </span>
  );
}

function TableStatus({ status }) {
  return (
    <div className="table-status">
      <p className="status-label">{status.label}</p>
      <p className="status-title">{status.title}</p>
      <p className="status-detail">{status.detail}</p>
    </div>
  );
}

function StageTimeline({ stages }) {
  return (
    <div className="timeline">
      {stages.map((stage) => (
        <article className="stage" key={stage.stage}>
          <div className="stage-header">
            <span className={`indicator ${stage.active ? 'active' : ''} ${stage.done ? 'done' : ''}`} />
            <span>Stage {stage.stage} - {STAGE_NAMES[stage.stage] || 'Processing'}</span>
          </div>
          <div className="stage-members">
            {(stage.members || []).map((member, index) => (
              <div className={`stage-member ${member.failed ? 'failed' : 'done'}`} key={`${member.id}-${index}`}>
                <span>{member.failed ? '×' : '✓'}</span>
                <span>{member.title}</span>
                {member.model && <span className="model-pill">{member.model}</span>}
                {member.elapsed !== undefined && <span className="elapsed">{Number(member.elapsed).toFixed(1)}s</span>}
              </div>
            ))}
          </div>
        </article>
      ))}
    </div>
  );
}

function DecisionRecord({ session }) {
  const decision = session?.decision || {};
  const verification = session?.verification || {};
  const memory = session?.memory || {};
  const classification = session?.classification || {};
  const hasStructuredDecision = Object.values(decision).some(Boolean);

  if (!hasStructuredDecision) {
    const synthesis = getSynthesis(session);
    return (
      <div className="decision-wide" dangerouslySetInnerHTML={{ __html: renderMarkdown(synthesis?.content || 'No decision returned.') }} />
    );
  }

  return (
    <div className="decision-layout">
      <article className="decision-main">
        <DecisionBlock title="Executive Summary" content={decision.executive_summary} />
        <DecisionBlock title="Strategic Direction" content={decision.strategic_direction} />
        <DecisionBlock title="Architecture & Design" content={decision.architecture_design} />
        <DecisionBlock title="Security Posture" content={decision.security_posture} />
      </article>

      <aside className="decision-side">
        <DecisionList title="Next Steps" items={decision.next_steps} />
        <DecisionList title="Top Risks" items={decision.risk_register} />
        <DecisionList title="Dissent" items={decision.dissenting_views} />
      </aside>

      <article className="decision-wide">
        <h3>Verification</h3>
        <p>{verification.score !== undefined ? `Score ${verification.score}/10 - ${verification.passed ? 'passed' : 'needs review'}` : 'Verification not run.'}</p>
        <PlainList items={verification.deficiencies} />
      </article>

      <article className="decision-wide">
        <h3>Routing</h3>
        <p>{classification.query_type ? `${classification.query_type} - ${classification.complexity || 'unscored'}` : 'Routing details unavailable.'}</p>
        <PlainList items={classification.relevant_member_ids} />
        {classification.role_gap_memo && <p>{classification.role_gap_memo}</p>}
      </article>

      <article className="decision-wide">
        <h3>SOTB Proposal</h3>
        <p>{memory.proposed_sotb_update || 'No memory update proposed.'}</p>
        {memory.requires_approval && <p>Human approval required before durable memory changes.</p>}
      </article>
    </div>
  );
}

function DecisionBlock({ title, content }) {
  if (!content) return null;
  return (
    <div className="decision-block">
      <h3>{title}</h3>
      <p>{content}</p>
    </div>
  );
}

function DecisionList({ title, items }) {
  if (!items || (Array.isArray(items) && !items.length)) return null;
  return (
    <div className="decision-block">
      <h3>{title}</h3>
      <PlainList items={items} />
    </div>
  );
}

function PlainList({ items }) {
  if (!items) return null;
  const values = Array.isArray(items) ? items : [items];
  if (!values.length) return null;
  return (
    <ul className="decision-list">
      {values.map((item, index) => <li key={`${item}-${index}`}>{String(item)}</li>)}
    </ul>
  );
}

function Metrics({ metrics = {} }) {
  const tokens = metrics.total_tokens || 0;
  const cost = metrics.total_cost_estimate_usd || 0;
  return (
    <div className="metrics">
      <span><strong>{metrics.total_calls || 0}</strong> LLM calls</span>
      <span><strong>{tokens.toLocaleString()}</strong> tokens</span>
      <span><strong>${Number(cost).toFixed(4)}</strong> estimated cost</span>
    </div>
  );
}

function SectionHeading({ eyebrow, title }) {
  return (
    <div className="section-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
    </div>
  );
}

async function loadMembers() {
  const resp = await fetch(`${API}/members`);
  if (!resp.ok) throw new Error('Failed to load members.');
  return resp.json();
}

async function streamDeliberation(params, { onEvent }) {
  const response = await fetch(`${API}/deliberate/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Server error: ${response.status} - ${err}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data: ')) continue;
      try {
        onEvent(JSON.parse(trimmed.slice(6)));
      } catch {
        // Ignore keepalives and malformed partials.
      }
    }
  }
}

function orderMembers(items) {
  const byId = new Map(items.map((member) => [member.id, member]));
  return [
    ...SEAT_ORDER.filter((id) => byId.has(id)).map((id) => byId.get(id)),
    ...items.filter((member) => !SEAT_ORDER.includes(member.id)),
  ];
}

function initialSeatStates(items) {
  return Object.fromEntries(items.map((member) => [member.id, { status: 'idle', label: 'idle' }]));
}

function resetSeatStates(items, fullBoard) {
  return Object.fromEntries(items.map((member) => [
    member.id,
    {
      status: fullBoard ? 'selected' : 'idle',
      label: fullBoard ? 'selected' : 'idle',
      selected: fullBoard,
    },
  ]));
}

function upsertStage(events, stage, patch) {
  const existing = events.find((item) => item.stage === stage);
  if (!existing) return [...events, { stage, members: [], ...patch }];
  return events.map((item) => item.stage === stage ? { ...item, ...patch } : item);
}

function addStageMember(events, stage, member) {
  const existing = events.find((item) => item.stage === stage);
  if (!existing) return [...events, { stage, active: true, done: false, members: [member] }];
  return events.map((item) => item.stage === stage ? { ...item, members: [...(item.members || []), member] } : item);
}

function statusForStageStart(stage, name) {
  if (stage === 1) {
    return {
      label: 'Stage 1',
      title: 'Independent analysis',
      detail: 'Board members are forming first-pass positions without peer influence.',
    };
  }
  if (stage === 2) {
    return {
      label: 'Stage 2',
      title: 'Peer review',
      detail: 'Members are challenging compacted peer positions.',
    };
  }
  if (stage === 3) {
    return {
      label: 'Stage 3',
      title: 'Chair synthesis',
      detail: 'The chair is resolving dissent into one board decision.',
    };
  }
  return {
    label: `Stage ${stage}`,
    title: name || 'Processing',
    detail: 'The board is working.',
  };
}

function getSynthesis(session) {
  return session?.stage3 || session?.stage3_synthesis || null;
}

function renderMarkdown(markdown) {
  return DOMPurify.sanitize(marked.parse(markdown || ''), { USE_PROFILES: { html: true } });
}

function initials(title) {
  return title
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0])
    .join('')
    .toUpperCase();
}

function roleShort(role) {
  return role.split('/')[0].trim();
}

function stageShortLabel(stage) {
  if (stage === 1) return 'analysis';
  if (stage === 2) return 'review';
  if (stage === 3) return 'synthesis';
  return 'stage';
}

createRoot(document.getElementById('root')).render(<App />);
