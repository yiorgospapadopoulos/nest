import { ApiError, OPEN_ELSEWHERE, type Api } from "../api/client.ts";
import {
  disablePush,
  enablePush,
  refreshPush,
  type PushEnv,
  type PushStatus,
} from "../pwa/push.ts";
import type {
  AgentDefaults,
  AgentWork,
  Approval,
  ApproveBody,
  ArtifactAnswer,
  ArtifactContent,
  AskStatus,
  ArtifactFilter,
  ArtifactStorage,
  ArtifactStorageChange,
  ArtifactStorageWrite,
  ArtifactVersion,
  Attachment,
  CallWork,
  ClaudeChat,
  CreatePixieBody,
  CommandList,
  CreateSessionBody,
  Habit,
  HabitBody,
  HabitRun,
  NestEvent,
  JsonObject,
  PeriodUnit,
  NotificationSettings,
  PageUsage,
  Pixie,
  PixieActivity,
  PixieSearchHit,
  PixieSkill,
  PixieTeam,
  RepoConfig,
  ResolveBody,
  ForkReply,
  MemoryReply,
  MemoryScope,
  QueuedAttachment,
  Restore,
  RewindPreview,
  RewindReply,
  SearchResults,
  SendAwayBody,
  Session,
  SessionDiff,
  UpdateHabitBody,
  UpdatePixieBody,
  UpdateSessionBody,
  UpdateTeamBody,
  UsageLimits,
  ProviderInfo,
} from "../api/types.ts";
import {
  loadFeatureGroups,
  loadFoldedTeams,
  loadShowAutomated,
  loadUsageBarHidden,
  saveFeatureGroups,
  saveFoldedTeams,
  saveShowAutomated,
  saveUsageBarHidden,
} from "./devicePrefs.ts";
import { CLAUDE } from "./catalog.ts";
import { storageChangeOf } from "../api/payloads.ts";
import { isoDay } from "../format.ts";
import { filterKey } from "./artifacts.ts";
import { nudgeText } from "./selectors.ts";
import { settingsActions } from "./settingsActions.ts";
import { draftKey, type Action, type Toast } from "./state.ts";

export type Dispatch = (action: Action) => void;

// The engines besides Claude whose usage windows the daemon keeps (B91).
export const OTHER_ENGINES = ["codex"];

/** The notice for a `usage.warning` event (D104): "5 hour limit 82% used". */
export function warningText(payload: JsonObject): string {
  const window = payload.window === "seven_day" ? "Weekly" : "5 hour";
  const used = typeof payload.utilization === "number" ? payload.utilization : 0;
  return `${window} limit ${String(Math.round(used * 100))}% used`;
}

// A pixie file as read: `hash` is null while the file does not exist yet.
export interface FileState {
  text: string;
  hash: string | null;
}

export type FileSave = { saved: FileState } | { stale: FileState };

// The code of a write that named an old hash (D072).
const STALE_FILE = "stale_file";

/** The current file a stale-write refusal carries. */
function currentFile({ text, hash }: Record<string, unknown>): FileState {
  return typeof text === "string" && typeof hash === "string"
    ? { text, hash }
    : { text: "", hash: null };
}

export type Actions = ReturnType<typeof createActions>;

const WORKING = new Set<Session["state"]>(["starting", "running"]);
// States in which a chat's subagents may be at work.
const BUSY = new Set<Session["state"]>(["starting", "running", "waiting"]);

// "elsewhere": refused because Claude Code has the chat open right now; `refused`: why the
// daemon refused the message, such as one calling a team's pixie on its own (B46).
export type SendResult = "sent" | "failed" | "elsewhere" | { refused: string };

// The daemon's code for a message that calls a team's pixie on its own (B46).
const PIXIE_IN_TEAM = "pixie_in_team";

// "taken": Claude already read the message (or the Mac no longer has it), so it stays sent.
export type RemoveResult = "removed" | "taken" | "failed";

// The daemon's code for a pending message Claude already read (B59).
const MESSAGE_TAKEN = "message_taken";
// The daemon's code for Resume now on a chat whose pause already ended (B78).
const NOT_PAUSED = "not_paused";

const RESTORED: Record<Restore, string> = {
  code: "Files restored",
  conversation: "Rewound",
  both: "Rewound, and the files restored",
};

/** A message's attachments as a draft holds them. */
export function asDraftFiles(attachments: QueuedAttachment[]): Attachment[] {
  return attachments.map((a) => ({ ...a, created_at: "" }));
}

// "gone": the task no longer runs; "closed": the chat's Claude Code run is not open.
export type StopResult = "sent" | "gone" | "closed" | "failed";

/** Where origin pushes now, when publishing waits for the user to confirm it (I-008). */
export interface RemotePrompt {
  urls: string[];
  // The address Nest recorded before, when origin changed since.
  confirmed: string | null;
}

// "remote": refused until the user confirms where origin pushes.
export type ApproveResult = "approved" | "refused" | "failed" | { remote: RemotePrompt };

// After a restart is asked for, how long to wait between checks that Nest answers again,
// and how many checks to make before giving up.
export const RESTART_POLL_MS = 1500;
export const RESTART_POLLS = 20;

// The daemon's code for an approve refused because HEAD is no longer the one reviewed.
const HEAD_CHANGED = "head_changed";
// Codes of an approve refused until the push address is confirmed.
const REMOTE_CODES: readonly (string | null)[] = ["remote_not_confirmed", "remote_changed"];

function remotePrompt(data: Record<string, unknown>): RemotePrompt {
  const urls = Array.isArray(data.remote_urls) ? data.remote_urls : [];
  return {
    urls: urls.filter((url): url is string => typeof url === "string"),
    confirmed: typeof data.confirmed_url === "string" ? data.confirmed_url : null,
  };
}

/**
 * Everything the screens can do. Each call reports its own failure as a toast (or sends
 * the app back to pairing on 401) and resolves to null, so screens only handle success.
 */
export function createActions(api: Api, dispatch: Dispatch, storage: () => Storage) {
  let toastId = 0;
  // Numbers the `!` commands run on this page.
  let bashRuns = 0;
  let showAutomated = loadShowAutomated(storage);
  let foldedTeams = loadFoldedTeams(storage);
  let usageBarHidden = loadUsageBarHidden(storage);
  let featureGroups = loadFeatureGroups(storage);
  // Until the first load succeeds, a failure means the Mac cannot be reached at all.
  let loaded = false;
  // The chats on screen, kept complete across a reconnect that cannot resume.
  const onScreen = new Set<string>();
  // The chats on screen whose last load failed, tried again after a reconnect.
  const failed = new Set<string>();
  // The project whose goals the chat list shows, loaded again after a reconnect.
  let goalsOf: string | null = null;
  // The stored events that arrived during each snapshot request in flight.
  const arriving = new Set<NestEvent[]>();
  // The last save of each pixie, and of the pixie order: the next one waits for it, so a
  // quick second edit reaches the Mac after the first and is the one that stays.
  const saving = new Map<string, Promise<unknown>>();
  // The artifact lists asked for, loaded again after a reconnect (B79).
  const artifactLists = new Map<string, ArtifactFilter>();
  // Artifacts being looked up, so cards naming the same one ask once.
  const lookups = new Map<string, Promise<void>>();
  // Versions read so far: a version never changes once saved.
  const versions = new Map<string, ArtifactContent>();
  // Open pages kept in step with their stored data (B88).
  const storageListeners = new Set<(change: ArtifactStorageChange) => void>();
  const eventListeners = new Set<(event: NestEvent) => void>();
  // Usage as pages read it, kept a minute.
  let pageUsage: { at: number; usage: Promise<PageUsage> } | null = null;

  const toast = (text: string, tone: Toast["tone"] = "ok") => {
    toastId += 1;
    dispatch({ type: "toast", toast: { id: toastId, text, tone } });
  };

  const report = (error: unknown) => {
    if (error instanceof ApiError && error.unauthorized) {
      dispatch({ type: "auth", auth: "unpaired" });
    } else {
      toast(error instanceof Error ? error.message : "Something went wrong", "error");
    }
  };

  /** Runs `call`, which never rejects, after the last one queued under `key`. */
  function inTurn<T>(key: string, call: () => Promise<T>): Promise<T> {
    const before = saving.get(key);
    const run = before === undefined ? call() : before.then(call);
    saving.set(key, run);
    void run.then(() => {
      if (saving.get(key) === run) saving.delete(key);
    });
    return run;
  }

  async function attempt<T>(call: () => Promise<T>): Promise<T | null> {
    try {
      return await call();
    } catch (error) {
      report(error);
      return null;
    }
  }

  // For suggestions while typing: a failure only means no suggestions, so no toast.
  async function quietly<T>(call: () => Promise<T>): Promise<T | null> {
    try {
      return await call();
    } catch (error) {
      if (error instanceof ApiError && error.unauthorized) {
        dispatch({ type: "auth", auth: "unpaired" });
      }
      return null;
    }
  }

  /** A pixie file; one that does not exist yet reads as empty, with no hash to name. */
  async function pixieFile(id: string, name: string): Promise<FileState> {
    try {
      return await api.pixieFile(id, name);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return { text: "", hash: null };
      throw error;
    }
  }

  /**
   * Applies a snapshot, then again the stored events that arrived while it loaded: the
   * snapshot may be older than they are. Transcripts already hold them without duplicates.
   */
  async function snapshot<T>(fetch: () => Promise<T>, apply: (loaded: T) => void): Promise<void> {
    const arrived: NestEvent[] = [];
    arriving.add(arrived);
    try {
      apply(await fetch());
      if (arrived.length > 0) dispatch({ type: "replayed", events: arrived });
    } finally {
      arriving.delete(arrived);
    }
  }

  async function loadPixies(): Promise<void> {
    const [pixies, teams] = await Promise.all([
      quietly(() => api.pixies()),
      quietly(() => api.teams()),
    ]);
    if (pixies !== null) dispatch({ type: "pixies", pixies });
    if (teams !== null) dispatch({ type: "teams", teams });
    // Read ones too: a report card in a pixie's chat shows any report (B42).
    const reports = await quietly(() => api.pixieReports(false));
    if (reports !== null) dispatch({ type: "reports", reports });
  }

  /** Every chat's pixies, and the agents of the chats at work, for the chat list (B46). */
  async function loadChatAgents(sessions: Session[]): Promise<void> {
    const groups = await quietly(() => api.pixieGroups());
    if (groups !== null) dispatch({ type: "pixieGroups", groups });
    const working = sessions.filter((s) => BUSY.has(s.state));
    await Promise.all(
      working.map(({ id }) =>
        quietly(() =>
          snapshot(
            () => api.session(id),
            ({ tasks, agents, background }) => {
              dispatch({ type: "tracking", id, tracking: { tasks, agents, background } });
            },
          ),
        ),
      ),
    );
  }

  /** A project's goals (B47); a failure keeps what the live events showed. */
  async function loadGoals(repo: string): Promise<void> {
    goalsOf = repo;
    await quietly(() =>
      snapshot(
        () => api.goals(repo),
        (goals) => {
          dispatch({ type: "goals", repo, goals });
        },
      ),
    );
  }

  /** Each engine's models besides Claude's; one the Mac cannot give keeps its last list. */
  async function loadOtherModels(providers: ProviderInfo[]): Promise<void> {
    for (const { name } of providers.filter((p) => p.name !== CLAUDE)) {
      const list = await quietly(() => api.models(name));
      if (list !== null) dispatch({ type: "modelList", provider: name, list });
    }
  }

  /** The engines and their models; `refresh` asks the engines for their login now. */
  async function loadProviders(refresh = false): Promise<void> {
    const found = await quietly(() => api.providers(refresh));
    if (found === null) return;
    dispatch({ type: "providers", providers: found.providers });
    await loadOtherModels(found.providers);
  }

  async function loadUnseenArtifacts(): Promise<void> {
    const found = await quietly(() => api.artifactsUnseen());
    if (found !== null) dispatch({ type: "unseenArtifacts", unseen: found.unseen });
  }

  /** A list of artifacts, kept live from then on; false when the Mac cannot answer. */
  async function loadArtifacts(filter: ArtifactFilter): Promise<boolean> {
    artifactLists.set(filterKey(filter), filter);
    const done = await quietly(() =>
      snapshot(
        () => api.artifacts(filter),
        (artifacts) => {
          dispatch({ type: "artifacts", filter, artifacts });
        },
      ).then(() => true),
    );
    return done !== null;
  }

  async function reloadArtifacts(): Promise<void> {
    await Promise.all([loadUnseenArtifacts(), ...[...artifactLists.values()].map(loadArtifacts)]);
  }

  async function lookUpArtifact(id: string): Promise<void> {
    try {
      dispatch({ type: "artifact", artifact: await api.artifact(id) });
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        dispatch({ type: "artifactRemoved", id });
      } else if (error instanceof ApiError && error.unauthorized) {
        dispatch({ type: "auth", auth: "unpaired" });
      }
    }
  }

  async function loadClaudeChats(): Promise<void> {
    const chats = await attempt(() => api.claudeChats(showAutomated));
    if (chats !== null) dispatch({ type: "claudeChats", chats });
  }

  // `stale`: streamed text and thinking may have missed their end, so a chat that is no
  // longer working drops them.
  async function fetchChat(id: string, stale = false): Promise<void> {
    const done = await attempt(() =>
      snapshot(
        () => Promise.all([api.session(id), api.sessionEvents(id)]),
        ([found, events]) => {
          // The detail is a session too; its task list and agents go to tracking.
          dispatch({ type: "session", session: found });
          const { tasks, agents, background } = found;
          dispatch({ type: "tracking", id, tracking: { tasks, agents, background } });
          dispatch({ type: "queued", id, queued: found.queued });
          // A chat closed meanwhile keeps no transcript.
          if (onScreen.has(id)) dispatch({ type: "transcriptLoaded", id, events });
          if (stale && !WORKING.has(found.state)) dispatch({ type: "liveCleared", id });
        },
      ),
    );
    if (done === null && onScreen.has(id)) {
      failed.add(id);
      dispatch({ type: "historyFailed", id });
    } else {
      failed.delete(id);
    }
  }

  async function load(): Promise<void> {
    let sessions: Session[] = [];
    try {
      await snapshot(
        () =>
          Promise.all([
            api.repos(),
            api.sessions(false),
            api.sessions(true),
            api.approvals(),
            api.claudeChats(showAutomated),
          ]),
        ([repos, open, archived, approvals, chats]) => {
          dispatch({ type: "loaded", repos, sessions: [...open, ...archived], approvals });
          dispatch({ type: "claudeChats", chats });
          sessions = open;
        },
      );
      loaded = true;
      await loadUnseenArtifacts();
      // Apart, so the app still opens when only the pixies cannot load.
      await loadPixies();
      await loadChatAgents(sessions);
    } catch (error) {
      if (error instanceof ApiError && error.unauthorized) {
        dispatch({ type: "auth", auth: "unpaired" });
      } else if (!loaded) {
        dispatch({ type: "auth", auth: "offline" });
      } else {
        toast("Could not refresh from your Mac", "error");
      }
    }
  }

  const settings = settingsActions(api, { dispatch, attempt, quietly, toast });

  return {
    ...settings,
    /** This device's id, when it was paired since B81. */
    toast,
    dismissToast: () => {
      dispatch({ type: "toast", toast: null });
    },
    load,

    loadPixies,
    loadGoals,
    /** The daemon fills in the defaults the body leaves out (D104). */
    async createPixie(body: CreatePixieBody): Promise<Pixie | null> {
      const created = await attempt(() => api.createPixie(body));
      if (created !== null) dispatch({ type: "pixie", pixie: created });
      return created;
    },
    /** Every skill a pixie may be given (B85); null, after a toast, when it cannot load. */
    pixieSkills(): Promise<PixieSkill[] | null> {
      return attempt(() => api.pixieSkills());
    },
    async updatePixie(id: string, body: UpdatePixieBody): Promise<boolean> {
      const updated = await inTurn(`pixie:${id}`, () => attempt(() => api.updatePixie(id, body)));
      if (updated === null) return false;
      dispatch({ type: "pixie", pixie: updated });
      return true;
    },
    async deletePixie(id: string): Promise<boolean> {
      const done = await attempt(() => api.deletePixie(id).then(() => true));
      if (done === null) return false;
      dispatch({ type: "pixieRemoved", id });
      return true;
    },
    /** `ids` names every pixie once; a refused order reads the list again. */
    async reorderPixies(ids: string[]): Promise<boolean> {
      const list = await inTurn("order", () => attempt(() => api.reorderPixies(ids)));
      if (list === null) {
        await loadPixies();
        return false;
      }
      dispatch({ type: "pixies", pixies: list });
      return true;
    },
    async duplicatePixie(id: string): Promise<Pixie | null> {
      const copy = await attempt(() => api.duplicatePixie(id));
      if (copy !== null) dispatch({ type: "pixie", pixie: copy });
      return copy;
    },
    async createTeam(name: string): Promise<PixieTeam | null> {
      const created = await attempt(() => api.createTeam({ name }));
      if (created !== null) dispatch({ type: "team", team: created });
      return created;
    },
    async updateTeam(id: string, body: UpdateTeamBody): Promise<boolean> {
      const updated = await attempt(() => api.updateTeam(id, body));
      if (updated === null) return false;
      dispatch({ type: "team", team: updated });
      return true;
    },
    /** Resolves to why the Mac refused the handle (409 taken, 422 invalid), else null. */
    async setTeamHandle(id: string, handle: string): Promise<string | null> {
      try {
        dispatch({ type: "team", team: await api.updateTeam(id, { handle }) });
      } catch (error) {
        if (error instanceof ApiError && (error.status === 409 || error.status === 422)) {
          return error.message;
        }
        report(error);
      }
      return null;
    },
    async deleteTeam(id: string): Promise<boolean> {
      const done = await attempt(() => api.deleteTeam(id).then(() => true));
      if (done === null) return false;
      dispatch({ type: "teamRemoved", id });
      return true;
    },
    /** Remembered on this device only. */
    setTeamFolded(id: string, folded: boolean): void {
      foldedTeams = [...foldedTeams.filter((each) => each !== id), ...(folded ? [id] : [])];
      saveFoldedTeams(storage, foldedTeams);
      dispatch({ type: "teamFolded", id, folded });
    },
    async sendToPixie(id: string, text: string): Promise<Session | null> {
      const sent = await attempt(() => api.sendToPixie(id, text));
      if (sent !== null) dispatch({ type: "session", session: sent });
      return sent;
    },
    async resetPixie(id: string): Promise<boolean> {
      const pixie = await attempt(() => api.resetPixie(id));
      if (pixie === null) return false;
      dispatch({ type: "pixie", pixie });
      return true;
    },
    /** Resolves to why the Mac refused the slug (409 taken, 422 invalid), else null. */
    async setPixieSlug(id: string, slug: string): Promise<string | null> {
      try {
        dispatch({ type: "pixie", pixie: await api.updatePixie(id, { slug }) });
      } catch (error) {
        if (error instanceof ApiError && (error.status === 409 || error.status === 422)) {
          return error.message;
        }
        report(error);
      }
      return null;
    },
    /** A file that does not exist yet reads as empty, with no hash to name. */
    async readPixieFile(id: string, name: string): Promise<FileState | null> {
      return attempt(() => pixieFile(id, name));
    },
    /** As readPixieFile, for a count on screen: no toast when the Mac cannot answer. */
    async peekPixieFile(id: string, name: string): Promise<FileState | null> {
      return quietly(() => pixieFile(id, name));
    },
    /** A stale write resolves to the file as it is now, for the user to choose. */
    async savePixieFile(
      id: string,
      name: string,
      text: string,
      hash: string | null,
    ): Promise<FileSave | null> {
      try {
        return { saved: await api.savePixieFile(id, name, text, hash) };
      } catch (error) {
        if (error instanceof ApiError && error.code === STALE_FILE) {
          return { stale: currentFile(error.data) };
        }
        report(error);
        return null;
      }
    },
    async pixieNotes(id: string): Promise<string[]> {
      return (await quietly(() => api.pixieNotes(id))) ?? [];
    },
    /** The pixie's activity log, newest first; null when the Mac cannot answer. */
    async pixieActivity(id: string): Promise<PixieActivity[] | null> {
      return quietly(() => api.pixieActivity(id));
    },
    async searchPixie(id: string, query: string): Promise<PixieSearchHit[]> {
      return (await quietly(() => api.searchPixie(id, query))) ?? [];
    },
    /** The pixie's habits, kept live from then on; null when the Mac cannot answer. */
    async loadHabits(pixieId: string): Promise<Habit[] | null> {
      const habits = await quietly(() => api.habits(pixieId));
      if (habits !== null) dispatch({ type: "habits", pixieId, habits });
      return habits;
    },
    async createHabit(pixieId: string, body: HabitBody): Promise<Habit | null> {
      const created = await attempt(() => api.createHabit(pixieId, body));
      if (created !== null) dispatch({ type: "habit", habit: created });
      return created;
    },
    async updateHabit(pixieId: string, id: string, body: UpdateHabitBody): Promise<boolean> {
      const updated = await attempt(() => api.updateHabit(pixieId, id, body));
      if (updated === null) return false;
      dispatch({ type: "habit", habit: updated });
      return true;
    },
    async deleteHabit(pixieId: string, id: string): Promise<boolean> {
      const done = await attempt(() => api.deleteHabit(pixieId, id).then(() => true));
      if (done === null) return false;
      dispatch({ type: "habitRemoved", pixieId, id });
      return true;
    },
    /** Run now: queued at once, whatever the usage. */
    async runHabit(pixieId: string, id: string): Promise<boolean> {
      const run = await attempt(() => api.runHabit(pixieId, id));
      if (run === null) return false;
      dispatch({ type: "habitRun", run });
      toast("Run queued");
      return true;
    },
    /** A habit's history, kept live from then on; null when the Mac cannot answer. */
    async loadHabitRuns(pixieId: string, habitId: string): Promise<HabitRun[] | null> {
      const runs = await quietly(() => api.habitRuns(pixieId, habitId));
      if (runs !== null) dispatch({ type: "habitRuns", habitId, runs });
      return runs;
    },
    async readReport(id: string): Promise<boolean> {
      const done = await attempt(() => api.readReport(id).then(() => true));
      if (done === null) return false;
      dispatch({ type: "reportsRead", ids: [id], at: new Date().toISOString() });
      return true;
    },
    /** Every report of the pixie read, as when its page opens; no toast on failure. */
    async readPixieReports(pixieId: string, unread: string[]): Promise<void> {
      const done = await quietly(() => api.readPixieReports(pixieId).then(() => true));
      if (done !== null) {
        dispatch({ type: "reportsRead", ids: unread, at: new Date().toISOString() });
      }
    },

    /** A live event from the socket. */
    receive(event: NestEvent): void {
      if (event.id !== null) {
        for (const arrived of arriving) arrived.push(event);
      }
      dispatch({ type: "event", event });
      for (const listener of [...eventListeners]) listener(event);
      if (event.type === "artifact.storage") {
        const change = storageChangeOf(event.payload);
        if (change !== null) for (const listener of [...storageListeners]) listener(change);
      }
      if (event.type === "usage.warning") toast(warningText(event.payload), "info");
      if (event.type === "extensions.updated") void settings.extensionsChanged();
      // Whether Codex can run chats follows its login.
      if (event.type === "account.codex") void loadProviders();
      if (event.type === "configuration.changed") void settings.configurationChanged(event.payload);
    },

    retry: () => {
      dispatch({ type: "auth", auth: "loading" });
      return load();
    },

    /** Resolves to an error message for the pairing screen, or null once paired. */
    async pair(code: string, deviceName: string): Promise<string | null> {
      try {
        await api.redeem(code, deviceName);
      } catch (error) {
        if (error instanceof ApiError && error.status === 429) {
          return "Too many attempts. Wait a minute and try again.";
        }
        if (error instanceof ApiError && error.status === 400) {
          return "That code is wrong or has expired.";
        }
        return "Could not reach your Mac.";
      }
      dispatch({ type: "auth", auth: "loading" });
      await load();
      return null;
    },

    async openChat(id: string): Promise<void> {
      onScreen.add(id);
      dispatch({ type: "transcriptOpened", id });
      await fetchChat(id);
    },

    /** The chat left the screen; its transcript is fetched again when it opens. */
    closeChat(id: string): void {
      onScreen.delete(id);
      failed.delete(id);
      dispatch({ type: "transcriptClosed", id });
    },

    /** Loads again an open chat whose history could not be loaded. */
    reloadChat: (id: string) => fetchChat(id),

    /** After a resumed reconnect: the chats on screen whose history failed to load. */
    async reloadFailed(): Promise<void> {
      await Promise.all([...failed].map((id) => fetchChat(id)));
    },

    /**
     * After a reconnect that could not resume from a cursor, events may have been missed:
     * reload the snapshots and the chats on screen. Stored events merge without duplicates.
     */
    async resync(): Promise<void> {
      const goals = goalsOf === null ? [] : [loadGoals(goalsOf)];
      const lists = [...artifactLists.values()].map(loadArtifacts);
      await Promise.all([
        load(),
        ...goals,
        ...lists,
        ...[...onScreen].map((id) => fetchChat(id, true)),
      ]);
    },

    async resolve(approval: Approval, body: ResolveBody, done: string): Promise<boolean> {
      const resolved = await attempt(() => api.resolveApproval(approval.id, body));
      if (resolved === null) return false;
      dispatch({ type: "approval", approval: resolved });
      const declined = body.behavior === "deny" || body.decision === "keep_planning";
      toast(done, declined ? "info" : "ok");
      return true;
    },

    /**
     * "refused": the daemon said no (409), for example for a branch that moved. The session
     * is fetched again so the screen shows why, then the reason. A push address to confirm
     * comes back for the screen to ask about instead.
     */
    async approveReview(review: Approval, body: ApproveBody, done: string): Promise<ApproveResult> {
      let updated: Session;
      try {
        updated = await api.approve(review.session_id, body);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 409)) {
          report(error);
          return "failed";
        }
        const found = await attempt(() => api.session(review.session_id));
        if (found !== null) dispatch({ type: "session", session: found });
        if (REMOTE_CODES.includes(error.code)) return { remote: remotePrompt(error.data) };
        toast(
          error.code === HEAD_CHANGED
            ? "The branch moved since you looked. Check the changes again."
            : error.message,
          "error",
        );
        return "refused";
      }
      dispatch({ type: "session", session: updated });
      dispatch({ type: "approval", approval: { ...review, status: "resolved" } });
      toast(done);
      return "approved";
    },

    async feedback(review: Approval, text: string): Promise<boolean> {
      const updated = await attempt(() => api.feedback(review.session_id, text));
      if (updated === null) return false;
      dispatch({ type: "session", session: updated });
      dispatch({ type: "approval", approval: { ...review, status: "superseded" } });
      toast("Feedback sent");
      return true;
    },

    /** Where the project's new chats work: a worktree, in place, or the agent default (null). */
    async setWorktreeDefault(repo: RepoConfig, value: boolean | null): Promise<boolean> {
      const updated = await attempt(() => api.updateRepo(repo.name, { default: value }));
      if (updated === null) return false;
      dispatch({ type: "repo", repo: updated });
      return true;
    },

    /**
     * Unregisters the project; its folder stays. Its chats (`sessions`) are deleted first,
     * as the daemon refuses to remove a project that still has any.
     */
    async removeRepo(name: string, sessions: string[]): Promise<boolean> {
      const done = await attempt(async () => {
        await api.removeRepo(name, sessions.length > 0);
        return true;
      });
      if (done === null) return false;
      for (const id of sessions) dispatch({ type: "sessionRemoved", id });
      dispatch({ type: "repoRemoved", name });
      toast(`Removed ${name}`, "info");
      return true;
    },

    /**
     * What rewinding to before the user message `eventId` would do. `quiet`: a failure is
     * not reported, for a check the user did not ask for.
     */
    rewindPreview(
      sessionId: string,
      eventId: number,
      restore: Restore,
      quiet = false,
    ): Promise<RewindPreview | null> {
      const call = () => api.rewindPreview(sessionId, eventId, restore);
      return quiet ? quietly(call) : attempt(call);
    },

    /**
     * Restores the files, the conversation or both to before the user message `eventId`.
     * A conversation rewind's `session.rewound` event takes the messages out of the chat.
     */
    async rewind(
      sessionId: string,
      eventId: number,
      restore: Restore,
    ): Promise<RewindReply | null> {
      const done = await attempt(() => api.rewind(sessionId, eventId, restore));
      if (done !== null) toast(RESTORED[restore]);
      return done;
    },

    /**
     * Forks the chat from the user message `eventId` into a new chat, whose draft gets that
     * message; the screen then opens it.
     */
    async fork(sessionId: string, eventId: number): Promise<ForkReply | null> {
      const forked = await attempt(() => api.fork(sessionId, eventId));
      if (forked === null) return null;
      dispatch({ type: "session", session: forked.session });
      dispatch({
        type: "draftFilled",
        key: draftKey({ session: forked.session.id }),
        text: forked.text,
        files: asDraftFiles(forked.attachments),
      });
      return forked;
    },

    /**
     * Squash-merges the pull request; the daemon then closes the chat and its worktree. The
     * branch stays unless `deleteBranch` (B96, B102).
     */
    async merge(approval: Approval, number: number, deleteBranch = false): Promise<boolean> {
      const updated = await attempt(() =>
        api.merge(approval.session_id, { method: "squash", delete_branch: deleteBranch }),
      );
      if (updated === null) return false;
      dispatch({ type: "session", session: updated });
      dispatch({ type: "approval", approval: { ...approval, status: "resolved" } });
      toast(`Merged #${String(number)}`);
      return true;
    },

    /**
     * Asks the agent to fix the failing checks, in the same chat. The daemon reads their
     * logs with its own GitHub login (the agent has none) and sends them in.
     */
    async sendCiFailure(session: Session): Promise<boolean> {
      const sent = await attempt(async () => {
        await api.ciFeedback(session.id);
        return true;
      });
      if (sent === null) return false;
      // The session's events show the agent starting on it.
      toast("Sent to the agent with the checks' logs");
      return true;
    },

    /** Stops a stuck chat's turn and starts it again with a nudge to change course. */
    async nudge(sessionId: string, details: string): Promise<boolean> {
      const text = nudgeText(details);
      const sent = await attempt(() => api.sendMessage(sessionId, text, [], true));
      if (sent === null) return false;
      toast("Nudge sent");
      return true;
    },

    /** Chat titles and messages across projects; null when the Mac could not search. */
    search(query: string): Promise<SearchResults | null> {
      return attempt(() => api.search(query));
    },

    /**
     * For a new chat's place (B55): the project read again, for the branch checked out in
     * its folder now. Quiet: without it the choice shows the branch the list had.
     */
    async refreshRepo(name: string): Promise<void> {
      const fresh = await quietly(() => api.repo(name));
      if (fresh !== null) dispatch({ type: "repo", repo: fresh });
    },

    /** The pixie, or the team with its members, leaves the chat's group (B46). */
    async sendAway(sessionId: string, body: SendAwayBody): Promise<boolean> {
      const group = await attempt(() => api.sendAway(sessionId, body));
      if (group === null) return false;
      dispatch({ type: "pixieGroup", id: sessionId, group });
      return true;
    },

    /** Every call to the pixie in the chat, newest first, with its work (B46). */
    pixieCalls: (sessionId: string, pixieId: string): Promise<CallWork[] | null> =>
      attempt(() => api.pixieCalls(sessionId, pixieId)),

    /** A subagent's transcript so far (B46). */
    agentTranscript: (sessionId: string, toolUseId: string): Promise<AgentWork | null> =>
      attempt(() => api.agentTranscript(sessionId, toolUseId)),

    async create(body: CreateSessionBody): Promise<Session | null> {
      const created = await attempt(() => api.createSession(body));
      if (created !== null) dispatch({ type: "session", session: created });
      return created;
    },

    /**
     * Sends a message; while a turn runs the daemon queues it, and the `session.queued`
     * event shows it under the transcript.
     */
    async send(id: string, text: string, attachmentIds: string[]): Promise<SendResult> {
      try {
        await api.sendMessage(id, text, attachmentIds);
        return "sent";
      } catch (error) {
        if (error instanceof ApiError && error.code === OPEN_ELSEWHERE) return "elsewhere";
        if (error instanceof ApiError && error.code === PIXIE_IN_TEAM) {
          return { refused: error.message };
        }
        report(error);
        return "failed";
      }
    },

    /**
     * Stops one background task or subagent; its end arrives as a `session.agent_task`
     * event. A task that already finished gets its chat fetched again.
     */
    async stopTask(sessionId: string, taskId: string): Promise<StopResult> {
      try {
        await api.stopTask(sessionId, taskId);
        return "sent";
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) return "closed";
        if (!(error instanceof ApiError && error.status === 404)) {
          report(error);
          return "failed";
        }
      }
      await fetchChat(sessionId);
      return "gone";
    },

    /**
     * Takes back a message Claude has not read. One it already read (or the Mac no longer
     * has) leaves the list too: it shows in the transcript where Claude read it.
     */
    async cancelQueued(sessionId: string, queuedId: string): Promise<RemoveResult> {
      let result: RemoveResult = "removed";
      try {
        await api.cancelQueued(sessionId, queuedId);
      } catch (error) {
        const taken =
          error instanceof ApiError && (error.status === 404 || error.code === MESSAGE_TAKEN);
        if (!taken) {
          report(error);
          return "failed";
        }
        toast("Claude already read this message", "info");
        result = "taken";
      }
      dispatch({ type: "queuedRemoved", id: sessionId, queuedId });
      return result;
    },

    /** Stops the running turn, if any, and starts the pending message next. */
    async sendNow(sessionId: string, queuedId: string): Promise<boolean> {
      const done = await attempt(async () => {
        await api.sendNow(sessionId, queuedId);
        return true;
      });
      return done !== null;
    },

    /**
     * Ends a chat's usage limit pause now (B78). One that already ended, as when the reset
     * came meanwhile, is fetched again instead of shown as an error.
     */
    async resumeLimit(id: string): Promise<boolean> {
      try {
        dispatch({ type: "session", session: await api.resumeLimit(id) });
        return true;
      } catch (error) {
        if (!(error instanceof ApiError && error.code === NOT_PAUSED)) {
          report(error);
          return false;
        }
      }
      await fetchChat(id);
      return true;
    },

    /**
     * Runs a `!` command in the chat's folder (B59). Its row shows at once; what it printed
     * goes to Claude with the next message. A refusal shows in the row.
     */
    async runShell(sessionId: string, command: string): Promise<void> {
      bashRuns += 1;
      const runId = bashRuns;
      dispatch({ type: "bashStarted", id: sessionId, runId, command });
      try {
        const result = await api.shell(sessionId, command);
        dispatch({ type: "bashFinished", id: sessionId, runId, result });
      } catch (error) {
        if (error instanceof ApiError && error.unauthorized) report(error);
        const message = (error as Error).message;
        dispatch({ type: "bashFinished", id: sessionId, runId, error: message });
      }
    },

    /** The chat's `!` commands went to Claude with a message, or are done with. */
    bashSent(sessionId: string, runIds: number[]): void {
      dispatch({ type: "bashSent", id: sessionId, runIds });
    },

    /** Saves a `#` memory to the project's or the user's CLAUDE.md (B59). */
    async remember(
      sessionId: string,
      text: string,
      scope: MemoryScope,
    ): Promise<MemoryReply | null> {
      const saved = await attempt(() => api.remember(sessionId, text, scope));
      if (saved !== null) toast(`Saved to ${scope} memory: ${saved.path}`);
      return saved;
    },

    /** A stored image, such as one in a tool result; null when it cannot be had. */
    attachment(id: string): Promise<Blob | null> {
      return quietly(() => api.attachment(id));
    },

    /** Puts a message taken back into a draft, replacing it. */
    fillDraft(key: string, text: string, files: Attachment[]): void {
      dispatch({ type: "draftFilled", key, text, files });
    },

    /** The chat's slash commands, or the project's last known ones before the chat exists. */
    commands(target: { session: string } | { repo: string }): Promise<CommandList | null> {
      return quietly(() =>
        "session" in target ? api.sessionCommands(target.session) : api.repoCommands(target.repo),
      );
    },

    /** Repo files for an @ mention, best matches first. */
    async files(sessionId: string, query: string): Promise<string[]> {
      const found = await quietly(() => api.files(sessionId, query));
      return found?.files ?? [];
    },

    loadClaudeChats,

    /** Lists chats programs started through an Agent SDK too, on this device. */
    async setShowAutomated(on: boolean): Promise<void> {
      showAutomated = on;
      saveShowAutomated(storage, on);
      dispatch({ type: "showAutomated", on });
      await loadClaudeChats();
    },

    claudeChatEvents(id: string): Promise<NestEvent[] | null> {
      return attempt(() => api.claudeChatEvents(id));
    },

    /** Continues the chat in Nest: it becomes a session and leaves the Claude Code list. */
    async adoptClaudeChat(chat: ClaudeChat): Promise<Session | null> {
      const session = await attempt(() => api.adoptClaudeChat(chat.id));
      if (session === null) return null;
      dispatch({ type: "session", session });
      dispatch({ type: "claudeChatRemoved", id: chat.id });
      return session;
    },

    /** Archives or restores a Claude Code chat in Nest; Claude Code never sees it (D040). */
    async archiveClaudeChat(chat: ClaudeChat, archived: boolean): Promise<boolean> {
      const updated = await attempt(() => api.setClaudeChatArchived(chat.id, archived));
      if (updated === null) return false;
      dispatch({ type: "claudeChat", chat: updated });
      toast(`${archived ? "Archived" : "Unarchived"} ${chat.title}`);
      return true;
    },

    async interrupt(id: string): Promise<boolean> {
      const done = await attempt(async () => {
        await api.interrupt(id);
        return true;
      });
      if (done) toast("Interrupted", "info");
      return done === true;
    },

    async update(id: string, body: UpdateSessionBody, done?: string): Promise<boolean> {
      const updated = await attempt(() => api.updateSession(id, body));
      if (updated === null) return false;
      dispatch({ type: "session", session: updated });
      if (done !== undefined) toast(done);
      return true;
    },

    async remove(session: Session): Promise<boolean> {
      const done = await attempt(async () => {
        await api.deleteSession(session.id);
        return true;
      });
      if (!done) return false;
      dispatch({ type: "sessionRemoved", id: session.id });
      toast(`Deleted ${session.title}`, "info");
      return true;
    },

    setDraftText(key: string, text: string): void {
      dispatch({ type: "draftText", key, text });
    },

    removeDraftFile(key: string, fileId: string): void {
      dispatch({ type: "draftFileRemoved", key, fileId });
    },

    /**
     * Takes what was sent out of the draft, keeping anything added while it was sending,
     * under `to` when the message created a new chat.
     */
    draftSent(key: string, text: string, fileIds: string[], to?: string): void {
      dispatch({ type: "draftSent", key, text, fileIds, ...(to === undefined ? {} : { to }) });
    },

    /** Uploads a file into the draft it was chosen for, even if another chat is open by then. */
    async attachToDraft(key: string, file: File): Promise<Attachment | null> {
      const uploaded = await attempt(() => api.uploadAttachment(file));
      if (uploaded !== null) dispatch({ type: "draftFileAdded", key, file: uploaded });
      return uploaded;
    },

    diff(sessionId: string): Promise<SessionDiff | null> {
      return attempt(() => api.diff(sessionId));
    },

    /** Shows another usage period; `date` is a day in it, null for the current one. */
    viewUsage(unit: PeriodUnit, date: string | null): void {
      dispatch({ type: "usageView", unit, date });
    },

    /** Loads the usage period of `unit` holding `date` (YYYY-MM-DD). */
    async loadUsage(unit: PeriodUnit, date: string): Promise<void> {
      const period = await attempt(() => api.usagePeriod(unit, date));
      if (period !== null) dispatch({ type: "usagePeriod", period });
    },

    async loadNotifications(): Promise<void> {
      const settings = await attempt(() => api.notificationSettings());
      if (settings !== null) dispatch({ type: "notifications", notifications: settings });
    },

    loadArtifacts,
    /** After a resumed reconnect: the badge and the artifact lists asked for. */
    reloadArtifacts,

    /** Fetches an artifact not known yet; one the Mac no longer has is marked gone. */
    loadArtifact(id: string): Promise<void> {
      const running = lookups.get(id);
      if (running !== undefined) return running;
      const lookup = lookUpArtifact(id).finally(() => {
        lookups.delete(id);
      });
      lookups.set(id, lookup);
      return lookup;
    },

    /** One version's content; null when it cannot be read now. */
    async artifactVersion(id: string, version: number): Promise<ArtifactContent | null> {
      const key = `${id}:${String(version)}`;
      const known = versions.get(key);
      if (known !== undefined) return known;
      const found = await quietly(() => api.artifactVersion(id, version));
      if (found !== null) versions.set(key, found);
      return found;
    },

    /** Its latest version was shown; the badge follows from the event. */
    async markArtifactSeen(id: string): Promise<void> {
      const marked = await quietly(() => api.markArtifactSeen(id));
      if (marked !== null) dispatch({ type: "artifact", artifact: marked });
    },

    /** What the artifact's pages stored; null when it cannot be read now. */
    artifactStorage(id: string): Promise<ArtifactStorage | null> {
      return quietly(() => api.artifactStorage(id));
    },

    /** A page's write; a refusal (413 over a cap) is the caller's to report. */
    writeArtifactStorage(id: string, write: ArtifactStorageWrite): Promise<{ size: number }> {
      return api.writeArtifactStorage(id, write);
    },

    async clearArtifactStorage(id: string): Promise<void> {
      await api.clearArtifactStorage(id);
    },

    /** Hears every event until the returned call. */
    onEvent(listener: (event: NestEvent) => void): () => void {
      eventListeners.add(listener);
      return () => {
        eventListeners.delete(listener);
      };
    },

    /**
     * Usage for a page: the limits, today's and this week's totals, as the Usage page
     * shows them. Read again after a minute, or at once when `fresh`; a failure is thrown.
     */
    pageUsage(fresh = false): Promise<PageUsage> {
      const now = Date.now();
      if (fresh || pageUsage === null || now - pageUsage.at > USAGE_FRESH_MS) {
        const usage = readPageUsage(api, new Date(now));
        pageUsage = { at: now, usage };
        usage.catch(() => {
          if (pageUsage?.usage === usage) pageUsage = null;
        });
      }
      return pageUsage.usage;
    },

    /** Today's asks of the artifact's pages; null when they cannot be read now. */
    askStatus(id: string): Promise<AskStatus | null> {
      return quietly(() => api.askStatus(id));
    },

    /** Claude's answer to a page's question; a refusal is the caller's to report. */
    askArtifact(
      id: string,
      question: { prompt: string; system?: string },
    ): Promise<ArtifactAnswer> {
      return api.askArtifact(id, question);
    },

    /** Hears every `artifact.storage` change until the returned call. */
    onArtifactStorage(listener: (change: ArtifactStorageChange) => void): () => void {
      storageListeners.add(listener);
      return () => {
        storageListeners.delete(listener);
      };
    },

    /**
     * The user's edit of a document as its new version, the artifact read again so its
     * latest version shows at once. A refusal is the caller's to report (the page says it).
     */
    async saveArtifactDocument(
      id: string,
      content: string,
      baseVersion: number,
    ): Promise<ArtifactVersion> {
      const saved = await api.saveArtifactVersion(id, { content, base_version: baseVersion });
      await lookUpArtifact(id);
      return saved;
    },

    async deleteArtifact(id: string): Promise<boolean> {
      const done = await attempt(() => api.deleteArtifact(id).then(() => true));
      if (done === null) return false;
      dispatch({ type: "artifactRemoved", id });
      toast("Artifact deleted");
      return true;
    },

    /** Shows the change at once and puts `previous` back if the Mac refuses it. */
    async saveNotifications(
      next: NotificationSettings,
      previous: NotificationSettings,
    ): Promise<void> {
      dispatch({ type: "notifications", notifications: next });
      const saved = await attempt(() => api.saveNotificationSettings(next));
      dispatch({ type: "notifications", notifications: saved ?? previous });
    },

    /** Resolves to the device's push status afterwards, or null if something failed. */
    async enablePush(env: PushEnv): Promise<PushStatus | null> {
      const status = await attempt(() => enablePush(env, api));
      if (status === "on") toast("Notifications are on");
      return status;
    },

    /** Quiet, as nobody asked for it: a failure only means the next launch tries again. */
    async refreshPush(env: PushEnv): Promise<void> {
      await quietly(() => refreshPush(env, api));
    },

    async disablePush(env: PushEnv): Promise<PushStatus | null> {
      const status = await attempt(() => disablePush(env, api));
      if (status !== null) toast("Notifications are off on this device", "info");
      return status;
    },

    async testPush(): Promise<void> {
      const report = await attempt(() => api.testPush());
      if (report === null) return;
      if (report.sent > 0) toast("Test notification sent");
      else toast("The test notification could not be delivered", "error");
    },

    /** Asks the Mac to check an engine's usage now (Claude's by default); resolves when the numbers are in. */
    async refreshUsage(provider: string = CLAUDE): Promise<void> {
      try {
        if (provider === CLAUDE) {
          dispatch({ type: "limits", limits: await api.refreshUsage() });
        } else {
          const limits = await api.refreshEngineUsage(provider);
          dispatch({ type: "engineLimits", provider, limits });
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 429) {
          toast("Usage was refreshed moments ago", "info");
        } else {
          report(error);
        }
      }
    },

    /**
     * Asks the Mac to restart Nest, then waits until it answers again: "back", "timeout"
     * when it never does, or null when the request itself failed (shown as a toast). The
     * first check waits, as the daemon answers the request before it exits.
     */
    async restartService(): Promise<"back" | "timeout" | null> {
      if ((await attempt(() => api.restartService())) === null) return null;
      for (let check = 0; check < RESTART_POLLS; check += 1) {
        await new Promise((resolve) => setTimeout(resolve, RESTART_POLL_MS));
        try {
          await api.health();
          return "back";
        } catch {
          // Still restarting.
        }
      }
      return "timeout";
    },

    /** The connectors alone, for `/mcp` in a chat (B59). */
    async loadConnectors(): Promise<void> {
      const connectors = await attempt(() => api.connectors());
      if (connectors !== null) dispatch({ type: "connectors", connectors });
    },

    async loadAccount(): Promise<void> {
      await attempt(async () => {
        const [connectors, limits, account] = await Promise.all([
          api.connectors(),
          api.usageLimits(),
          api.account(),
        ]);
        dispatch({ type: "connectors", connectors });
        dispatch({ type: "limits", limits });
        dispatch({ type: "account", account });
      });
    },

    /**
     * The engines, Claude Code's models, the agent defaults, then the other engines' models,
     * for the model menus and the Agents page. Quiet: without them the menus keep working
     * with fewer choices, and a part the Mac cannot give keeps what it had.
     */
    async loadChoices(): Promise<void> {
      const [found, list, defaults] = await Promise.all([
        quietly(() => api.providers(false)),
        quietly(() => api.models()),
        quietly(() => api.agentDefaults()),
      ]);
      if (found !== null) dispatch({ type: "providers", providers: found.providers });
      if (list !== null) dispatch({ type: "modelList", provider: CLAUDE, list });
      if (defaults !== null) dispatch({ type: "agentDefaults", defaults });
      if (found !== null) await loadOtherModels(found.providers);
    },

    loadProviders,

    /** The other engines' usage windows (B91), quietly: one the Mac cannot give keeps its last. */
    async loadEngineLimits(): Promise<void> {
      for (const provider of OTHER_ENGINES) {
        const limits = await quietly(() => api.engineLimits(provider));
        if (limits !== null) dispatch({ type: "engineLimits", provider, limits });
      }
    },

    /** The Features groups opened or closed by hand (B103), by id. */
    featureGroups(): Record<string, boolean> {
      return featureGroups;
    },

    /** Remembered on this device only. */
    setFeatureGroup(id: string, open: boolean): void {
      featureGroups = { ...featureGroups, [id]: open };
      saveFeatureGroups(storage, featureGroups);
    },

    /** Whether the usage bar shows the engine (B102); remembered on this device only. */
    setUsageBarEngine(provider: string, shown: boolean): void {
      const others = usageBarHidden.filter((name) => name !== provider);
      usageBarHidden = shown ? others : [...others, provider];
      saveUsageBarHidden(storage, usageBarHidden);
      dispatch({ type: "usageBarEngine", provider, shown });
    },

    /** Shows the change at once and puts `previous` back if the Mac refuses it. */
    async saveAgentDefaults(next: AgentDefaults, previous: AgentDefaults): Promise<void> {
      dispatch({ type: "agentDefaults", defaults: next });
      const saved = await attempt(() => api.saveAgentDefaults(next));
      dispatch({ type: "agentDefaults", defaults: saved ?? previous });
    },
  };
}

const USAGE_FRESH_MS = 60_000;

async function readPageUsage(api: Api, now: Date): Promise<PageUsage> {
  const day = isoDay(now);
  const [limits, today, week] = await Promise.all([
    api.usageLimits(),
    api.usagePeriod("day", day),
    api.usagePeriod("week", day),
  ]);
  const window = (found: UsageLimits["five_hour"]) =>
    found === null ? null : { utilization: found.utilization, resets_at: found.resets_at };
  return {
    limits: { five_hour: window(limits.five_hour), seven_day: window(limits.seven_day) },
    today: { tokens: today.tokens.total, sessions: today.sessions },
    week: { tokens: week.tokens.total, sessions: week.sessions },
  };
}
