import { useState } from "react";
import type { ClaudeAccount, GithubAccount, GithubState } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { Tone } from "../../store/selectors.ts";
import { Pill } from "../../ui/bits.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { Loading, Row, Section } from "./rows.tsx";

const GITHUB: Record<GithubState, { tone: Tone; label: string }> = {
  signed_in: { tone: "rev", label: "Signed in" },
  signed_out: { tone: "wait", label: "Signed out" },
  unavailable: { tone: "fail", label: "gh not installed" },
};

/** Claude Code's login and the GitHub login, as the Mac has them; Nest stores neither. */
export function AccountsPage() {
  const { state } = useStore();
  const { claude, github } = state.settings;
  return (
    <>
      {claude === null ? <Loading title="Claude" /> : <Claude account={claude} />}
      {github === null ? <Loading title="GitHub" /> : <GitHub account={github} />}
    </>
  );
}

function Claude({ account }: { account: ClaudeAccount }) {
  const { state, actions } = useStore();
  const [showEmail, setShowEmail] = useState(false);
  const [asking, setAsking] = useState(false);
  const name = state.account?.display_name ?? "Claude account";
  return (
    <Section title="Claude">
      {account.signed_in ? (
        <>
          <Row label={name}>
            <Pill tone="rev" label="Signed in" />
            <button
              className="b"
              onClick={() => {
                setAsking(true);
              }}
            >
              Sign out
            </button>
          </Row>
          {account.plan !== null && (
            <Row label="Plan">
              <span className="sval">{account.plan}</span>
            </Row>
          )}
          {account.email !== null && (
            <Row label="Email">
              {showEmail ? (
                <span className="sval">{account.email}</span>
              ) : (
                <button
                  className="b"
                  aria-label="Show email"
                  onClick={() => {
                    setShowEmail(true);
                  }}
                >
                  Show
                </button>
              )}
            </Row>
          )}
        </>
      ) : (
        <Row label="Not signed in">
          <button className="b b-pri" onClick={() => void actions.claudeLogin()}>
            Sign in
          </button>
        </Row>
      )}
      {typeof account.error === "string" && (
        <p className="srow note" role="alert">
          {account.error}
        </p>
      )}
      {asking && (
        <Confirm
          title="Sign out of Claude?"
          about="Agents cannot run until you sign in again."
          action="Sign out"
          onConfirm={() => void actions.claudeLogout()}
          onClose={() => {
            setAsking(false);
          }}
        />
      )}
    </Section>
  );
}

function GitHub({ account }: { account: GithubAccount }) {
  const { actions } = useStore();
  const [checking, setChecking] = useState(false);
  const status = GITHUB[account.state];
  return (
    <Section title="GitHub">
      <Row label={account.login ?? "GitHub"}>
        <Pill tone={status.tone} label={status.label} />
        <button
          className="b"
          disabled={checking}
          onClick={() => {
            setChecking(true);
            void actions.checkGithub().finally(() => {
              setChecking(false);
            });
          }}
        >
          {checking ? "Checking..." : "Check again"}
        </button>
      </Row>
    </Section>
  );
}
