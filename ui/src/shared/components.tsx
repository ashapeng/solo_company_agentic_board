import type { ReactNode } from 'react';
import { compactList, humanize } from './presentation';

export function PanelHeading({ icon, kicker, title }: { icon: ReactNode; kicker: string; title: string }) {
  return (
    <div>
      <p className="flex items-center gap-2 text-xs font-extrabold uppercase text-[#003d9b]">
        {icon}
        {kicker}
      </p>
      <h2 className="mt-1 text-2xl font-extrabold leading-tight text-[#0f172a]">{title}</h2>
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-headline text-sm font-extrabold uppercase tracking-[0.22em] text-on-surface-variant">
      {children}
    </h2>
  );
}

export function MaterialCard({ icon, title, subtitle }: { icon: ReactNode; title: string; subtitle: string }) {
  return (
    <article className="flex items-center rounded-lg bg-surface-container-highest p-3 transition-colors hover:bg-surface-container-high">
      <span className="mr-3 text-primary">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-extrabold text-on-surface">{title}</p>
        <p className="truncate text-xs font-semibold text-on-surface-variant">{subtitle}</p>
      </div>
    </article>
  );
}

export function PlainList({ items }: { items?: string[] | string | null }) {
  if (!items) return null;
  const values = Array.isArray(items) ? items : [items];
  if (!values.length) return null;
  return (
    <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-relaxed text-[#64748b]">
      {values.map((item, index) => <li key={`${item}-${index}`}>{String(item)}</li>)}
    </ul>
  );
}

export function StageIndicator({ active, done }: { active?: boolean; done?: boolean }) {
  return (
    <span
      className={`h-3 w-3 rounded-lg border ${
        done ? 'border-[#2d8a52] bg-[#2d8a52]' : active ? 'border-[#003d9b] bg-[#003d9b]' : 'border-[#aebbb3] bg-white'
      }`}
    />
  );
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="mt-4 rounded-lg border border-[#f0c8c2] bg-[#fff5f2] p-4 text-sm font-semibold text-[#b42318]">
      {message}
    </div>
  );
}

export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3 grid gap-1 border-t border-[#e2e8f0] pt-3 first:mt-0 first:border-t-0 first:pt-0">
      <dt className="text-xs font-extrabold uppercase text-[#003d9b]">{label}</dt>
      <dd className="text-sm leading-relaxed text-[#475569]">{value}</dd>
    </div>
  );
}

export function TagRow({ title, items }: { title: string; items: string[] }) {
  const values = compactList(items).slice(0, 6);
  if (!values.length) return null;
  return (
    <div className="mt-5">
      <p className="mb-2 text-xs font-extrabold uppercase text-[#003d9b]">{title}</p>
      <div className="flex flex-wrap gap-2">
        {values.map((item) => (
          <span key={item} className="rounded-lg border border-[#e2e8f0] bg-[#f8fafc] px-2 py-1 text-xs font-bold text-[#475569]">
            {humanize(item)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function MetricCard({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-sm font-extrabold uppercase text-[#64748b]">{label}</p>
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-[#eff6ff] text-[#003d9b]">{icon}</div>
      </div>
      <p className="text-4xl font-extrabold text-[#0f172a]">{value}</p>
      <p className="mt-3 text-sm font-semibold text-[#64748b]">{detail}</p>
    </article>
  );
}

