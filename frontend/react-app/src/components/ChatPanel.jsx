import { useState } from "react"
import ExampleQuestions from "./ExampleQuestions.jsx";
import { initialMessages } from "../data/mock.js";

export default function ChatPanel() {
  const [messages, setMessages] = useState(initialMessages);
  const [input, setInput] = useState("");

  function send(e) {
    e.preventDefault();
    const text = input.trim();
    if (!text) return;
    setMessages((m) => [...m, { id: Date.now(), role: "user", text }]);
    setInput("");
  }

  return (
    <section className="panel" aria-labelledby="chat-title">
      <h2 id="chat-title" className="panel-title">KI-Assistent</h2>

      <div className="chat-scroll" aria-live="polite">
      {messages.map((m) => (
  <div key={m.id} className="bubble-user">{m.text}</div>
  ))}

        <ExampleQuestions onPick={setInput} />
      </div>

      <form className="chat-input" onSubmit={send}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Frage stellen …"
          aria-label="Frage stellen"
        />
        <button type="submit" className="btn">Senden</button>
      </form>
    </section>
  );
}
