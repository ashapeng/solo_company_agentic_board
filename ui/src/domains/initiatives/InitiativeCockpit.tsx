import { CheckCircle2, CircleDot, Plus, XCircle } from 'lucide-react';
import type { FounderOutcome, Initiative } from './index';

type InitiativeCockpitProps = {
  initiatives: Initiative[];
  activeInitiativeId: string | null;
  onSelect: (id: string | null) => void;
  onCreateDraft: () => void;
  onActivate: (id: string) => void;
  onClose: (id: string, outcome: FounderOutcome) => void;
};

const outcomeActions: Array<{
  outcome: FounderOutcome;
  label: string;
  icon: typeof CheckCircle2;
}> = [
  { outcome: 'success', label: 'Success', icon: CheckCircle2 },
  { outcome: 'mixed', label: 'Mixed', icon: CircleDot },
  { outcome: 'failure', label: 'Failure', icon: XCircle },
];

export function InitiativeCockpit({
  initiatives,
  activeInitiativeId,
  onSelect,
  onCreateDraft,
  onActivate,
  onClose,
}: InitiativeCockpitProps) {
  const activeInitiative = initiatives.find((initiative) => initiative.id === activeInitiativeId) ?? null;
  const title = activeInitiative?.title || 'Ad hoc board session';
  const isClosed = activeInitiative?.status === 'closed';

  return (
    <section className="initiative-cockpit" aria-label="Initiative cockpit">
      <div className="initiative-cockpit__header">
        <div className="initiative-cockpit__title-block">
          <span className="initiative-cockpit__eyebrow">Initiative</span>
          <h2 className="initiative-cockpit__title">{title}</h2>
        </div>
        <button
          type="button"
          className="initiative-cockpit__icon-button"
          onClick={onCreateDraft}
          aria-label="Create draft initiative"
          title="Create draft initiative"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      <div className="initiative-cockpit__selector" aria-label="Select initiative">
        <button
          type="button"
          className={`initiative-cockpit__selector-button ${activeInitiativeId === null ? 'is-active' : ''}`}
          onClick={() => onSelect(null)}
        >
          Ad hoc
        </button>
        {initiatives.map((initiative) => (
          <button
            key={initiative.id}
            type="button"
            className={`initiative-cockpit__selector-button ${initiative.id === activeInitiativeId ? 'is-active' : ''}`}
            onClick={() => onSelect(initiative.id)}
          >
            {initiative.title}
          </button>
        ))}
      </div>

      {activeInitiative ? (
        <div className="initiative-cockpit__body">
          <div className="initiative-cockpit__meta">
            <span>{activeInitiative.status}</span>
            <span>{activeInitiative.approval_state}</span>
          </div>

          <p className="initiative-cockpit__objective">{activeInitiative.objective}</p>

          {activeInitiative.success_criteria.length > 0 && (
            <ul className="initiative-cockpit__criteria">
              {activeInitiative.success_criteria.map((criterion) => (
                <li key={criterion}>{criterion}</li>
              ))}
            </ul>
          )}

          <div className="initiative-cockpit__actions">
            {activeInitiative.status === 'draft' && (
              <button
                type="button"
                className="initiative-cockpit__action initiative-cockpit__action--primary"
                onClick={() => onActivate(activeInitiative.id)}
              >
                <CircleDot className="h-4 w-4" aria-hidden="true" />
                Activate
              </button>
            )}
            {!isClosed && outcomeActions.map(({ outcome, label, icon: Icon }) => (
              <button
                key={outcome}
                type="button"
                className="initiative-cockpit__action"
                onClick={() => onClose(activeInitiative.id, outcome)}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                Close {label}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <p className="initiative-cockpit__empty">
          This meeting will run without an initiative attachment.
        </p>
      )}
    </section>
  );
}
