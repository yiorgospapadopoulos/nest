import { useCallback, useEffect, useState } from "react";
import type { AccountProvider, EngineAccount, PairingCode, SetupCheck } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import type { DraftModel } from "../layout/project.ts";
import { useSignIn } from "../settings/accounts/signIn.ts";
import { NtfyFields } from "../settings/NtfySection.tsx";
import { PairingCodeView } from "../settings/parts3/PairingCodeView.tsx";
import { useApi } from "../context.ts";
import { Button } from "../ui/controls.tsx";
import { CheckAgain, FixAction, StepMark, TestNotification } from "./parts.tsx";
import { tailscaleStage, type Mark } from "./steps.ts";

const ENGINES: { provider: AccountProvider; title: string }[] = [
  { provider: "claude", title: "Claude Code" },
  { provider: "codex", title: "Codex" },
];

function EngineRow({
  provider,
  title,
  account,
}: {
  provider: AccountProvider;
  title: string;
  account: EngineAccount | undefined;
}) {
  const { add, signIn } = useSignIn();
  return (
    <div className="su-row">
      <b>{title}</b>
      {account?.signed_in === true ? (
        <StepMark mark="ok" />
      ) : (
        <Button
          onClick={() => {
            if (account === undefined) add(provider);
            else signIn(account.id);
          }}
        >
          Sign in
        </Button>
      )}
    </div>
  );
}

/** Claude Code, Codex or local models, through the same actions as Settings > Accounts. */
export function EnginePage({ onChanged }: { onChanged: () => void }) {
  const { state, actions } = useStore();
  const api = useApi();
  const accounts = state.settings.accounts ?? [];
  const localOnly = state.local.list?.local_only === true;
  const signedIn = accounts.filter((account) => account.signed_in === true).length;
  useEffect(() => {
    void actions.loadAccounts();
    void actions.loadLocalModels();
  }, [actions]);
  // A sign-in ends in the browser; its `accounts.changed` makes the check worth asking again.
  useEffect(() => {
    if (signedIn > 0) onChanged();
  }, [signedIn, onChanged]);
  const chooseLocal = async () => {
    await api.useLocalOnly();
    await actions.loadLocalModels();
    onChanged();
  };
  return (
    <div className="su-rows">
      {ENGINES.map(({ provider, title }) => (
        <EngineRow
          key={provider}
          provider={provider}
          title={title}
          account={accounts.find((a) => a.provider === provider)}
        />
      ))}
      <div className="su-row">
        <b>Local models</b>
        {localOnly ? (
          <StepMark mark="ok" />
        ) : (
          <Button
            onClick={() => {
              chooseLocal().catch((error: unknown) => {
                actions.toast(error instanceof Error ? error.message : String(error), "error");
              });
            }}
          >
            Use local models only
          </Button>
        )}
      </div>
    </div>
  );
}

interface CheckedProps {
  check: SetupCheck | undefined;
  checking: boolean;
  onCheck: () => void;
}

/** A check's message, its fix and Check again. */
export function GenericPage({ check, checking, onCheck }: CheckedProps) {
  const line = check === undefined ? null : check.message || check.detail;
  return (
    <>
      {line != null && line !== "" && <p className="su-line">{line}</p>}
      {check?.fix != null && <FixAction fix={check.fix} />}
      <CheckAgain checking={checking} onCheck={onCheck} />
    </>
  );
}

function Line({ mark, children }: { mark: Mark; children: string }) {
  return (
    <p className="su-step">
      <StepMark mark={mark} />
      {children}
    </p>
  );
}

/** Tailscale running, shared at its address, then the pairing code in place. */
export function TailscalePage({ check, checking, onCheck }: CheckedProps) {
  const { actions } = useStore();
  const stage = tailscaleStage(check);
  const paired = check?.state === "ok";
  const pairing = stage === "shared" && !paired;
  const [code, setCode] = useState<PairingCode | null>(null);
  const newCode = useCallback(() => {
    void actions.pairingCode().then((created) => {
      if (created !== null) setCode(created);
    });
  }, [actions]);
  useEffect(() => {
    if (pairing) newCode();
  }, [pairing, newCode]);
  const address = check?.detail ?? "";
  return (
    <>
      {check === undefined ? null : stage === "off" ? (
        <Line mark="now">{check.message}</Line>
      ) : (
        <>
          <Line mark="ok">Tailscale is running</Line>
          {stage === "unshared" ? (
            <Line mark="now">Share Nest with your own devices</Line>
          ) : (
            <Line mark="ok">{`Shared with your devices at ${address}`}</Line>
          )}
        </>
      )}
      {check?.fix != null && <FixAction fix={check.fix} />}
      {paired && <Line mark="ok">Your iPhone is paired</Line>}
      {pairing && <Line mark="now">Open that address on your iPhone and enter this code</Line>}
      {pairing && code !== null && (
        <PairingCodeView code={code} className="su-code" onNewCode={newCode} />
      )}
      {!pairing && <CheckAgain checking={checking} onCheck={onCheck} />}
    </>
  );
}

export function NotificationsPage({ onSent }: { onSent: () => void }) {
  return (
    <>
      <TestNotification onSent={onSent} />
      <p className="su-line">Turn on notifications in Account &gt; Notifications on your phone.</p>
    </>
  );
}

export function NtfyPage() {
  return <NtfyFields />;
}

export function FirstChatPage({
  chat,
  disabled,
  onOpenChat,
  onAddProject,
}: {
  chat: DraftModel | null;
  disabled: boolean;
  onOpenChat: (chat: DraftModel | null) => void;
  onAddProject: () => void;
}) {
  return (
    <div className="su-again">
      <Button
        kind="primary"
        size="large"
        disabled={disabled}
        onClick={() => {
          onOpenChat(chat);
        }}
      >
        Open a chat
      </Button>
      <Button size="large" disabled={disabled} onClick={onAddProject}>
        Add a project
      </Button>
    </div>
  );
}
