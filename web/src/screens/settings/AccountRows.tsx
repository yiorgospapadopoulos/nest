import { useEffect, useState, type ReactNode } from "react";
import type { BankedCredit, EngineAccount } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { engineTitle } from "../../store/usageMeter.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet, Sheet } from "../../ui/Sheet.tsx";
import { Confirm } from "../pixies/Confirm.tsx";
import { NameSheet } from "../pixies/NameSheet.tsx";
import {
  accountDetail,
  accountState,
  bankedTitle,
  creditExpiry,
  creditTitle,
  limitLine,
  signOutNote,
  used,
} from "./accountText.ts";
import { Loading, Row, Section, Status } from "./rows.tsx";

// Each section's mark, as the More engines design has it (B107): short letters in a chip.
const MARKS: Record<string, ReactNode> = {
  claude: "CL",
  codex: "CX",
  more: "+",
  gh: "gh",
  local: <Icon name="devices" />,
};

export function Mark({ name }: { name: string }) {
  return (
    <span className="acct-mark" aria-hidden="true">
      {MARKS[name] ?? name.slice(0, 2).toUpperCase()}
    </span>
  );
}

/**
 * An engine's accounts (B98, D124) as the Mac's: the check marks the one turns run on and a
 * tap on another's moves it; each row's ⋯ renames, signs out or removes. Adding an account and
 * signing in stay on the Mac, whose sign-in pages open there.
 */
export function EngineAccounts({
  provider,
  // Local models run chats, so signing in is a choice (B106).
  optional,
}: {
  provider: "claude" | "codex";
  optional: boolean;
}) {
  const { state, actions } = useStore();
  const [acting, setActing] = useState<EngineAccount | null>(null);
  const [banked, setBanked] = useState(false);
  const all = state.settings.accounts;
  const engine = engineTitle(provider);
  if (all === null) return <Loading title={engine} />;
  const accounts = all.filter((a) => a.provider === provider);
  const signedOut = !optional && accounts.some((a) => a.signed_in === false);
  const available = accounts.reduce((sum, a) => sum + (a.banked_resets?.available ?? 0), 0);
  return (
    <Section title={engine} className="acct" mark={<Mark name={provider} />}>
      {accounts.length === 0 ? (
        <Row label="Not signed in" />
      ) : (
        <div role="radiogroup" aria-label={`${engine} account in use`}>
          {accounts.map((account) => (
            <AccountRow
              key={account.id}
              account={account}
              optional={optional}
              onActivate={() => void actions.activateAccount(account.id)}
              onMore={() => {
                setActing(account);
              }}
            />
          ))}
        </div>
      )}
      {signedOut && (
        <p className="srow note">Sign in to {engine} on the Mac, in Settings &gt; Accounts.</p>
      )}
      {/* Claude Code keeps no banked resets. */}
      {provider === "codex" && accounts.length > 0 && (
        <button
          className="srow slink"
          onClick={() => {
            setBanked(true);
          }}
        >
          <span className="slab">{bankedTitle(available)}</span>
          <Icon name="chevr" className="schev" />
        </button>
      )}
      {acting !== null && (
        <AccountActions
          account={acting}
          optional={optional}
          onClose={() => {
            setActing(null);
          }}
        />
      )}
      {banked && (
        <BankedResetsSheet
          accounts={accounts}
          onClose={() => {
            setBanked(false);
          }}
        />
      )}
    </Section>
  );
}

/** The check and initial, the title over the plan and email, the login and ⋯, then each window. */
function AccountRow({
  account,
  optional,
  onActivate,
  onMore,
}: {
  account: EngineAccount;
  optional: boolean;
  onActivate: () => void;
  onMore: () => void;
}) {
  const detail = accountDetail(account);
  const status = accountState(account, optional);
  const now = new Date();
  const engine = engineTitle(account.provider);
  return (
    <>
      <div className="srow acrow">
        <button
          className="ucheck"
          role="radio"
          aria-checked={account.active}
          aria-label={`Use ${account.title} for ${engine}`}
          onClick={onActivate}
        />
        <span className="acav" aria-hidden="true">
          {account.title.charAt(0).toUpperCase()}
        </span>
        <span className="slab">
          <span>{account.title}</span>
          {detail !== null && <span className="hint">{detail}</span>}
        </span>
        <div className="sctl">
          <Status tone={status.tone} label={status.label} />
          <button className="acmore" aria-label={`Actions for ${account.title}`} onClick={onMore}>
            <Icon name="dots" />
          </button>
        </div>
        {account.signed_in === true && account.limits.length > 0 && (
          <div className="acwin">
            {account.limits.map((w) => (
              <div key={w.label} className="acw">
                <span>{limitLine(w, now)}</span>
                <div
                  className="meter sm ink"
                  role="meter"
                  aria-label={`${account.title} ${w.label} used`}
                  aria-valuenow={used(w)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <i style={{ width: `${String(used(w))}%` }} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {account.error !== null && (
        <p className="srow note" role="alert">
          Signing in failed: {account.error}
        </p>
      )}
    </>
  );
}

/** ⋯ on an account: Use this account, Rename, Sign out and Remove, each as the Mac's menu. */
function AccountActions({
  account,
  optional,
  onClose,
}: {
  account: EngineAccount;
  optional: boolean;
  onClose: () => void;
}) {
  const { actions } = useStore();
  const [step, setStep] = useState<"menu" | "rename" | "signOut" | "remove">("menu");
  const detail = accountDetail(account);
  const signedIn = account.signed_in === true;
  switch (step) {
    case "rename":
      return (
        <NameSheet
          title="Rename"
          label="Account name"
          empty="Type a name"
          initial={account.name ?? account.title}
          action="Save"
          onSave={(name) => {
            onClose();
            void actions.renameAccount(account.id, name);
          }}
          onClose={onClose}
        />
      );
    case "signOut":
      return (
        <Confirm
          title={`Sign out of ${account.title}?`}
          about={signOutNote(account, optional)}
          action="Sign out"
          onConfirm={() => void actions.signOutAccount(account.id)}
          onClose={onClose}
        />
      );
    case "remove":
      return (
        <Confirm
          title={`Remove ${account.title}?`}
          about=""
          action="Remove"
          onConfirm={() => void actions.removeAccount(account.id)}
          onClose={onClose}
        />
      );
    case "menu":
      return (
        <ActionSheet
          label={`Actions for ${account.title}`}
          title={<b>{[account.title, detail].filter((part) => part !== null).join(" · ")}</b>}
          onClose={onClose}
        >
          {!account.active && signedIn && (
            <button
              className="asi"
              role="menuitem"
              onClick={() => {
                onClose();
                void actions.activateAccount(account.id);
              }}
            >
              <Icon name="check" />
              <span>Use this account</span>
            </button>
          )}
          <button
            className="asi"
            role="menuitem"
            onClick={() => {
              setStep("rename");
            }}
          >
            <Icon name="edit" />
            <span>Rename</span>
          </button>
          {signedIn && (
            <button
              className="asi"
              role="menuitem"
              onClick={() => {
                setStep("signOut");
              }}
            >
              <Icon name="user" />
              <span>Sign out</span>
            </button>
          )}
          {/* The engine's own login on the Mac is never removed. */}
          {!account.first && (
            <button
              className="asi dng"
              role="menuitem"
              onClick={() => {
                setStep("remove");
              }}
            >
              <Icon name="trash" />
              <span>Remove</span>
            </button>
          )}
        </ActionSheet>
      );
  }
}

/** Each signed-in Codex account's banked resets, read as the sheet opens, each with Use. */
function BankedResetsSheet({
  accounts,
  onClose,
}: {
  accounts: EngineAccount[];
  onClose: () => void;
}) {
  const { state, actions } = useStore();
  const [using, setUsing] = useState<{ account: EngineAccount; credit: BankedCredit } | null>(null);
  useEffect(() => {
    void actions.loadBankedResets("codex");
  }, [actions]);
  const signedIn = accounts.filter((a) => a.signed_in === true);
  if (using !== null) {
    return (
      <Confirm
        title={`Use a banked reset on ${using.account.title}?`}
        about="Its current Codex limits reset now."
        action="Use"
        neutral
        onConfirm={() => void actions.useBankedReset(using.account.id, using.credit.id)}
        onClose={() => {
          setUsing(null);
        }}
      />
    );
  }
  return (
    <Sheet title="Banked resets" onClose={onClose}>
      <div className="set">
        {signedIn.map((account) => {
          const credits = state.settings.bankedResets[account.id]?.credits ?? null;
          const none =
            credits === null ? (account.banked_resets?.available ?? 0) === 0 : credits.length === 0;
          return (
            <Section key={account.id} title={account.title}>
              {none ? (
                <p className="srow note">No banked resets</p>
              ) : credits === null ? (
                <p className="srow note">Loading...</p>
              ) : (
                credits.map((credit) => {
                  const expiry = creditExpiry(credit);
                  return (
                    <Row
                      key={credit.id}
                      label={
                        <>
                          <span>{creditTitle(credit)}</span>
                          {expiry !== null && <span className="hint">{expiry}</span>}
                        </>
                      }
                    >
                      <button
                        className="b"
                        aria-label={`Use ${creditTitle(credit)} on ${account.title}`}
                        onClick={() => {
                          setUsing({ account, credit });
                        }}
                      >
                        Use
                      </button>
                    </Row>
                  );
                })
              )}
            </Section>
          );
        })}
      </div>
    </Sheet>
  );
}
