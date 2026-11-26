export default function ResultsPanel({ open, onToggle }) {
  return (
    <aside className="results" data-collapsed={!open} aria-label="Ergebnisse">
      <div className="results-head">
        {open && <h2 className="panel-title">Ergebnisse</h2>}
        <button
          className="plain collapse"
          aria-expanded={open}
          aria-label={open ? "Ergebnisse einklappen" : "Ergebnisse ausklappen"}
          onClick={onToggle}
        >
          {open ? "›" : "‹"}
        </button>
      </div>
      {open && <div className="results-body" />}
    </aside>
  );
}