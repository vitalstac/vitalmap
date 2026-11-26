import { useState } from "react";
import Header from "./components/Header.jsx";
import ChatPanel from "./components/ChatPanel.jsx";
import SearchPanel from "./components/SearchPanel.jsx";
import MapView from "./components/MapView.jsx";
import TimeSeriesPanel from "./components/TimeSeriesPanel.jsx";
import ResultsPanel from "./components/ResultsPanel.jsx";

export default function App() {
  const [mode, setMode] = useState("assistant"); 
  const [resultsOpen, setResultsOpen] = useState(true);

  return (
    <div className="app" data-results={resultsOpen ? "open" : "closed"}>
      <Header mode={mode} onModeChange={setMode} />

      <div className="area-left" id="left-panel" role="tabpanel">
        {mode === "assistant" ? <ChatPanel /> : <SearchPanel />}
      </div>

      <MapView />
      <TimeSeriesPanel />

      <ResultsPanel open={resultsOpen} onToggle={() => setResultsOpen((v) => !v)} />
    </div>
  );
}