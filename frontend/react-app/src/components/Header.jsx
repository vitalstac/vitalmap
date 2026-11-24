import { useState } from "react";

export default function Header({ mode, onModeChange }) {
  const [lang, setLang] = useState("DE");

  return (
    <header className="header">
      <div className="brand">
        <span aria-hidden="true">✜</span> <strong>VitalMap</strong>
        <span className="brand-sub">AIHealthMap</span>
      </div>

      <div className="mode-switch" role="tablist" aria-label="Suchmodus">
        <button
          role="tab"
          aria-selected={mode === "assistant"}
          aria-controls="left-panel"
          onClick={() => onModeChange("assistant")}
        >
          KI-Assistent
        </button>
        <button
          role="tab"
          aria-selected={mode === "search"}
          aria-controls="left-panel"
          onClick={() => onModeChange("search")}
        >
          Klassische Suche
        </button>
      </div>

      <div className="header-right">
        <div role="group" aria-label="Sprache" className="lang">
          <button aria-pressed={lang === "DE"} onClick={() => setLang("DE")}>DE</button>
          <span aria-hidden="true">|</span>
          <button aria-pressed={lang === "EN"} onClick={() => setLang("EN")}>EN</button>
        </div>
        <button className="plain">Hilfe ?</button>
      </div>
    </header>
  );
}