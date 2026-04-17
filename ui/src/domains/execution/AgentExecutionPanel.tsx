import type { DelegatedTask, DelegationPlan, ExecutionAgent } from '../../shared/types';
import { PlainList } from '../../shared/components';
import { humanize, taskStatusClass } from '../../shared/presentation';

export function AgentExecutionPanel({
  delegationPlan,
  executionAgents,
  routingLabel,
  onApproveTask,
  onPlanTask,
}: {
  delegationPlan: DelegationPlan | null;
  executionAgents: ExecutionAgent[];
  routingLabel: string;
  onApproveTask: (taskId: string) => void;
  onPlanTask: (task: DelegatedTask) => void;
}) {
  const agentsById = new Map(executionAgents.map((agent) => [agent.id, agent]));
  const tasks = delegationPlan?.tasks || [];

  if (!tasks.length) {
    return (
      <div className="relative grid gap-5 pl-5">
        <div className="absolute bottom-2 left-1 top-2 w-px bg-primary-fixed" />
        <article className="relative text-on-surface">
          <span className="absolute -left-[1.28rem] top-1 h-2.5 w-2.5 rounded-full bg-primary" />
          <p className="text-[11px] font-extrabold uppercase text-primary">Awaiting Delegation</p>
          <h3 className="mt-1 text-sm font-extrabold">Manager agents stand by</h3>
          <p className="mt-1 text-sm leading-relaxed">{routingLabel} will create approval-gated tasks after synthesis.</p>
          {delegationPlan?.warnings?.map((warning) => (
            <p key={warning} className="mt-2 text-xs font-semibold text-[#b42318]">{warning}</p>
          ))}
        </article>
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      {tasks.map((task) => {
        const agent = agentsById.get(task.manager_agent_id);
        return (
          <article key={task.id} className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[11px] font-extrabold uppercase text-primary">{agent?.title || humanize(task.manager_agent_id)}</p>
                <h3 className="mt-1 text-sm font-extrabold leading-tight text-[#0f172a]">{task.title}</h3>
              </div>
              <span className={`shrink-0 rounded-lg px-2 py-1 text-[10px] font-extrabold uppercase ${taskStatusClass(task.status)}`}>
                {task.status}
              </span>
            </div>
            <p className="mt-2 text-sm leading-relaxed text-[#64748b]">{task.objective}</p>
            <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-extrabold uppercase text-[#64748b]">
              <span className="rounded-lg border border-[#e2e8f0] bg-white px-2 py-1">{humanize(task.execution_unit_id)}</span>
              <span className="rounded-lg border border-[#e2e8f0] bg-white px-2 py-1">{task.priority}</span>
              <span className="rounded-lg border border-[#e2e8f0] bg-white px-2 py-1">Board: {humanize(task.accountable_board_member_id)}</span>
            </div>
            <PlainList items={task.acceptance_criteria?.slice(0, 3)} />
            {task.subtask_plan?.subtasks?.length ? (
              <div className="mt-3 grid gap-2 border-t border-[#e2e8f0] pt-3">
                {task.subtask_plan.subtasks.map((subtask) => (
                  <div key={subtask.id} className="rounded-lg border border-[#e2e8f0] bg-white px-3 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-extrabold text-[#0f172a]">{subtask.title}</span>
                      <span className="text-[10px] font-bold uppercase text-[#64748b]">{subtask.status}</span>
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-[#64748b]">{subtask.objective}</p>
                  </div>
                ))}
              </div>
            ) : null}
            {task.result_summary && <p className="mt-3 text-sm font-semibold text-[#475569]">{task.result_summary}</p>}
            {task.artifacts?.length ? <PlainList items={task.artifacts} /> : null}
            <div className="mt-3 flex flex-wrap gap-2">
              {task.status === 'proposed' && (
                <button type="button" onClick={() => onApproveTask(task.id)} className="rounded-lg bg-[#0f172a] px-3 py-2 text-xs font-extrabold text-white hover:bg-[#003d9b]">
                  Approve Task
                </button>
              )}
              {task.status === 'approved' && (
                <button type="button" onClick={() => onPlanTask(task)} className="rounded-lg border border-[#cbd5e1] bg-white px-3 py-2 text-xs font-extrabold text-[#003d9b] hover:border-[#003d9b]">
                  Plan Subtasks
                </button>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}

