export function SotbCard({ sotb }: { sotb: { content?: string; path?: string } }) {
  const rawLines = sotb.content
    ? sotb.content.split('\n').filter((line) => line.trim() && !line.startsWith('#'))
    : [];

  const summary = rawLines.slice(0, 4).join(' ');
  const hasMemory = Boolean(summary);
  const sessionCount = rawLines.length;

  return (
    <article className="relative flex flex-col gap-3 rounded-lg bg-surface-container-lowest p-5">
      <header className="flex items-center justify-between gap-3">
        <h3 className="font-headline text-lg text-on-surface">Board Memory</h3>
        <span className="text-[10px] font-medium uppercase tracking-wider text-on-surface-variant">SOTB</span>
      </header>

      {hasMemory ? (
        <div className="relative overflow-hidden">
          <p className="line-clamp-6 font-body text-sm leading-relaxed text-on-surface">{summary}</p>
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-0 h-8 w-full bg-gradient-to-t from-surface-container-lowest to-transparent"
          />
        </div>
      ) : (
        <p className="font-body text-sm italic text-on-surface-variant">No recorded memory yet.</p>
      )}

      <footer className="mt-1 flex flex-wrap gap-2 text-xs text-on-surface-variant">
        <span className="rounded-full bg-surface-container-high px-3 py-1 font-medium">
          Sessions &middot; {sessionCount}
        </span>
        {sotb.path && (
          <span className="truncate rounded-full bg-surface-container-high px-3 py-1 font-medium">
            Source &middot; {sotb.path.split('/').pop()}
          </span>
        )}
      </footer>
    </article>
  );
}
