export function SotbCard({ sotb }: { sotb: { content?: string; path?: string } }) {
  const summary = sotb.content
    ? sotb.content.split('\n').filter((line) => line.trim() && !line.startsWith('#')).slice(0, 3).join(' ')
    : 'State of the Board memory will load from the local server.';

  return (
    <article className="rounded-lg border border-[#e2e8f0] bg-white p-4 shadow-sm">
      <p className="text-xs font-extrabold uppercase text-[#003d9b]">Board Memory</p>
      <p className="mt-2 line-clamp-5 text-sm leading-relaxed text-[#64748b]">{summary}</p>
    </article>
  );
}

