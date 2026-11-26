import { useState } from "react";
import StacRequest from "./StacRequest.jsx";
import { BBOX } from "../data/mock.js";

const INITIAL = {
  q: " ",
  from: "2020-01-01",
  to: "2023-12-31",
  space: "view", 
  status: { abgeschlossen: false, laufend: false },
  type: { Raster: false, Vektor: false, Zeitreihe: false },
  update: "alle",
  format: "alle",
};

function buildRequest(s) {
  const bbox = s.space === "view" ? `&bbox=${BBOX}` : "";
  return `platzhalter`;
}

export default function SearchPanel() {
  const [s, setS] = useState(INITIAL);
  const set = (patch) => setS((v) => ({ ...v, ...patch }));
  const toggle = (group, key) => set({ [group]: { ...s[group], [key]: !s[group][key] } });

  return (
    <section className="panel" aria-labelledby="search-title">
      <h2 id="search-title" className="panel-title">Klassische Suche (ohne KI)</h2>

      <form className="search-form" onSubmit={(e) => e.preventDefault()}>
        <label className="field">
          Freitext
          <input type="search" value={s.q} onChange={(e) => set({ q: e.target.value })} />
        </label>

        <div className="field">
          Zeitraum
          <div className="range">
            <input type="date" aria-label="Von" value={s.from} onChange={(e) => set({ from: e.target.value })} />
            <span aria-hidden="true">–</span>
            <input type="date" aria-label="Bis" value={s.to} onChange={(e) => set({ to: e.target.value })} />
          </div>
        </div>

        <fieldset className="field">
          <legend>Raum</legend>
          <label className="inline">
            <input type="radio" name="space" checked={s.space === "view"} onChange={() => set({ space: "view" })} />
            aktueller Kartenausschnitt
          </label>
          <label className="inline">
            <input type="radio" name="space" checked={s.space === "draw"} onChange={() => set({ space: "draw" })} />
            Rechteck auf der Karte zeichnen
          </label>
        </fieldset>

        <fieldset className="facets">
          <legend>Facetten <span className="muted">(Bonus, Health-Felder)</span></legend>
          <div className="facet-row">
            Status:
            {Object.keys(s.status).map((k) => (
              <label key={k} className="inline">
                <input type="checkbox" checked={s.status[k]} onChange={() => toggle("status", k)} /> {k}
              </label>
            ))}
          </div>
          <div className="facet-row">
            Repräsentation:
            {Object.keys(s.type).map((k) => (
              <label key={k} className="inline">
                <input type="checkbox" checked={s.type[k]} onChange={() => toggle("type", k)} /> {k}
              </label>
            ))}
          </div>
          <div className="facet-row">
            <label className="inline">
              Aktualisierung:
              <select value={s.update} onChange={(e) => set({ update: e.target.value })}>
                <option>alle</option><option>jährlich</option><option>täglich</option>
              </select>
            </label>
            <label className="inline">
              Format:
              <select value={s.format} onChange={(e) => set({ format: e.target.value })}>
                <option>alle</option><option>COG</option><option>GeoJSON</option>
              </select>
            </label>
          </div>
        </fieldset>

        <div className="search-actions">
          <button type="submit" className="btn">Suchen</button>
          <button type="button" className="plain muted" onClick={() => setS(INITIAL)}>Filter zurücksetzen</button>
        </div>
      </form>

      <StacRequest label="Ausgeführte Anfrage" request={buildRequest(s)} rawHref="#" defaultOpen />
    </section>
  );
}
