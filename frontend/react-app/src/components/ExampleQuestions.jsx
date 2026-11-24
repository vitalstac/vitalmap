import { exampleQuestions } from "../data/mock.js";

export default function ExampleQuestions({ onPick }) {
  return (
    <div className="examples">
      <h3>Beispielfragen</h3>
      <ul>
        {exampleQuestions.map((q) => (
          <li key={q}>
            <button className="chip" onClick={() => onPick(q)}>{q}</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
