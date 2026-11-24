import { useState } from "react";

const MIN_YEAR = 2020;
const MAX_YEAR = 2023;

export default function LayerPanel({ year, onYearChange }) {
  const [pm25, setPm25] = useState(true);
  const [hospitals, setHospitals] = useState(false);
  const [opacity, setOpacity] = useState(70);

  return (
    <section className="layers float" aria-labelledby="layers-title">
      <h3 id="layers-title">Ebenen</h3>

      <label className="inline">
        <input type="checkbox" checked={pm25} onChange={(e) => setPm25(e.target.checked)} />
       Jahresmittel beispiel {year}
      </label>

      <label className="opacity">
        Deckkraft
        <input
          type="range" min="0" max="100" value={opacity}
          onChange={(e) => setOpacity(Number(e.target.value))}
        />
      </label>

      <label className="inline">
        <input type="checkbox" checked={hospitals} onChange={(e) => setHospitals(e.target.checked)} />
        Krankenhäuser beispiel
      </label>

      <div className="year" role="group" aria-label="Jahr">
        Jahr:
        <button aria-label="Vorheriges Jahr" disabled={year <= MIN_YEAR} onClick={() => onYearChange(year - 1)}>‹</button>
        <strong>{year}</strong>
        <button aria-label="Nächstes Jahr" disabled={year >= MAX_YEAR} onClick={() => onYearChange(year + 1)}>›</button>
      </div>
    </section>
  );
}
