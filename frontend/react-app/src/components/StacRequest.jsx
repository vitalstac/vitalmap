import { useState } from "react";
import CopyButton from "./CopyButton.jsx";

export default function StacRequest({ label = "Ausgeführte STAC-Abfrage", request, rawHref, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="stac">
      <div className="stac-head">
        <button className="plain" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          <span aria-hidden="true">{open ? "▾" : "▸"}</span> {label}
        </button>
        <span className="stac-actions">
          <CopyButton text={request} />
          {rawHref && (
            <>
              <span aria-hidden="true"> · </span>
              <a className="link-btn" href={rawHref}>Rohantwort ↗</a>
            </>
          )}
        </span>
      </div>
      {open && <code className="stac-code">{request}</code>}
    </div>
  );
}