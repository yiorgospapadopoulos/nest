import { useId, useState } from "react";
import { questionsOf, type QuestionView } from "../../api/payloads.ts";
import type { Approval } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";

type Answer = string | string[];

function recommended(q: QuestionView): string[] {
  const labels = q.options.filter((o) => o.recommended).map((o) => o.label);
  return q.multiSelect ? labels : labels.slice(0, 1);
}

function answerOf(q: QuestionView, picked: string[], text: string): Answer {
  if (text.trim()) return text.trim();
  return q.multiSelect ? picked : picked.join("");
}

/**
 * The agent's questions with their options; the recommended option starts selected and
 * typed text replaces the choice. Answers go back keyed by question text.
 */
export function QuestionForm({ approval, inline }: { approval: Approval; inline: boolean }) {
  const { actions } = useStore();
  const questions = questionsOf(approval);
  const [answers, setAnswers] = useState<Record<string, Answer>>(() =>
    Object.fromEntries(questions.map((q) => [q.question, answerOf(q, recommended(q), "")])),
  );
  const [busy, setBusy] = useState(false);
  const complete = Object.values(answers).every((a) => a.length > 0);

  const send = async () => {
    setBusy(true);
    if (!(await actions.resolve(approval, { answers }, "Answer sent"))) setBusy(false);
  };

  return (
    <form
      onSubmit={(event) => {
        // The send button, and so submitting, is disabled until every question has an answer.
        event.preventDefault();
        void send();
      }}
    >
      {questions.map((q) => (
        <QuestionField
          key={q.question}
          question={q}
          inline={inline}
          onAnswer={(answer) => {
            setAnswers((current) => ({ ...current, [q.question]: answer }));
          }}
        />
      ))}
      <div className="acts">
        <button className="b b-pri" type="submit" disabled={!complete || busy}>
          Send answer
        </button>
      </div>
    </form>
  );
}

function QuestionField({
  question: q,
  inline,
  onAnswer,
}: {
  question: QuestionView;
  inline: boolean;
  onAnswer: (answer: Answer) => void;
}) {
  const id = useId();
  const [picked, setPicked] = useState(() => recommended(q));
  const [text, setText] = useState("");

  const choose = (label: string) => {
    const next = !q.multiSelect
      ? [label]
      : picked.includes(label)
        ? picked.filter((l) => l !== label)
        : [...picked, label];
    setPicked(next);
    onAnswer(answerOf(q, next, text));
  };

  return (
    <fieldset className="qset">
      <legend className={inline ? "ask-q" : "cq"}>{q.question}</legend>
      <div role={q.multiSelect ? "group" : "radiogroup"} aria-label={q.question}>
        {q.options.map((o) => (
          <button
            type="button"
            key={o.label}
            className="ropt"
            role={q.multiSelect ? "checkbox" : "radio"}
            aria-checked={picked.includes(o.label)}
            onClick={() => {
              choose(o.label);
            }}
          >
            <span className="rdo" aria-hidden="true" />
            <span>
              <b>
                {o.label}
                {o.recommended && <span className="rec">Recommended</span>}
              </b>
              {o.description !== null && <small>{o.description}</small>}
            </span>
          </button>
        ))}
      </div>
      <label className="sr" htmlFor={id}>
        Your own answer
      </label>
      <input
        id={id}
        className="fin"
        placeholder="Your own answer"
        autoComplete="off"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          onAnswer(answerOf(q, picked, event.target.value));
        }}
      />
    </fieldset>
  );
}
