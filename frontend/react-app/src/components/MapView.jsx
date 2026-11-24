import { useState } from "react";
import LayerPanel from "./LayerPanel.jsx";
import Legend from "./Legend.jsx";

export default function MapView() {
  const [year, setYear] = useState(2023);

  return (
    <main className="map" aria-label="Karte">
      <div className="map-art" aria-hidden="true">
        <div className="raster" />
      </div>

      <div className="zoom" role="group" aria-label="Zoom">
        <button aria-label="Vergrößern">+</button>
        <button aria-label="Verkleinern">−</button>
      </div>

      <LayerPanel year={year} onYearChange={setYear} />
      <Legend year={year} />
    </main>
  );
}
