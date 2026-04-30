import { MoreHorizontal } from 'lucide-react';
import type { DelegatedTask, DelegationPlan, ExecutionAgent } from '../../shared/types';
import { PlainList } from '../../shared/components';
import { humanize, taskStatusClass } from '../../shared/presentation';

function statusKickerColor(status: DelegatedTask['status']): string {
  if (status === 'running') return 'text-primary';
  if (status === 'completed') return 'text-primary-fixed-dim';
  if (status === 'approved') return 'text-secondary';
  if (status === 'blocked' || status === 'rejected') return 'text-error';
  return 'text-on-surface-variant';
}

function progressForStatus(status: DelegatedTask['status']): number {
  if (status === 'running') return 60;
  if (status === 'completed') return 100;
  if (status === 'approved') return 25;
  if (status === 'blocked' || status === 'rejected') return 40;
  return 10;
}

function subtaskAccentClass(status: string): string {
  if (status === 'running' || status === 'completed') return 'accent-bar-left';
  return '';
}

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
      <div className="flex flex-col gap-3 rounded-lg bg-surface-container-lowest p-5">
        <div className="flex items-center justify-between gap-3">
          <p className="font-body text-[11px] font-medium tracking-wider text-primary-fixed-dim">
            Awaiting Delegation
          </p>
          <MoreHorizontal className="h-4 w-4 text-on-surface-variant/60" aria-hidden="true" />
        </div>
        <h3 className="font-headline text-lg text-on-surface">Manager agents stand by</h3>
        <p className="font-body text-sm italic leading-relaxed text-on-surface-variant">
          No delegation planned yet. {routingLabel} will create approval-gated tasks after synthesis.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {tasks.map((task) => {
        const agent = agentsById.get(task.manager_agent_id);
        const kickerColor = statusKickerColor(task.status);
        const progress = progressForStatus(task.status);
        return (
          <article
            key={task.id}
            className="flex flex-col gap-3 rounded-lg bg-surface-container-lowest p-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className={`text-xs font-body font-bold uppercase tracking-wider ${kickerColor}`}>
                  {agent?.title || humanize(task.manager_agent_id)}
                </p>
                <h3 className="mt-1 font-body text-sm leading-tight text-on-surface">
                  {task.title}
                </h3>
              </div>
              <span
                className={`shrink-0 rounded-full px-2 py-1 text-[10px] font-body font-semibold uppercase tracking-wider ${taskStatusClass(task.status)}`}
              >
                {task.status}
              </span>
              <button
                type="button"
                aria-label="More actions"
                className="shrink-0 rounded-lg p-1 text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface"
              >
                <MoreHorizontal className="h-4 w-4" />
              </button>
            </div>

            <p className="font-body text-sm leading-relaxed text-on-surface-variant">
              {task.objective}
            </p>

            {task.status === 'running' && (
              <div className="h-1 w-full rounded-full bg-surface-container-high">
                <div
                  className="h-1 rounded-full bg-secondary-container"
                  style={{ width: `${progress}%` }}
                />
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <span className="rounded-full bg-surface-container-high px-3 py-1 text-xs font-medium text-on-surface-variant">
                {humanize(task.execution_unit_id)}
              </span>
              <span className="rounded-full bg-surface-container-high px-3 py-1 text-xs font-medium text-on-surface-variant">
                Priority &middot; {task.priority}
              </span>
              <span className="rounded-full bg-surface-container-high px-3 py-1 text-xs font-medium text-on-surface-variant">
                Board &middot; {humanize(task.accountable_board_member_id)}
              </span>
            </div>

            <PlainList items={task.acceptance_criteria?.slice(0, 3)} />

            {task.subtask_plan?.subtasks?.length ? (
              <div className="mt-1 flex flex-col gap-2 pt-2">
                {task.subtask_plan.subtasks.map((subtask) => {
                  const isActive = subtask.status === 'running' || subtask.status === 'completed';
                  return (
                    <div
                      key={subtask.id}
                      className={`rounded-lg bg-surface-container-low px-3 py-2 ${
                        isActive ? subtaskAccentClass(subtask.status) : ''
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-body text-xs font-semibold text-on-surface">
                          {subtask.title}
                        </span>
                        <span className="text-[10px] font-medium uppercase tracking-wider text-on-surface-variant">
                          {subtask.status}
                        </span>
                      </div>
                      <p className="mt-1 font-body text-xs leading-relaxed text-on-surface-variant">
                        {subtask.objective}
                      </p>
                    </div>
                  );
                })}
              </div>
            ) : null}

            {task.result_summary && (
              <p className="font-body text-sm text-on-surface-variant">{task.result_summary}</p>
            )}
            {task.artifacts?.length ? <PlainList items={task.artifacts} /> : null}

            <div className="flex flex-wrap gap-2">
              {task.status === 'proposed' && (
                <button
                  type="button"
                  onClick={() => onApproveTask(task.id)}
                  className="rounded-lg bg-surface-container-high/0 px-3 py-1.5 font-body text-sm text-primary-fixed-dim transition-colors hover:bg-surface-container-high hover:text-primary"
                >
                  Approve Task
                </button>
              )}
              {task.status === 'approved' && (
                <button
                  type="button"
                  onClick={() => onPlanTask(task)}
                  className="rounded-lg bg-surface-container-high/0 px-3 py-1.5 font-body text-sm text-primary-fixed-dim transition-colors hover:bg-surface-container-high hover:text-primary"
                >
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
