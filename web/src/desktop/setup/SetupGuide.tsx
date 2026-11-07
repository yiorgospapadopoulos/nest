import { useEffect, useState } from "react";
import { useStore } from "../../store/context.ts";
import { useApi } from "../context.ts";
import { useSettingsChange } from "../settings/config/util.ts";
import { useShell } from "../shell/context.ts";
import { Button } from "../ui/controls.tsx";
import {
  EnginePage,
  FirstChatPage,
  GenericPage,
  NotificationsPage,
  NtfyPage,
  TailscalePage,
} from "./pages.tsx";
import { StepMark } from "./parts.tsx";
import {
  STEPS,
  canContinue,
  canFinish,
  canSkip,
  checksById,
  firstChatModel,
  markOf,
  type StepId,
} from "./steps.ts";
import { useChecks } from "./useChecks.ts";

const SUBTITLES: Partial<Record<StepId, string>> = {
  engine: "Nest needs one. You can add the others later.",
  first_chat: "It uses the cheapest model of your engine.",
};

/**
 * The setup guide over the whole window (B130, design B): the steps on the left, every one
 * can be clicked, and one page at a time. Skipped steps are remembered while it is open.
 */
export function SetupGuide({ firstRun }: { firstRun: boolean }) {
  const { state, actions } = useStore();
  const api = useApi();
  const shell = useShell();
  const change = useSettingsChange();
  const { checks, checking, refresh } = useChecks();
  const [index, setIndex] = useState(0);
  const [skipped, setSkipped] = useState<ReadonlySet<StepId>>(new Set());
  const [notified, setNotified] = useState(false);
  const found = checksById(checks ?? []);
  const step = STEPS[index] ?? STEPS[0];
  useEffect(() => {
    void actions.loadChoices();
    void actions.loadAccounts();
  }, [actions]);
  if (step === undefined) return null;

  const check = found.get(step.id);
  const engineReady = found.get("engine")?.state === "ok";
  const last = index === STEPS.length - 1;
  const finishable = canFinish(firstRun, engineReady);
  const finish = (then: () => void) => {
    change("Could not finish", async () => {
      await api.finishSetup();
      shell.closeGuide();
      then();
    });
  };
  const skip = () => {
    setSkipped(new Set(skipped).add(step.id));
    setIndex(index + 1);
  };

  const page = () => {
    switch (step.id) {
      case "engine":
        return <EnginePage onChanged={refresh} />;
      case "tailscale":
        return <TailscalePage check={check} checking={checking} onCheck={refresh} />;
      case "notifications":
        return (
          <NotificationsPage
            onSent={() => {
              setNotified(true);
            }}
          />
        );
      case "ntfy":
        return <NtfyPage />;
      case "first_chat":
        return (
          <FirstChatPage
            chat={firstChatModel(state)}
            disabled={!finishable}
            onOpenChat={(chat) => {
              finish(() => {
                shell.openGeneralChat(chat);
              });
            }}
            onAddProject={() => {
              finish(() => {
                shell.openSettings({ page: "addProject" });
              });
            }}
          />
        );
      default:
        return <GenericPage check={check} checking={checking} onCheck={refresh} />;
    }
  };

  const subtitle = SUBTITLES[step.id];
  return (
    <div className="su">
      <nav className="su-rail" aria-label="Set up Nest">
        <h2>Set up Nest</h2>
        {STEPS.map(({ id, rail }, at) => {
          const open = at === index;
          const passed = id === "secret_service" || (id === "notifications" && notified);
          return (
            <button
              key={id}
              className={open ? "su-item on" : "su-item"}
              aria-current={open ? "step" : undefined}
              onClick={() => {
                setIndex(at);
              }}
            >
              <StepMark mark={markOf(found.get(id)?.state, open, skipped.has(id), passed)} />
              {rail}
            </button>
          );
        })}
      </nav>
      <main className="su-pane" aria-label={step.title}>
        <h1>{step.title}</h1>
        {subtitle !== undefined && <p className="su-sub">{subtitle}</p>}
        <div className="su-body" key={step.id}>
          {page()}
        </div>
        <footer className="su-foot">
          {canSkip(step.id) && (
            <Button kind="plain" size="large" onClick={skip}>
              Skip
            </Button>
          )}
          {index > 0 && (
            <Button
              size="large"
              onClick={() => {
                setIndex(index - 1);
              }}
            >
              Back
            </Button>
          )}
          {last ? (
            <Button
              kind="primary"
              size="large"
              disabled={!finishable}
              onClick={() => {
                finish(() => undefined);
              }}
            >
              Finish
            </Button>
          ) : (
            <Button
              kind="primary"
              size="large"
              disabled={!canContinue(step.id, engineReady)}
              onClick={() => {
                setIndex(index + 1);
              }}
            >
              Continue
            </Button>
          )}
        </footer>
      </main>
    </div>
  );
}
