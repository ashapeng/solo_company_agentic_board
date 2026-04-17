import { Rocket, Users } from 'lucide-react';
import type { BoardMember, ExecutionAgent, SeatState } from '../../shared/types';
import { Fact, PanelHeading, TagRow } from '../../shared/components';
import {
  MEMBER_ICONS,
  MEMBER_IMAGES,
  humanize,
  memberDossier,
  memberTone,
  roleShort,
} from '../../shared/presentation';

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
    <div className="mx-auto min-h-[calc(100vh-4rem)] max-w-7xl px-4 py-6 md:px-6">
      <header className="mb-6 flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <PanelHeading icon={<Users className="h-4 w-4" />} kicker="Board Roster" title="Member Dossiers" />
        <div className="rounded-lg border border-[#e2e8f0] bg-white px-4 py-3 text-sm font-bold text-[#64748b]">
          {members.length} active members
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {members.map((member) => {
          const Icon = MEMBER_ICONS[member.id] || Users;
          const dossier = memberDossier(member);
          const state = seatStates[member.id] || {};
          const imageUrl = MEMBER_IMAGES[member.id];
          return (
            <article key={member.id} className="rounded-lg border border-slate-100 bg-white p-6 shadow-[0_16px_40px_rgba(0,0,0,0.03)] transition hover:-translate-y-1 hover:shadow-xl" style={{ borderTopColor: memberTone(member.id) }}>
              <div className="grid grid-cols-[auto_1fr_auto] items-center gap-3">
                {imageUrl ? (
                  <img src={imageUrl} alt="" aria-hidden="true" className="h-14 w-14 rounded-full border-2 border-white object-cover shadow-lg ring-4 ring-primary-fixed" />
                ) : (
                  <div className="grid h-14 w-14 place-items-center rounded-full bg-primary/5" style={{ color: memberTone(member.id) }}>
                    <Icon className="h-6 w-6" />
                  </div>
                )}
                <div className="min-w-0">
                  <p className="truncate text-xs font-extrabold uppercase text-primary">{member.governance_seat || roleShort(member.role)}</p>
                  <h2 className="truncate text-lg font-extrabold text-slate-900">{member.title}</h2>
                </div>
                <span className="rounded-lg border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-bold uppercase text-slate-500">
                  {state.label || 'ready'}
                </span>
              </div>

              <dl className="mt-5 grid gap-3">
                <Fact label="Strength" value={dossier.strength} />
                <Fact label="Focus" value={dossier.focus} />
                <Fact label="Signal" value={dossier.signal} />
              </dl>

              <TagRow title="Expertise" items={member.expertise} />
              <TagRow title="Capabilities" items={member.capabilities || []} />
            </article>
          );
        })}
      </div>

      <section className="mt-10">
        <header className="mb-5 flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <PanelHeading icon={<Rocket className="h-4 w-4" />} kicker="Execution Agents" title="Manager Agents" />
          <div className="rounded-lg border border-[#e2e8f0] bg-white px-4 py-3 text-sm font-bold text-[#64748b]">
            {executionAgents.length} active agents
          </div>
        </header>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {executionAgents.map((agent) => (
            <article key={agent.id} className="rounded-lg border border-slate-100 bg-white p-5 shadow-[0_16px_40px_rgba(0,0,0,0.03)]">
              <p className="text-xs font-extrabold uppercase text-primary">{humanize(agent.execution_unit_id)}</p>
              <h2 className="mt-1 text-lg font-extrabold text-slate-900">{agent.title}</h2>
              <p className="mt-2 text-sm leading-relaxed text-[#64748b]">{agent.role}</p>
              <TagRow title="Capabilities" items={agent.capabilities} />
              <div className="mt-4 grid gap-2">
                {agent.subagent_templates.slice(0, 3).map((template) => (
                  <div key={template.id} className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2">
                    <p className="text-xs font-extrabold text-[#0f172a]">{template.title}</p>
                    <p className="mt-1 text-xs leading-relaxed text-[#64748b]">{template.purpose}</p>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

