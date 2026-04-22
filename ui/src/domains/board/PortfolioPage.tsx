import { Users } from 'lucide-react';
import type { CSSProperties } from 'react';
import type { BoardMember, ExecutionAgent, SeatState } from '../../shared/types';
import { Fact, MaterialCard, PlainList, SectionLabel, TagRow } from '../../shared/components';
import {
  MEMBER_ICONS,
  MEMBER_IMAGES,
  humanize,
  memberDossier,
  memberTone,
  roleShort,
} from '../../shared/presentation';

type RingStyle = CSSProperties & { ['--tw-ring-color']?: string };

export function PortfolioPage({
  members,
  seatStates,
  executionAgents,
}: {
  members: BoardMember[];
  seatStates: Record<string, SeatState>;
  executionAgents: ExecutionAgent[];
}) {
  return (
    <div className="flex min-h-screen flex-col gap-10 bg-background p-10">
      <header className="flex flex-col gap-3">
        <p className="font-body text-xs font-medium tracking-wider text-primary-fixed-dim">
          Portfolio of Advisors
        </p>
        <h1 className="font-headline text-4xl italic text-on-surface">The Council</h1>
        <p className="max-w-3xl font-body text-sm leading-relaxed text-on-surface-variant">
          A seated roster of specialist advisors. Each dossier captures the seat, headline strength,
          and focus the member is accountable for when the board is convened.
        </p>
        <div className="flex flex-wrap gap-2">
          <span className="rounded-full bg-surface-container-high px-3 py-1 text-xs font-medium text-on-surface-variant">
            {members.length} active members
          </span>
          {executionAgents.length > 0 && (
            <span className="rounded-full bg-surface-container-high px-3 py-1 text-xs font-medium text-on-surface-variant">
              {executionAgents.length} execution agents
            </span>
          )}
        </div>
      </header>

      <section className="grid grid-cols-1 gap-8 md:grid-cols-2 xl:grid-cols-3">
        {members.map((member) => {
          const Icon = MEMBER_ICONS[member.id] || Users;
          const dossier = memberDossier(member);
          const state = seatStates[member.id] || {};
          const imageUrl = MEMBER_IMAGES[member.id];
          const tone = memberTone(member.id);
          const ringStyle: RingStyle = { ['--tw-ring-color']: tone };
          return (
            <article
              key={member.id}
              className="flex flex-col gap-4 rounded-xl bg-surface-container-lowest p-6 transition-transform hover:scale-[1.01]"
            >
              <div className="flex items-center gap-4">
                {imageUrl ? (
                  <img
                    src={imageUrl}
                    alt=""
                    aria-hidden="true"
                    className="h-16 w-16 rounded-full object-cover ring-2 ring-offset-2 ring-offset-surface-container-lowest"
                    style={ringStyle}
                  />
                ) : (
                  <div
                    className="grid h-16 w-16 place-items-center rounded-full bg-surface-container-high ring-2 ring-offset-2 ring-offset-surface-container-lowest"
                    style={ringStyle}
                  >
                    <Icon className="h-6 w-6" style={{ color: tone }} />
                  </div>
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[10px] font-medium uppercase tracking-wider text-primary-fixed-dim">
                    {member.governance_seat || roleShort(member.role)}
                  </p>
                  <h2 className="truncate font-headline text-xl text-on-surface">{member.title}</h2>
                  <p className="mt-1 text-xs font-medium text-on-surface-variant">
                    {state.label || 'ready'}
                  </p>
                </div>
              </div>

              <div>
                <SectionLabel>Dossier</SectionLabel>
                <dl className="mt-2 grid gap-1">
                  <Fact label="Strength" value={dossier.strength} />
                  <Fact label="Focus" value={dossier.focus} />
                  <Fact label="Signal" value={dossier.signal} />
                </dl>
              </div>

              <TagRow title="Expertise" items={member.expertise} />

              {member.capabilities?.length ? (
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-on-surface-variant">
                    Capabilities
                  </p>
                  <PlainList items={member.capabilities.slice(0, 4)} />
                </div>
              ) : null}
            </article>
          );
        })}
      </section>

      {executionAgents.length > 0 && (
        <section className="flex flex-col gap-5">
          <header className="flex flex-col gap-2">
            <p className="font-body text-xs font-medium tracking-wider text-primary-fixed-dim">
              Execution Fleet
            </p>
            <h2 className="font-headline text-2xl italic text-on-surface">Manager Agents</h2>
            <p className="max-w-2xl font-body text-sm leading-relaxed text-on-surface-variant">
              Approval-gated workers that pick up board decisions and translate them into subtasks.
            </p>
          </header>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3">
            {executionAgents.map((agent) => (
              <article
                key={agent.id}
                className="flex flex-col gap-3 rounded-xl bg-surface-container-lowest p-5"
              >
                <div className="flex flex-col gap-1">
                  <p className="text-[10px] font-medium uppercase tracking-wider text-primary-fixed-dim">
                    {humanize(agent.execution_unit_id)}
                  </p>
                  <h3 className="font-headline text-lg text-on-surface">{agent.title}</h3>
                  <p className="font-body text-sm leading-relaxed text-on-surface-variant">
                    {agent.role}
                  </p>
                </div>
                <TagRow title="Capabilities" items={agent.capabilities} />
                {agent.subagent_templates.slice(0, 3).map((template) => (
                  <MaterialCard
                    key={template.id}
                    icon={<span className="text-xs">{'•'}</span>}
                    title={template.title}
                    subtitle={template.purpose}
                  />
                ))}
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
