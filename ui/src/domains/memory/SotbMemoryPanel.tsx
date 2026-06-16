import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { AlertTriangle, History, ListTree, Loader2, RefreshCw, RotateCcw } from 'lucide-react';
import {
  consolidateMemory,
  getSotbEntries,
  getSotbSnapshots,
  rollbackSnapshot,
} from '../../shared/api';
import type {
  ConsolidationResult,
  RollbackResult,
  SotbEntry,
  SotbSnapshot,
} from '../../shared/types';

const LOW_CONFIDENCE = 0.5;

type AuditTab = 'entries' | 'snapshots';

function isExpired(entry: SotbEntry): boolean {
  if (!entry.expires_at) return false;
  const ts = Date.parse(entry.expires_at);
  return Number.isFinite(ts) && ts < Date.now();
}

function formatTimestamp(value?: string | null): string {
  if (!value) return '—';
  const ts = Date.parse(value);
  if (!Number.isFinite(ts)) return value;
  return new Date(ts).toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

function groupBySection(entries: SotbEntry[]): Array<[string, SotbEntry[]]> {
  const map = new Map<string, SotbEntry[]>();
  for (const entry of entries) {
    const key = entry.section || 'Uncategorized';
    const list = map.get(key) ?? [];
    list.push(entry);
    map.set(key, list);
  }
  return [...map.entries()];
}

export function SotbMemoryPanel({ ventureId = 'default' }: { ventureId?: string }) {
  const [tab, setTab] = useState<AuditTab>('entries');
  const [entries, setEntries] = useState<SotbEntry[]>([]);
  const [snapshots, setSnapshots] = useState<SotbSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [busy, setBusy] = useState(false);
  const [pendingRollback, setPendingRollback] = useState<string | null>(null);
  const [actionNote, setActionNote] = useState<string>('');
  const [consolidation, setConsolidation] = useState<ConsolidationResult | null>(null);

  async function refresh() {
    setLoading(true);
    setError('');
    try {
      const [nextEntries, nextSnapshots] = await Promise.all([
        getSotbEntries(ventureId),
        getSotbSnapshots(ventureId),
      ]);
      setEntries(nextEntries);
      setSnapshots(nextSnapshots);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load memory audit.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ventureId]);

  async function handleRollback(snapshotId: string) {
    setBusy(true);
    setActionNote('');
    setError('');
    try {
      const result: RollbackResult = await rollbackSnapshot(snapshotId);
      setActionNote(
        result.manual_edits_since
          ? `Restored snapshot — warning: manual edits were made since this snapshot and have been overwritten (${result.restored_index_rows ?? 0} entries restored).`
          : `Restored snapshot — ${result.restored_index_rows ?? 0} entries restored.`,
      );
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Rollback failed.');
    } finally {
      setBusy(false);
      setPendingRollback(null);
    }
  }

  async function handleConsolidate() {
    setBusy(true);
    setActionNote('');
    setError('');
    setConsolidation(null);
    try {
      const result = await consolidateMemory(ventureId);
      setConsolidation(result);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Consolidation failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="flex flex-col gap-4 rounded-lg bg-surface-container-lowest p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-headline text-lg text-on-surface">Memory Audit</h3>
          <p className="text-[10px] font-medium uppercase tracking-wider text-on-surface-variant">
            White-box &middot; venture {ventureId}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || busy}
            className="flex items-center gap-1.5 rounded-full bg-surface-container-high px-3 py-1.5 text-xs font-medium text-on-surface-variant transition-colors hover:bg-surface-container-highest hover:text-on-surface disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label="Refresh memory audit"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void handleConsolidate()}
            disabled={busy || loading}
            className="metallic-gradient flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold text-on-primary transition-transform hover:scale-[1.02] disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
            aria-label="Consolidate memory"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <ListTree className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            Consolidate
          </button>
        </div>
      </header>

      <div className="flex gap-1 rounded-lg bg-surface-container-high p-1">
        <TabButton active={tab === 'entries'} onClick={() => setTab('entries')} icon={<ListTree className="h-3.5 w-3.5" aria-hidden="true" />}>
          Entries{entries.length ? ` (${entries.length})` : ''}
        </TabButton>
        <TabButton active={tab === 'snapshots'} onClick={() => setTab('snapshots')} icon={<History className="h-3.5 w-3.5" aria-hidden="true" />}>
          Snapshots{snapshots.length ? ` (${snapshots.length})` : ''}
        </TabButton>
      </div>

      {consolidation && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-surface-container-high px-3 py-2 text-xs font-body text-on-surface">
          <span className="font-semibold text-primary">Consolidated</span>
          <CountChip label="merged" value={consolidation.merged} />
          <CountChip label="superseded" value={consolidation.superseded} />
          <CountChip label="expired" value={consolidation.expired} />
          <CountChip label="kept" value={consolidation.kept} />
        </div>
      )}

      {actionNote && (
        <div className="rounded-lg bg-surface-container-high px-3 py-2 text-xs font-body text-on-surface">
          {actionNote}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-lg bg-error-container px-3 py-2 text-xs font-medium text-error">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 py-6 text-sm text-on-surface-variant">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Loading memory audit…
        </div>
      ) : tab === 'entries' ? (
        <EntriesView entries={entries} />
      ) : (
        <SnapshotsView
          snapshots={snapshots}
          busy={busy}
          pendingRollback={pendingRollback}
          onRequestRollback={setPendingRollback}
          onConfirmRollback={handleRollback}
          onCancelRollback={() => setPendingRollback(null)}
        />
      )}
    </article>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-body font-semibold transition-colors ${
        active
          ? 'bg-surface-container-lowest text-on-surface'
          : 'text-on-surface-variant hover:text-on-surface'
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

function CountChip({ label, value }: { label: string; value: number }) {
  return (
    <span className="rounded-full bg-surface-container-lowest px-2.5 py-0.5 font-medium text-on-surface-variant">
      {value} {label}
    </span>
  );
}

function EntriesView({ entries }: { entries: SotbEntry[] }) {
  if (entries.length === 0) {
    return <p className="py-6 text-sm italic text-on-surface-variant">No reconciled memory entries yet.</p>;
  }

  const groups = groupBySection(entries);

  return (
    <div className="flex flex-col gap-5">
      {groups.map(([section, sectionEntries]) => (
        <section key={section} className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-primary">{section}</h4>
          <ul className="flex flex-col gap-2">
            {sectionEntries.map((entry) => (
              <EntryRow key={entry.entry_id} entry={entry} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function EntryRow({ entry }: { entry: SotbEntry }) {
  const expired = isExpired(entry);
  const lowConfidence = entry.confidence < LOW_CONFIDENCE;
  const sessionId = entry.provenance?.session_id;
  const sourceMember = entry.provenance?.source_member;

  return (
    <li
      className={`flex flex-col gap-2 rounded-lg bg-surface-container-lowest p-3 ${
        expired ? 'accent-bar-left ring-1 ring-error/30' : ''
      }`}
    >
      <p className="font-body text-sm leading-relaxed text-on-surface">{entry.text}</p>
      <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-body">
        <span
          className={`rounded-full px-2 py-0.5 font-medium ${
            lowConfidence
              ? 'bg-error-container text-error'
              : 'bg-surface-container-high text-on-surface-variant'
          }`}
          title="Author/section confidence"
        >
          confidence {entry.confidence.toFixed(2)}
          {lowConfidence ? ' · low' : ''}
        </span>
        {entry.expires_at && (
          <span
            className={`rounded-full px-2 py-0.5 font-medium ${
              expired ? 'bg-error-container text-error' : 'bg-surface-container-high text-on-surface-variant'
            }`}
            title="Expiry"
          >
            {expired ? 'expired' : 'expires'} {formatTimestamp(entry.expires_at)}
          </span>
        )}
        {sessionId && (
          <span className="rounded-full bg-surface-container-high px-2 py-0.5 font-medium text-on-surface-variant">
            session · {sessionId}
          </span>
        )}
        {sourceMember && (
          <span className="rounded-full bg-surface-container-high px-2 py-0.5 font-medium text-on-surface-variant">
            source · {sourceMember}
          </span>
        )}
        <span className="rounded-full bg-surface-container-high px-2 py-0.5 font-mono text-on-surface-variant/70">
          {entry.entry_id}
        </span>
      </div>
    </li>
  );
}

function SnapshotsView({
  snapshots,
  busy,
  pendingRollback,
  onRequestRollback,
  onConfirmRollback,
  onCancelRollback,
}: {
  snapshots: SotbSnapshot[];
  busy: boolean;
  pendingRollback: string | null;
  onRequestRollback: (id: string) => void;
  onConfirmRollback: (id: string) => void;
  onCancelRollback: () => void;
}) {
  if (snapshots.length === 0) {
    return <p className="py-6 text-sm italic text-on-surface-variant">No snapshots recorded yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {snapshots.map((snapshot) => {
        const confirming = pendingRollback === snapshot.snapshot_id;
        return (
          <li
            key={snapshot.snapshot_id}
            className="flex flex-col gap-2 rounded-lg bg-surface-container-lowest p-3"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex flex-col gap-1">
                <p className="truncate font-body text-sm font-medium text-on-surface">{snapshot.reason}</p>
                <div className="flex flex-wrap items-center gap-1.5 text-[10px] font-body text-on-surface-variant">
                  <span>{formatTimestamp(snapshot.created_at)}</span>
                  {snapshot.session_id && <span>· session {snapshot.session_id}</span>}
                  <span className="font-mono text-on-surface-variant/70">· {snapshot.snapshot_id.slice(0, 8)}</span>
                </div>
              </div>
              {confirming ? (
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => onConfirmRollback(snapshot.snapshot_id)}
                    disabled={busy}
                    className="flex items-center gap-1 rounded-full bg-error-container px-3 py-1.5 text-xs font-semibold text-error transition-colors hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
                    aria-label="Confirm rollback to this snapshot"
                  >
                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
                    Confirm
                  </button>
                  <button
                    type="button"
                    onClick={onCancelRollback}
                    disabled={busy}
                    className="rounded-full bg-surface-container-high px-3 py-1.5 text-xs font-medium text-on-surface-variant transition-colors hover:bg-surface-container-highest disabled:opacity-40 disabled:cursor-not-allowed"
                    aria-label="Cancel rollback"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => onRequestRollback(snapshot.snapshot_id)}
                  disabled={busy || !snapshot.has_payload}
                  className="flex shrink-0 items-center gap-1.5 rounded-full bg-surface-container-high px-3 py-1.5 text-xs font-medium text-on-surface-variant transition-colors hover:bg-surface-container-highest hover:text-on-surface disabled:opacity-40 disabled:cursor-not-allowed"
                  aria-label={`Roll back to snapshot from ${formatTimestamp(snapshot.created_at)}`}
                  title={snapshot.has_payload ? 'Roll back to this snapshot' : 'No payload stored for this snapshot'}
                >
                  <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
                  Rollback
                </button>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
