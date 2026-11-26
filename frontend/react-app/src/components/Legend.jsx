export default function Legend({ year }) {
  return (
    <section className="legend float" aria-labelledby="legend-title">
      <h3 id="legend-title">Jahresmittel beispiel {year}</h3>
      <p>Einheit: µg/m³</p>
      <div className="legend-bar" role="img" aria-label="Farbskala von 0 bis 25 oder mehr µg/m³" />
      <div className="legend-scale"><span>0</span><span>12,5</span><span>≥ 25</span></div>
      <p className="muted">Farbskala: cividis (farbenblindgeeignet)<br />Quelle: 0</p>
    </section>
  );
}
