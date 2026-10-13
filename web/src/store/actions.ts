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
  Approval,
  ApproveBody,
  ClaudeChat,
  CommandList,
  CreateSessionBody,
  HarnessEvent,
  MonthUsage,
  NotificationSettings,
  RepoConfig,
  ResolveBody,
  RewindPreview,
  SearchResults,
  Session,
  SessionDiff,
  UpdateSessionBody,
} from "../api/types.ts";
import { loadShowAutomated, saveShowAutomated } from "./devicePrefs.ts";
import { nudgeText } from "./selectors.ts";
import type { Action, Toast } from "./state.ts";

export type Dispatch = (action: Action) => void;

export type Actions = ReturnType<typeof createActions>;

const WORKING = new Set<Session["state"]>(["starting", "running"]);

// "elsewhere": refused because Claude Code has the chat open right now.
export type SendResult = "sent" | "failed" | "elsewhere";

/** Where origin pushes now, when publishing waits for the user to confirm it (I-008). */
export interface RemotePrompt {
  urls: string[];
  // The address harness recorded before, when origin changed since.
  confirmed: string | null;
}

// "remote": refused until the user confirms where origin pushes.
export type ApproveResult = "approved" | "refused" | "failed" | { remote: RemotePrompt };

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
  let showAutomated = loadShowAutomated(storage);
  // Until the first load succeeds, a failure means the Mac cannot be reached at all.
  let loaded = false;
  // The chats on screen, kept complete across a reconnect that cannot resume.
  const onScreen = new Set<string>();
  // The chats on screen whose last load failed, tried again after a reconnect.
  const failed = new Set<string>();
  // The stored events that arrived during each snapshot request in flight.
  const arriving = new Set<HarnessEvent[]>();

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

  /**
   * Applies a snapshot, then again the stored events that arrived while it loaded: the
   * snapshot may be older than they are. Transcripts already hold them without duplicates.
   */
  async function snapshot<T>(fetch: () => Promise<T>, apply: (loaded: T) => void): Promise<void> {
    const arrived: HarnessEvent[] = [];
    arriving.add(arrived);
    try {
      apply(await fetch());
      if (arrived.length > 0) dispatch({ type: "replayed", events: arrived });
    } finally {
      arriving.delete(arrived);
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
        },
      );
      loaded = true;
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

  return {
    toast,
    dismissToast: () => {
      dispatch({ type: "toast", toast: null });
    },
    load,

    /** A live event from the socket. */
    receive(event: HarnessEvent): void {
      if (event.id !== null) {
        for (const arrived of arriving) arrived.push(event);
      }
      dispatch({ type: "event", event });
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

    /**
     * After a reconnect that could not resume from a cursor, events may have been missed:
     * reload the snapshots and the chats on screen. Stored events merge without duplicates.
     */
    /** Loads again an open chat whose history could not be loaded. */
    reloadChat: (id: string) => fetchChat(id),

    /** After a resumed reconnect: the chats on screen whose history failed to load. */
    async reloadFailed(): Promise<void> {
      await Promise.all([...failed].map((id) => fetchChat(id)));
    },

    async resync(): Promise<void> {
      await Promise.all([load(), ...[...onScreen].map((id) => fetchChat(id, true))]);
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
     * "refused": the daemon said no (409), for example for a git violation or a branch that
     * moved. The session is fetched again so the screen shows why, then the reason. A push
     * address to confirm comes back for the screen to ask about instead.
     */
    async approveReview(review: Approval, body: ApproveBody): Promise<ApproveResult> {
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
      toast(updated.pr_url === null ? "Approved and committed" : "Pull request opened");
      return "approved";
    },

    async rejectReview(review: Approval): Promise<boolean> {
      const updated = await attempt(() => api.reject(review.session_id));
      if (updated === null) return false;
      dispatch({ type: "session", session: updated });
      dispatch({ type: "approval", approval: { ...review, status: "resolved" } });
      toast("Rejected. Nothing merged", "info");
      return true;
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
      const updated = await attempt(() =>
        api.updateWorktree(repo.name, { ...repo.worktree, default: value }),
      );
      if (updated === null) return false;
      dispatch({ type: "repo", repo: updated });
      return true;
    },

    /** The files linked into the project's worktrees and the commands run in new ones. */
    async saveRepoSetup(repo: RepoConfig, link: string[], setup: string[]): Promise<boolean> {
      const updated = await attempt(() => api.updateRepo(repo.name, { link, setup }));
      if (updated === null) return false;
      dispatch({ type: "repo", repo: updated });
      toast(`Saved ${repo.name}`);
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

    /** What restoring files to before the user message `eventId` would change. */
    rewindPreview(sessionId: string, eventId: number): Promise<RewindPreview | null> {
      return attempt(() => api.rewindPreview(sessionId, eventId));
    },

    /** Restores the files, not the conversation, to before the user message `eventId`. */
    async rewind(sessionId: string, eventId: number): Promise<boolean> {
      const done = await attempt(async () => {
        await api.rewind(sessionId, eventId);
        return true;
      });
      if (done === null) return false;
      toast("Files restored");
      return true;
    },

    /** Squash-merges the pull request; the daemon then closes the chat and its worktree. */
    async merge(approval: Approval, number: number): Promise<boolean> {
      const updated = await attempt(() => api.merge(approval.session_id, { method: "squash" }));
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
        report(error);
        return "failed";
      }
    },

    /** Takes a queued message back; one already delivered just leaves the list. */
    async cancelQueued(sessionId: string, queuedId: string): Promise<void> {
      try {
        await api.cancelQueued(sessionId, queuedId);
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 404)) {
          report(error);
          return;
        }
        toast("Already sent", "info");
      }
      dispatch({ type: "queuedRemoved", id: sessionId, queuedId });
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

    claudeChatEvents(id: string): Promise<HarnessEvent[] | null> {
      return attempt(() => api.claudeChatEvents(id));
    },

    /** Continues the chat in harness: it becomes a session and leaves the Claude Code list. */
    async adoptClaudeChat(chat: ClaudeChat): Promise<Session | null> {
      const session = await attempt(() => api.adoptClaudeChat(chat.id));
      if (session === null) return null;
      dispatch({ type: "session", session });
      dispatch({ type: "claudeChatRemoved", id: chat.id });
      return session;
    },

    /** Archives or restores a Claude Code chat in harness; Claude Code never sees it (D040). */
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
    async attachToDraft(key: string, file: File): Promise<void> {
      const uploaded = await attempt(() => api.uploadAttachment(file));
      if (uploaded !== null) dispatch({ type: "draftFileAdded", key, file: uploaded });
    },

    diff(sessionId: string): Promise<SessionDiff | null> {
      return attempt(() => api.diff(sessionId));
    },

    month(year: number, month: number): Promise<MonthUsage | null> {
      return attempt(() => api.usageMonth(year, month));
    },

    async loadNotifications(): Promise<void> {
      const settings = await attempt(() => api.notificationSettings());
      if (settings !== null) dispatch({ type: "notifications", notifications: settings });
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

    /** Asks the Mac to check Claude's usage now; resolves when the numbers are in. */
    async refreshUsage(): Promise<void> {
      try {
        dispatch({ type: "limits", limits: await api.refreshUsage() });
      } catch (error) {
        if (error instanceof ApiError && error.status === 429) {
          toast("Usage was refreshed moments ago", "info");
        } else {
          report(error);
        }
      }
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
     * Claude Code's models and the agent defaults, for the composer's selectors and the
     * Account tab. Quiet: without them the selectors keep working with fewer choices.
     */
    async loadChoices(): Promise<void> {
      const [list, defaults] = await Promise.all([
        quietly(() => api.models()),
        quietly(() => api.agentDefaults()),
      ]);
      if (list !== null) dispatch({ type: "models", models: list.models });
      if (defaults !== null) dispatch({ type: "agentDefaults", defaults });
    },

    /** Shows the change at once and puts `previous` back if the Mac refuses it. */
    async saveAgentDefaults(next: AgentDefaults, previous: AgentDefaults): Promise<void> {
      dispatch({ type: "agentDefaults", defaults: next });
      const saved = await attempt(() => api.saveAgentDefaults(next));
      dispatch({ type: "agentDefaults", defaults: saved ?? previous });
    },
  };
}
