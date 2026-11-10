import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import type { BankedCredit, EngineAccount } from "../../../api/types.ts";
import { initials } from "../../../format.ts";
import {
  accountDetail,
  bankedTitle,
  creditExpiry,
  creditTitle,
  finishSignIn,
  LIMIT_RESET,
  limitLine,
  limitResetTitle,
  used,
} from "../../../screens/settings/accountText.ts";
import { useStore } from "../../../store/context.ts";
import { engineTitle } from "../../../store/usageMeter.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { useApi } from "../../context.ts";
import { EngineMark } from "../../shell/frame/marks.tsx";
import { Button } from "../../ui/controls.tsx";
import { Menu } from "../../ui/Menu.tsx";
import type { MenuEntry } from "../../ui/menuItems.ts";
import { Popover } from "../../ui/Popover.tsx";
import { CheckBox, Failure, SettingsListRow, SettingsSection } from "../rows.tsx";
import { FoldChevron, StatusLabel } from "../config/parts.tsx";
import { Confirm } from "../../sheets/Alert.tsx";
import { useSettingsChange } from "../config/util.ts";
import { EngineHeader, Meter, MoreGlyph } from "./parts.tsx";
import { useSignIn } from "./signIn.ts";

/**
 * An engine's accounts as a radio group (B98), as AccountsPage.swift's EngineAccounts: the
 * check marks the one turns run on, and a click on another signed-in row moves it. Then Add
 * and, for Codex, the banked resets.
 */
export function EngineAccounts({
  provider,
  optional,
}: {
  provider: "claude" | "codex";
  // With local models, signing in is a choice, not a need (B106).
  optional: boolean;
}) {
  const { state } = useStore();
  const { add } = useSignIn();
  const engine = engineTitle(provider);
  const accounts = (state.settings.accounts ?? []).filter((a) => a.provider === provider);

  return (
    <SettingsSection bare>
      <EngineHeader engine={provider} title={engine} />
      <div className="dka-rows" role="radiogroup" aria-label={`${engine} account in use`}>
        {accounts.map((account) => (
          <div key={account.id}>
            <AccountRow account={account} accounts={accounts} optional={optional} />
            {account.error !== null && <Failure text={`Signing in failed: ${account.error}`} />}
          </div>
        ))}
      </div>
      {provider === "claude" && <LimitResetRows accounts={accounts} />}
      <div className="dka-tools">
        <Button
          onClick={() => {
            add(provider);
          }}
        >
          <Icon name="plus" />
          {`Add ${engine} account`}
        </Button>
        {/* Claude Code keeps no banked resets. */}
        {provider === "codex" && <BankedResetsButton accounts={accounts} />}
      </div>
    </SettingsSection>
  );
}

function AccountRow({
  account,
  accounts,
  optional,
}: {
  account: EngineAccount;
  accounts: EngineAccount[];
  optional: boolean;
}) {
  const { actions } = useStore();
  const [renaming, setRenaming] = useState(false);
  const engine = engineTitle(account.provider);
  const activate = (id: string) => void actions.activateAccount(id);

  // Up and Down move the check to the signed-in account above or below.
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === " ") {
      event.preventDefault();
      activate(account.id);
      return;
    }
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    const choices = accounts.filter((a) => a.signed_in === true || a.id === account.id);
    const next =
      choices[choices.findIndex((a) => a.id === account.id) + (event.key === "ArrowUp" ? -1 : 1)];
    if (next === undefined) return;
    event.preventDefault();
    activate(next.id);
    event.currentTarget
      .closest("[role=radiogroup]")
      ?.querySelector<HTMLElement>(`[data-account="${CSS.escape(next.id)}"]`)
      ?.focus();
  };

  return (
    <div
      data-account={account.id}
      className="dka-row"
      role="radio"
      aria-checked={account.active}
      aria-label={`Use ${account.title} for ${engine}`}
      tabIndex={account.active ? 0 : -1}
      onClick={(event) => {
        if ((event.target as HTMLElement).closest("button, input") === null) activate(account.id);
      }}
      onKeyDown={onKeyDown}
    >
      <SettingsListRow
        title={account.title}
        detail={accountDetail(account)}
        rename={
          renaming
            ? {
                initial: account.name ?? account.title,
                done: (name) => {
                  setRenaming(false);
                  if (name !== null) void actions.renameAccount(account.id, name);
                },
              }
            : null
        }
        leading={
          <>
            <CheckBox on={account.active} />
            <AccountMark account={account} />
          </>
        }
        trailing={
          <AccountControls
            account={account}
            optional={optional}
            onRename={() => {
              setRenaming(true);
            }}
          />
        }
      />
    </div>
  );
}

/** Claude's accounts show their initials, Codex's the OpenAI mark. */
function AccountMark({ account }: { account: EngineAccount }) {
  if (account.provider === "claude") {
    return (
      <span className="dka-avatar" aria-hidden="true">
        {initials(account.title)}
      </span>
    );
  }
  return (
    <span className="dka-tile" aria-hidden="true">
      <EngineMark provider={account.provider} size={18} />
    </span>
  );
}

/**
 * The row's trailing side: signing in waits on the browser; otherwise the limits of a
 * signed-in account, its login, Sign in when signed out, and the menu.
 */
function AccountControls({
  account,
  optional,
  onRename,
}: {
  account: EngineAccount;
  optional: boolean;
  onRename: () => void;
}) {
  const api = useApi();
  const { actions } = useStore();
  const { signIn } = useSignIn();
  const change = useSettingsChange();
  const [confirming, setConfirming] = useState<"signOut" | "remove" | null>(null);
  const [busy, setBusy] = useState(false);

  if (account.signing_in) {
    return (
      <>
        <Fireflies />
        <span className="dka-meta">{finishSignIn(account.provider)}</span>
        <Button
          onClick={() => {
            change("Could not cancel signing in", () => api.cancelAccountSignIn(account.id));
          }}
        >
          Cancel
        </Button>
      </>
    );
  }
  const signedIn = account.signed_in === true;
  const state =
    account.signed_in === true
      ? "Signed in"
      : account.signed_in === false
        ? optional
          ? "Not signed in, optional"
          : "Signed out"
        : "Not checked";
  const items = (): MenuEntry[] => [
    { title: "Rename…", onSelect: onRename },
    ...(signedIn
      ? [
          {
            title: "Sign out",
            onSelect: () => {
              setConfirming("signOut");
            },
          },
        ]
      : []),
    ...(account.first
      ? []
      : [
          { type: "separator" as const },
          {
            title: "Remove",
            danger: true,
            onSelect: () => {
              setConfirming("remove");
            },
          },
        ]),
  ];
  const run = (call: () => Promise<void>) => {
    setBusy(true);
    void call().finally(() => {
      setBusy(false);
    });
  };
  // The first account is the engine's own login on this computer.
  const signOutNote =
    account.first && !optional
      ? account.provider === "claude"
        ? "Claude Code on this computer signs out too. Chats cannot run until you sign in again."
        : "Codex on this computer signs out too. Codex chats cannot run until you sign in again."
      : undefined;

  return (
    <>
      {signedIn && <AccountLimits account={account} />}
      <StatusLabel tone={signedIn ? "review" : "done"} label={state} hollow={!signedIn} />
      {!signedIn && (
        <Button
          kind={optional ? "soft" : "primary"}
          onClick={() => {
            signIn(account.id);
          }}
        >
          Sign in
        </Button>
      )}
      <Menu label={`Actions for ${account.title}`} items={items} align="end">
        {(trigger) => (
          <button
            {...trigger}
            type="button"
            className="dka-menu"
            aria-label={`Actions for ${account.title}`}
            title="More"
            disabled={busy}
          >
            <MoreGlyph />
          </button>
        )}
      </Menu>
      {confirming !== null && (
        <Confirm
          title={
            confirming === "remove" ? `Remove ${account.title}?` : `Sign out of ${account.title}?`
          }
          {...(confirming === "signOut" && signOutNote !== undefined
            ? { message: signOutNote }
            : {})}
          action={confirming === "remove" ? "Remove" : "Sign out"}
          destructive
          onConfirm={() => {
            run(() =>
              confirming === "remove"
                ? actions.removeAccount(account.id)
                : actions.signOutAccount(account.id),
            );
          }}
          onClose={() => {
            setConfirming(null);
          }}
        />
      )}
    </>
  );
}

/** Every window, each a thin bar under its percent and reset time. */
function AccountLimits({ account }: { account: EngineAccount }) {
  const now = new Date();
  if (account.limits.length === 0) return null;
  return (
    <span className="dka-limits">
      {account.limits.map((window) => (
        <span key={window.label} className="dka-limit">
          <span>{limitLine(window, now)}</span>
          <Meter value={used(window)} label={`${account.title} ${window.label} used`} />
        </span>
      ))}
    </span>
  );
}

/**
 * Claude Code's limit reset (B161), for each signed-in Claude account: Reset in Terminal
 * asks first, then opens Claude Code there, which uses the reset itself if there is one.
 */
function LimitResetRows({ accounts }: { accounts: EngineAccount[] }) {
  const { actions } = useStore();
  const [using, setUsing] = useState<EngineAccount | null>(null);
  const offered = accounts.filter((a) => a.limit_reset);
  if (offered.length === 0) return null;
  return (
    <div className="dka-rows">
      {offered.map((account) => (
        <SettingsListRow
          key={account.id}
          title={LIMIT_RESET.row}
          detail={accounts.length > 1 ? account.title : null}
          trailing={
            <Button
              aria-label={`${LIMIT_RESET.action} for ${account.title}`}
              onClick={() => {
                setUsing(account);
              }}
            >
              {LIMIT_RESET.action}
            </Button>
          }
        />
      ))}
      {using !== null && (
        <Confirm
          title={limitResetTitle(using)}
          message={LIMIT_RESET.message}
          action={LIMIT_RESET.action}
          onConfirm={() => void actions.openLimitReset(using.id)}
          onClose={() => {
            setUsing(null);
          }}
        />
      )}
    </div>
  );
}

/** The banked resets: the count available on the button, each account's in a popover. */
function BankedResetsButton({ accounts }: { accounts: EngineAccount[] }) {
  const { state, actions } = useStore();
  const anchor = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [using, setUsing] = useState<{ account: EngineAccount; credit: BankedCredit } | null>(null);
  const available = accounts.reduce((sum, a) => sum + (a.banked_resets?.available ?? 0), 0);
  useEffect(() => {
    if (open) void actions.loadBankedResets("codex");
  }, [open, actions]);
  const signedIn = accounts.filter((a) => a.signed_in === true);
  return (
    <>
      <span ref={anchor} className="dka-anchor">
        <Button
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
          }}
        >
          {bankedTitle(available)}
          <FoldChevron open />
        </Button>
      </span>
      {open && (
        <Popover
          anchor={anchor}
          label="Banked resets"
          onClose={() => {
            setOpen(false);
          }}
          className="dka-banked"
        >
          {signedIn.map((account) => {
            const credits = state.settings.bankedResets[account.id]?.credits ?? null;
            const none =
              (account.banked_resets?.available ?? 0) === 0 && (credits?.length ?? 0) === 0;
            return (
              <SettingsSection key={account.id} title={account.title} bare>
                {none ? (
                  <p className="dka-none">No banked resets</p>
                ) : credits === null ? (
                  <Fireflies />
                ) : (
                  <div className="dka-rows">
                    {credits.map((credit) => (
                      <SettingsListRow
                        key={credit.id}
                        title={creditTitle(credit)}
                        detail={creditExpiry(credit)}
                        trailing={
                          <Button
                            onClick={() => {
                              setOpen(false);
                              setUsing({ account, credit });
                            }}
                          >
                            Use
                          </Button>
                        }
                      />
                    ))}
                  </div>
                )}
              </SettingsSection>
            );
          })}
        </Popover>
      )}
      {using !== null && (
        <Confirm
          title={`Use a banked reset on ${using.account.title}?`}
          message="Its current Codex limits reset now."
          action="Use"
          onConfirm={() => void actions.useBankedReset(using.account.id, using.credit.id)}
          onClose={() => {
            setUsing(null);
          }}
        />
      )}
    </>
  );
}
