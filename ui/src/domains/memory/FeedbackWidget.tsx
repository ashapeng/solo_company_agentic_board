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
      <div className="mt-4 flex items-center gap-3 rounded-lg bg-surface-container-lowest p-4 text-sm font-body text-on-surface">
        <span className="text-xs font-medium uppercase tracking-wider text-primary-fixed-dim">Recorded</span>
        <span className="text-on-surface-variant">Feedback captured &middot; {rating}</span>
      </div>
    );
  }

  return (
    <div className="mt-4 flex flex-col gap-3 rounded-lg bg-surface-container-lowest p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="font-headline text-base text-on-surface">Rate this decision</p>
        <span className="text-[10px] font-medium uppercase tracking-wider text-on-surface-variant">
          Board review
        </span>
      </div>

      <textarea
        className="min-h-[72px] w-full resize-y rounded-lg bg-surface-container-highest px-3 py-2 text-sm text-on-surface font-body placeholder:text-on-surface-variant/70 focus:outline-none focus:border-b-2 focus:border-b-secondary-container"
        placeholder="What could be better?"
        value={note}
        onChange={(event) => setNote(event.target.value)}
        maxLength={500}
      />

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => submit('positive')}
          className="metallic-gradient rounded-lg px-4 py-2 text-sm font-body font-semibold text-on-primary transition-transform hover:scale-[1.02]"
        >
          Good
        </button>
        <button
          type="button"
          onClick={() => submit('negative')}
          className="rounded-lg bg-surface-container-high px-4 py-2 text-sm font-body font-semibold text-on-surface-variant transition-colors hover:bg-surface-container-highest hover:text-on-surface"
        >
          Needs work
        </button>
        {error && (
          <span className="text-sm font-medium text-error">{error}</span>
        )}
      </div>
    </div>
  );
}
