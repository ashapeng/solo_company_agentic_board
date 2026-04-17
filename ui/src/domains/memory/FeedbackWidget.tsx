import { useState } from 'react';
import { submitFeedback } from '../../shared/api';

export function FeedbackWidget({ sessionId }: { sessionId?: string }) {
  const [rating, setRating] = useState<string | null>(null);
  const [note, setNote] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState('');

  if (!sessionId) return null;

  async function submit(selectedRating: string) {
    setRating(selectedRating);
    setError('');
    try {
      await submitFeedback(sessionId, selectedRating, note || undefined);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error.');
    }
  }

  if (submitted) {
    return (
      <div className="mt-4 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-3 text-sm font-bold text-[#2d8a52]">
        Feedback recorded: {rating}
      </div>
    );
  }

  return (
    <div className="mt-4 flex flex-wrap items-center gap-2 rounded-lg border border-[#e2e8f0] bg-[#f8fafc] p-3">
      <span className="text-sm font-bold text-[#475569]">Rate this decision</span>
      <button type="button" onClick={() => submit('positive')} className="rounded-lg border border-[#cbd5e1] bg-white px-3 py-2 text-sm font-bold text-[#003d9b] hover:border-[#003d9b]">
        Good
      </button>
      <button type="button" onClick={() => submit('negative')} className="rounded-lg border border-[#cbd5e1] bg-white px-3 py-2 text-sm font-bold text-[#b42318] hover:border-[#b42318]">
        Needs work
      </button>
      <input
        className="min-h-10 min-w-48 flex-1 rounded-lg border border-[#cbd5e1] bg-white px-3 text-sm text-[#0f172a] outline-none focus:border-[#003d9b]"
        type="text"
        placeholder="What could be better?"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        maxLength={500}
      />
      {error && <span className="text-sm font-semibold text-[#b42318]">{error}</span>}
    </div>
  );
}
