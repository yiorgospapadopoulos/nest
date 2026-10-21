import { useState } from "react";
import type { ClaudeAccount, CodexAccount, GithubAccount, GithubState } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Confirm } from "../pixies/Confirm.tsx";
import { Loading, Row, Section, Status, type StatusTone } from "./rows.tsx";

const GITHUB: Record<GithubState, { tone: StatusTone; label: string }> = {
  signed_in: { tone: "ok", label: "Signed in" },
  signed_out: { tone: "wait", label: "Signed out" },
  unavailable: { tone: "bad", label: "gh not installed" },
};

/**
 * Claude Code's login, Codex's (B94) and the GitHub login, as the Mac has them; Nest stores
 * none of them.
 */
export function AccountsPage() {
  const { state } = useStore();
  const { claude, codex, github } = state.settings;
  return (
    <>
      {claude === null ? <Loading title="Claude" /> : <Claude account={claude} />}
      {codex === null ? <Loading title="Codex" /> : <Codex account={codex} />}
      {github === null ? <Loading title="GitHub" /> : <GitHub account={github} />}
    </>
  );
}

const CODEX_STATE = {
  true: { tone: "ok", label: "Signed in" },
  false: { tone: "wait", label: "Signed out" },
  null: { tone: "idle", label: "Not checked" },
} as const;

/**
 * Codex's ChatGPT sign-in (B102 item 26): its callback is local to the Mac, so the phone
 * shows the status, signs out, and says where to sign in.
 */
function Codex({ account }: { account: CodexAccount }) {
  const { actions } = useStore();
  const [asking, setAsking] = useState(false);
  const status = CODEX_STATE[String(account.signed_in) as keyof typeof CODEX_STATE];
  const email = account.email === null || account.email === "" ? null : account.email;
  return (
    <Section title="Codex">
      <Row
        label={
          <>
            <span>{email ?? "Codex"}</span>
            {account.plan !== null && <span className="hint">{account.plan}</span>}
          </>
        }
      >
        <Status tone={status.tone} label={status.label} />
        {account.signed_in === true && (
          <button
            className="b"
            aria-label="Sign out of Codex"
            onClick={() => {
              setAsking(true);
            }}
          >
            Sign out
          </button>
        )}
      </Row>
      {account.signed_in === false && (
        <p className="srow note">Sign in to Codex on the Mac, in Settings &gt; Accounts.</p>
      )}
      {typeof account.error === "string" && (
        <p className="srow note" role="alert">
          {account.error}
        </p>
      )}
      {asking && (
        <Confirm
          title="Sign out of Codex?"
          about="Codex on this Mac signs out too. Codex chats cannot run until you sign in again."
          action="Sign out"
          onConfirm={() => void actions.codexLogout()}
          onClose={() => {
            setAsking(false);
          }}
        />
      )}
    </Section>
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
            <Status tone="ok" label="Signed in" />
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
        <Status tone={status.tone} label={status.label} />
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
