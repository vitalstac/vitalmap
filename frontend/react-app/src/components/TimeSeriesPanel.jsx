import { useState } from "react";

const LINE = "M0 30 L40 26 L80 22 L120 28 L160 18 L200 24 L240 14 L280 22 L320 12 L360 20 L400 16";

export default function TimeSeriesPanel() {
  const [open, setOpen] = useState(true);

  return (
    <section className="series" data-collapsed={!open} aria-label="Zeitreihe">
      <button className="plain series-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span aria-hidden="true">{open ? "▴" : "▾"}</span>{" "}
        <strong>Zeitreihe</strong>{" "}
      </button>
      {open && (
        <svg viewBox="0 0 400 40" preserveAspectRatio="none" role="img" aria-label="Verlauf der Zeitreihe">
        </svg>
      )}
    </section>
  );
}
