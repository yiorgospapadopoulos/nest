import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useStore } from "../../store/context.ts";
import { Button } from "../ui/controls.tsx";
import { useOverlay, useRestoreFocus } from "../ui/floating.ts";
import { promptStart, promptWords, type TeamPrompt } from "./words.ts";

/**
 * New team or Change handle, as the Mac's PixiePromptSheet: one field starting with what
 * is there, selected, so typing replaces it. Return answers, Escape or a press outside
 * cancels; an empty answer changes nothing.
 */
export function PromptSheet({ prompt, onClose }: { prompt: TeamPrompt; onClose: () => void }) {
  const { state, actions } = useStore();
  const words = promptWords(prompt);
  const [text, setText] = useState(() => promptStart(prompt, state.teams));
  const field = useRef<HTMLInputElement>(null);
  useRestoreFocus();
  useOverlay(onClose);
  useLayoutEffect(() => {
    field.current?.focus({ preventScroll: true });
    field.current?.select();
  }, []);

  const answer = () => {
    onClose();
    const value = text.trim();
    if (value === "") return;
    if (prompt.kind === "new") void actions.createTeam(value);
    else if (prompt.kind === "rename") void actions.updateTeam(prompt.team, { name: value });
    else void actions.updateTeam(prompt.team, { handle: value });
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    } else if (event.key === "Enter" && event.target === field.current) {
      event.preventDefault();
      answer();
    }
  };

  return createPortal(
    <div
      className="px-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="px-prompt"
        role="dialog"
        aria-modal="true"
        aria-label={words.title}
        onKeyDown={onKeyDown}
      >
        <h2>{words.title}</h2>
        <input
          ref={field}
          className="px-prompt-field"
          aria-label={words.field}
          placeholder={words.field}
          spellCheck={false}
          autoComplete="off"
          value={text}
          onChange={(event) => {
            setText(event.target.value);
          }}
        />
        {words.note !== null && <p className="px-prompt-note">{words.note}</p>}
        <div className="px-prompt-b">
          <Button kind="soft" onClick={onClose}>
            Cancel
          </Button>
          <Button kind="primary" onClick={answer}>
            {words.action}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
