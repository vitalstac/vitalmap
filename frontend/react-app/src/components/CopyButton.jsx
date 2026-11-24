import { useState } from "react";

export default function CopyButton({ text }) {
  const [done, setDone] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } catch {
    }
  }

  return (
    <button className="link-btn" onClick={copy}>
      <span aria-hidden="true">⧉</span> {done ? "kopiert" : "kopieren"}
    </button>
  );
}