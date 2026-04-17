import { Activity, BarChart3, ShieldCheck, TrendingUp } from 'lucide-react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { BoardSession, SessionMetrics } from '../../shared/types';
import { MetricCard, PanelHeading } from '../../shared/components';
import { metricsByStage } from '../../shared/presentation';

export function PerformancePage({ metrics, session }: { metrics: SessionMetrics; session: BoardSession | null }) {
  const stageData = metricsByStage(metrics);
  const totalCalls = metrics.total_calls || 0;
  const totalTokens = metrics.total_tokens || 0;
  const totalCost = Number(metrics.total_cost_estimate_usd || 0);
  const pieData = stageData.map((stage) => ({ name: stage.name, value: stage.tokens || 1 }));

  return (
    <div className="mx-auto min-h-[calc(100vh-4rem)] max-w-7xl px-4 py-6 md:px-6">
      <header className="mb-6 flex flex-col justify-between gap-4 md:flex-row md:items-end">
        <div>
          <PanelHeading icon={<TrendingUp className="h-4 w-4" />} kicker="Performance" title="Run Metrics" />
          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[#64748b]">
            {session?.session_id ? `Current session: ${session.session_id}` : 'Most recent saved session from the local API.'}
          </p>
        </div>
      </header>

      <div className="mb-6 grid gap-4 md:grid-cols-3">
        <MetricCard icon={<Activity className="h-5 w-5" />} label="LLM Calls" value={String(totalCalls)} detail="Across board stages" />
        <MetricCard icon={<BarChart3 className="h-5 w-5" />} label="Tokens" value={totalTokens.toLocaleString()} detail="Unknown tokens counted as zero" />
        <MetricCard icon={<ShieldCheck className="h-5 w-5" />} label="Cost" value={`$${totalCost.toFixed(4)}`} detail="Estimated from configured rates" />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1.35fr_0.65fr]">
        <article className="rounded-lg border border-[#e2e8f0] bg-white p-5 shadow-sm">
          <h2 className="text-xl font-extrabold text-[#0f172a]">Stage Tokens</h2>
          <div className="mt-5 h-[340px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={stageData}>
                <defs>
                  <linearGradient id="tokenFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#003d9b" stopOpacity={0.22} />
                    <stop offset="95%" stopColor="#003d9b" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: '#64748b', fontWeight: 700 }} />
                <YAxis hide />
                <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid #e2e8f0' }} />
                <Area type="monotone" dataKey="tokens" stroke="#003d9b" strokeWidth={3} fill="url(#tokenFill)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </article>

        <article className="rounded-lg border border-[#e2e8f0] bg-white p-5 shadow-sm">
          <h2 className="text-xl font-extrabold text-[#0f172a]">Stage Share</h2>
          <div className="mt-5 h-[240px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={pieData} cx="50%" cy="50%" innerRadius={58} outerRadius={82} paddingAngle={6} dataKey="value">
                  {['#003d9b', '#003d9b', '#c45a45'].map((color, index) => (
                    <Cell key={color} fill={color} stroke={index === 0 ? '#ffffff' : color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid #e2e8f0' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 grid gap-2">
            {stageData.map((stage, index) => (
              <div key={stage.name} className="flex items-center justify-between gap-3 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] px-3 py-2">
                <span className="flex items-center gap-2 text-sm font-bold text-[#475569]">
                  <span className="h-2.5 w-2.5 rounded-lg" style={{ backgroundColor: ['#003d9b', '#003d9b', '#c45a45'][index] }} />
                  {stage.name}
                </span>
                <span className="text-sm font-extrabold text-[#0f172a]">{stage.calls} calls</span>
              </div>
            ))}
          </div>
        </article>

        <article className="rounded-lg border border-[#e2e8f0] bg-white p-5 shadow-sm lg:col-span-2">
          <h2 className="text-xl font-extrabold text-[#0f172a]">Call Mix</h2>
          <div className="mt-5 h-[260px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={stageData}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: '#64748b', fontWeight: 700 }} />
                <YAxis hide />
                <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid #e2e8f0' }} />
                <Bar dataKey="calls" fill="#0f172a" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </article>
      </div>
    </div>
  );
}

