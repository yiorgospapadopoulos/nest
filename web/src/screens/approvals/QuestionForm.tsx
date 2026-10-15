import { useState } from "react";
import { questionsOf, type QuestionView } from "../../api/payloads.ts";
import type { Approval } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";

type Answer = string | string[];

function recommended(q: QuestionView): string[] {
  const labels = q.options.filter((o) => o.recommended).map((o) => o.label);
  return q.multiSelect ? labels : labels.slice(0, 1);
}

/**
 * The answer to send; `other` is Other's text, or null while Other is not chosen. Other
 * chosen with no text is no answer yet, so the question stays unanswered.
 */
function answerOf(q: QuestionView, picked: string[], other: string | null): Answer {
  if (other === null) return q.multiSelect ? picked : picked.join("");
  const typed = other.trim();
  if (!q.multiSelect) return typed;
  return typed ? [...picked, typed] : [];
}

/**
 * The agent's questions with their options and a last one, Other, that takes typed text;
 * the recommended option starts selected. Answers go back keyed by question text.
 */
export function QuestionForm({ approval, inline }: { approval: Approval; inline: boolean }) {
  const { actions } = useStore();
  const questions = questionsOf(approval);
  const [answers, setAnswers] = useState<Record<string, Answer>>(() =>
    Object.fromEntries(questions.map((q) => [q.question, answerOf(q, recommended(q), null)])),
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
  const [picked, setPicked] = useState(() => recommended(q));
  // Other's text, or null while Other is not chosen.
  const [other, setOther] = useState<string | null>(null);
  const role = q.multiSelect ? "checkbox" : "radio";

  const update = (nextPicked: string[], nextOther: string | null) => {
    setPicked(nextPicked);
    setOther(nextOther);
    onAnswer(answerOf(q, nextPicked, nextOther));
  };

  // A single choice is one of the options or Other; several keep Other apart.
  const choose = (label: string) => {
    if (!q.multiSelect) update([label], null);
    else
      update(
        picked.includes(label) ? picked.filter((l) => l !== label) : [...picked, label],
        other,
      );
  };
  const toggleOther = () => {
    if (!q.multiSelect) update([], other ?? "");
    else update(picked, other === null ? "" : null);
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
            role={role}
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
        <button
          type="button"
          className="ropt"
          role={role}
          aria-checked={other !== null}
          onClick={toggleOther}
        >
          <span className="rdo" aria-hidden="true" />
          <span>
            <b>Other</b>
          </span>
        </button>
      </div>
      {other !== null && (
        <input
          className="fin"
          aria-label="Your answer"
          placeholder="Type your answer"
          autoComplete="off"
          autoFocus
          value={other}
          onChange={(event) => {
            update(picked, event.target.value);
          }}
        />
      )}
    </fieldset>
  );
}
