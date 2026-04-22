import type { ReactNode } from 'react';
import { compactList, humanize } from './presentation';

export function PanelHeading({ icon, kicker, title }: { icon: ReactNode; kicker: string; title: string }) {
  return (
    <div>
      <p className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-on-surface-variant">
        <span className="text-primary">{icon}</span>
        {kicker}
      </p>
      <h2 className="mt-2 font-headline text-2xl font-bold leading-tight tracking-tight text-on-surface">{title}</h2>
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h2 className="font-headline text-lg font-bold tracking-tight text-on-surface">
      {children}
    </h2>
  );
}

export function MaterialCard({ icon, title, subtitle }: { icon: ReactNode; title: string; subtitle: string }) {
  return (
    <article className="flex items-center rounded-lg bg-surface-container-lowest p-4 transition-colors hover:bg-surface-container-low">
      <span className="mr-3 text-on-surface-variant">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-semibold text-on-surface">{title}</p>
        <p className="truncate text-xs font-medium text-on-surface-variant">{subtitle}</p>
      </div>
    </article>
  );
}

export function PlainList({ items }: { items?: string[] | string | null }) {
  if (!items) return null;
  const values = Array.isArray(items) ? items : [items];
  if (!values.length) return null;
  return (
    <ul className="mt-3 space-y-2 pl-1 text-sm leading-relaxed text-on-surface">
      {values.map((item, index) => (
        <li key={`${item}-${index}`} className="flex gap-2">
          <span aria-hidden="true" className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-primary" />
          <span className="min-w-0 flex-1">{String(item)}</span>
        </li>
      ))}
    </ul>
  );
}

export function StageIndicator({ active, done }: { active?: boolean; done?: boolean }) {
  const color = done
    ? 'bg-primary'
    : active
    ? 'bg-secondary-container animate-pulse'
    : 'bg-surface-container-highest';
  return <span className={`h-2.5 w-2.5 rounded-full ${color}`} />;
}

export function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="mt-4 rounded-lg bg-error-container/15 p-4 text-sm font-medium text-error">
      {message}
    </div>
  );
}

export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="mt-3 grid gap-1 first:mt-0">
      <dt className="text-xs font-medium text-on-surface-variant">{label}</dt>
      <dd className="text-sm font-medium leading-relaxed text-on-surface">{value}</dd>
    </div>
  );
}

export function TagRow({ title, items }: { title: string; items: string[] }) {
  const values = compactList(items).slice(0, 6);
  if (!values.length) return null;
  return (
    <div className="mt-5">
      <p className="mb-2 text-xs font-medium uppercase tracking-wider text-on-surface-variant">{title}</p>
      <div className="flex flex-wrap gap-2">
        {values.map((item) => (
          <span
            key={item}
            className="rounded-full bg-surface-container-high px-3 py-1 text-xs font-medium text-on-surface-variant"
          >
            {humanize(item)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function MetricCard({ icon, label, value, detail }: { icon: ReactNode; label: string; value: string; detail: string }) {
  return (
    <article className="rounded-lg bg-surface-container-lowest p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-xs font-medium uppercase tracking-wider text-on-surface-variant">{label}</p>
        <div className="grid h-10 w-10 place-items-center rounded-lg bg-surface-container-high text-primary">{icon}</div>
      </div>
      <p className="font-headline text-3xl font-bold leading-tight tracking-tight text-on-surface">{value}</p>
      <p className="mt-3 text-xs font-medium text-on-surface-variant">{detail}</p>
    </article>
  );
}
