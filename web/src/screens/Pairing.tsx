import { useState, type SyntheticEvent } from "react";
import { useStore } from "../store/context.ts";

// Pairing codes use an alphabet without look-alikes (no 0, O, 1, I, L).
const CODE_LENGTH = 8;
const NOT_IN_CODES = /[^A-HJKMNP-Z2-9]/g;

function normalizeCode(text: string): string {
  return text.toUpperCase().replace(NOT_IN_CODES, "").slice(0, CODE_LENGTH);
}

export function Pairing() {
  const { actions } = useStore();
  const [code, setCode] = useState("");
  const [name, setName] = useState("iPhone");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ready = code.length === CODE_LENGTH && name.trim() !== "" && !busy;

  const submit = async (event: SyntheticEvent) => {
    // The Pair button, and so submitting, is disabled until the form is ready.
    event.preventDefault();
    setBusy(true);
    setError(null);
    const failure = await actions.pair(code, name.trim());
    if (failure !== null) {
      setError(failure);
      setBusy(false);
    }
  };

  return (
    <main className="center">
      <form className="pair gl" onSubmit={(e) => void submit(e)} aria-labelledby="pair-title">
        <h1 id="pair-title">Pair this iPhone</h1>
        <p>
          On your Mac, run <code>harness pair</code> or open Pairing in the harness app, then enter
          the code it shows.
        </p>
        <label className="flbl" htmlFor="pair-code">
          Pairing code
        </label>
        <input
          id="pair-code"
          className="fin code"
          value={code}
          onChange={(e) => {
            setCode(normalizeCode(e.target.value));
          }}
          inputMode="text"
          autoCapitalize="characters"
          autoComplete="one-time-code"
          autoCorrect="off"
          spellCheck={false}
          aria-describedby="pair-error"
        />
        <label className="flbl" htmlFor="pair-name">
          Device name
        </label>
        <input
          id="pair-name"
          className="fin"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
          autoComplete="off"
        />
        <div id="pair-error" className="err" role="alert">
          {error}
        </div>
        <button className="b b-pri" type="submit" disabled={!ready}>
          {busy ? "Pairing..." : "Pair"}
        </button>
      </form>
    </main>
  );
}
