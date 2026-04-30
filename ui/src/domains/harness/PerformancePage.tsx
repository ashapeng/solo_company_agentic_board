import { Activity, BarChart3, Layers, ShieldCheck } from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { BoardSession, SessionMetrics } from '../../shared/types';
import { MetricCard } from '../../shared/components';
import { metricsByStage } from '../../shared/presentation';

// Cream-legible jewel palette sourced from MEMBER_TONES
const PIE_PALETTE = ['#8C6608', '#1E3A5F', '#6B21A8', '#047857', '#9B2C2C', '#B45309', '#9D174D'];

const AXIS_TICK_STYLE = {
  fontSize: 12,
  fontFamily: 'Manrope',
  fill: '#5C5348',
  fontWeight: 500,
} as const;

const TOOLTIP_STYLE = {
  backgroundColor: '#FFFFFF',
  border: '1px solid #C9BFAE',
  borderRadius: '8px',
  color: '#1A1614',
  fontFamily: 'Manrope',
} as const;

const TOOLTIP_LABEL_STYLE = {
  color: '#5C5348',
  fontFamily: 'Manrope',
} as const;

const TOOLTIP_ITEM_STYLE = {
  color: '#1A1614',
  fontFamily: 'Manrope',
} as const;

export function PerformancePage({ metrics, session }: { metrics: SessionMetrics; session: BoardSession | null }) {
  const stageData = metricsByStage(metrics);
  const totalCalls = metrics.total_calls || 0;
  const totalTokens = metrics.total_tokens || 0;
  const totalCost = Number(metrics.total_cost_estimate_usd || 0);
  const pieData = stageData.map((stage) => ({ name: stage.name, value: stage.tokens || 1 }));
  const avgTokensPerCall = totalCalls ? Math.round(totalTokens / totalCalls) : 0;
  const diagnosticWarnings = [
    ...(session?.delegation_plan?.warnings || []),
    ...(session?.structured_output_warnings || []),
  ];
  const callDiagnostics = session?.metrics?.calls || [];

  return (
    <div className="flex min-h-screen flex-col gap-10 bg-background p-10">
      <header className="flex flex-col gap-3">
        <p className="font-body text-xs font-medium tracking-wider text-primary-fixed-dim">
          Compliance &middot; Performance
        </p>
        <h1 className="font-headline text-4xl italic text-on-surface">Session Telemetry</h1>
        <p className="max-w-3xl font-body text-sm leading-relaxed text-on-surface-variant">
          {session?.session_id
            ? `Current session: ${session.session_id}`
            : 'Most recent saved session from the local API.'}
        </p>
      </header>

      <section className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          icon={<Activity className="h-5 w-5" />}
          label="LLM Calls"
          value={String(totalCalls)}
          detail="Across board stages"
        />
        <MetricCard
          icon={<BarChart3 className="h-5 w-5" />}
          label="Tokens"
          value={totalTokens.toLocaleString()}
          detail="Unknown tokens counted as zero"
        />
        <MetricCard
          icon={<ShieldCheck className="h-5 w-5" />}
          label="Cost"
          value={`$${totalCost.toFixed(4)}`}
          detail="Estimated from configured rates"
        />
        <MetricCard
          icon={<Layers className="h-5 w-5" />}
          label="Tokens / Call"
          value={avgTokensPerCall.toLocaleString()}
          detail="Average weighted across stages"
        />
      </section>

      <section className="grid grid-cols-1 gap-8 lg:grid-cols-2">
        {(diagnosticWarnings.length > 0 || callDiagnostics.length > 0 || session?.verification) && (
          <article className="flex flex-col gap-4 rounded-xl bg-surface-container-lowest p-6 lg:col-span-2">
            <div>
              <h2 className="font-headline text-xl text-on-surface">Session Diagnostics</h2>
              <p className="mt-1 font-body text-sm text-on-surface-variant">
                Audit details hidden from Governance.
              </p>
            </div>

            {diagnosticWarnings.length > 0 && (
              <div>
                <p className="font-body text-xs font-semibold uppercase tracking-wider text-error">Warnings</p>
                <ul className="mt-2 grid gap-2">
                  {diagnosticWarnings.map((warning, index) => (
                    <li key={`${warning}-${index}`} className="rounded-lg bg-error-container/20 px-3 py-2 font-body text-sm text-error">
                      {warning}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {session?.verification && (
              <div className="rounded-lg bg-surface-container-low p-4">
                <p className="font-body text-xs font-semibold uppercase tracking-wider text-on-surface-variant">Verification</p>
                <p className="mt-2 font-body text-sm text-on-surface">
                  Score {session.verification.score ?? 'not scored'} / 10 &middot; {session.verification.passed ? 'passed' : 'not passed'}
                </p>
              </div>
            )}

            {callDiagnostics.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] border-separate border-spacing-y-2 text-left font-body text-sm">
                  <thead className="text-xs uppercase tracking-wider text-on-surface-variant">
                    <tr>
                      <th className="px-3 py-1">Stage</th>
                      <th className="px-3 py-1">Member</th>
                      <th className="px-3 py-1">Model</th>
                      <th className="px-3 py-1">Tokens</th>
                      <th className="px-3 py-1">Latency</th>
                      <th className="px-3 py-1">Finish</th>
                    </tr>
                  </thead>
                  <tbody>
                    {callDiagnostics.map((call, index) => (
                      <tr key={`${call.member_id}-${call.stage}-${index}`} className="bg-surface-container-low">
                        <td className="rounded-l-lg px-3 py-2">{call.stage ?? '-'}</td>
                        <td className="px-3 py-2">{call.member_id || '-'}</td>
                        <td className="px-3 py-2">{call.model || '-'}</td>
                        <td className="px-3 py-2">{Number((call.input_tokens || 0) + (call.output_tokens || 0)).toLocaleString()}</td>
                        <td className="px-3 py-2">{call.latency_seconds !== undefined ? `${Number(call.latency_seconds).toFixed(1)}s` : '-'}</td>
                        <td className="rounded-r-lg px-3 py-2">{call.finish_reason || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>
        )}

        <article className="flex flex-col gap-4 rounded-xl bg-surface-container-lowest p-6">
          <div>
            <h2 className="font-headline text-xl text-on-surface">Stage Tokens</h2>
            <p className="mt-1 font-body text-sm text-on-surface-variant">
              Token pressure by deliberation stage.
            </p>
          </div>
          <div className="h-[320px] w-full" style={{ fontFamily: 'Manrope' }}>
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stageData} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="tokenFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#B8860B" stopOpacity={0.35} />
                    <stop offset="95%" stopColor="#B8860B" stopOpacity={0.04} />
                  </linearGradient>
                </defs>
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={AXIS_TICK_STYLE}
                  stroke="#C9BFAE"
                />
                <YAxis hide />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  itemStyle={TOOLTIP_ITEM_STYLE}
                  cursor={{ stroke: '#9E8F78', strokeOpacity: 0.4 }}
                />
                <Area
                  type="monotone"
                  dataKey="tokens"
                  stroke="#B8860B"
                  strokeWidth={2.5}
                  fill="url(#tokenFill)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="flex flex-col gap-4 rounded-xl bg-surface-container-lowest p-6">
          <div>
            <h2 className="font-headline text-xl text-on-surface">Stage Share</h2>
            <p className="mt-1 font-body text-sm text-on-surface-variant">
              Proportional token allocation per stage.
            </p>
          </div>
          <div className="h-[240px] w-full" style={{ fontFamily: 'Manrope' }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={56}
                  outerRadius={82}
                  paddingAngle={6}
                  dataKey="value"
                  stroke="none"
                >
                  {pieData.map((entry, index) => (
                    <Cell key={entry.name} fill={PIE_PALETTE[index % PIE_PALETTE.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  itemStyle={TOOLTIP_ITEM_STYLE}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="grid gap-2">
            {stageData.map((stage, index) => (
              <div
                key={stage.name}
                className="flex items-center justify-between gap-3 rounded-lg bg-surface-container-low px-3 py-2"
              >
                <span className="flex items-center gap-2 font-body text-sm text-on-surface">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: PIE_PALETTE[index % PIE_PALETTE.length] }}
                  />
                  {stage.name}
                </span>
                <span className="font-body text-sm font-semibold text-on-surface-variant">
                  {stage.calls} calls
                </span>
              </div>
            ))}
          </div>
        </article>

        <article className="flex flex-col gap-4 rounded-xl bg-surface-container-lowest p-6 lg:col-span-2">
          <div>
            <h2 className="font-headline text-xl text-on-surface">Call Mix</h2>
            <p className="mt-1 font-body text-sm text-on-surface-variant">
              Number of LLM calls issued per stage.
            </p>
          </div>
          <div className="h-[260px] w-full" style={{ fontFamily: 'Manrope' }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stageData} margin={{ top: 10, right: 12, left: 0, bottom: 0 }}>
                <XAxis
                  dataKey="name"
                  axisLine={false}
                  tickLine={false}
                  tick={AXIS_TICK_STYLE}
                  stroke="#C9BFAE"
                />
                <YAxis hide />
                <Tooltip
                  contentStyle={TOOLTIP_STYLE}
                  labelStyle={TOOLTIP_LABEL_STYLE}
                  itemStyle={TOOLTIP_ITEM_STYLE}
                  cursor={{ fill: '#E8DFCC', fillOpacity: 0.5 }}
                />
                <Bar dataKey="calls" fill="#1E3A5F" radius={[6, 6, 0, 0]} />
                <Bar dataKey="tokens" fill="#B8860B" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
      </section>
    </div>
  );
}
