import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { LocalModel, Session } from "../../api/types.ts";
import { WEAK_DISMISSED_KEY } from "../../store/devicePrefs.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { claudeProvider, codexProvider, detail, repo, session } from "../../test/fixtures.ts";
import { memoryStorage, renderApp } from "../../test/render.tsx";

// Local models on the phone (B116 item 8, D129).

function localModel(overrides: Partial<LocalModel> = {}): LocalModel {
  return {
    id: "lm_ready",
    server_id: "srv1",
    model: "qwen3-coder-30b",
    name: "qwen3-coder-30b",
    address: "localhost:1234",
    app: "LM Studio",
    context: 65536,
    tools: "good",
    weak_reason: null,
    vision: false,
    thinking: false,
    running: true,
    has_key: false,
    memory_warning: null,
    ...overrides,
  };
}

const READY = localModel();
const WEAK = localModel({ id: "lm_weak", name: "qwen3-4b", tools: "weak", context: 32768 });
const STOPPED = localModel({
  id: "lm_stopped",
  name: "devstral-small-2",
  app: "Ollama",
  address: "localhost:11434",
  running: false,
});

function withLocal(api: FakeApi, models: LocalModel[] = [READY, WEAK, STOPPED]) {
  api.providers.mockResolvedValue({ providers: [claudeProvider(), codexProvider()] });
  api.localModels.mockResolvedValue({ models, engine: "claude", local_only: false });
  api.repos.mockResolvedValue([repo("todo-ui")]);
  return api;
}

async function newChat(api: FakeApi) {
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: "New chat in todo-ui" }));
  await screen.findByRole("button", { name: /^Model: / });
  await waitFor(() => {
    expect(api.localModels).toHaveBeenCalled();
  });
  return rendered;
}

async function openChat(chat: Session, api: FakeApi, storage = memoryStorage()) {
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  const rendered = await renderApp({ api, storage });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  await waitFor(() => {
    expect(api.localModels).toHaveBeenCalled();
  });
  return rendered;
}

const downRefusal = () =>
  new ApiError(409, "LM Studio is not running", "local_server_down", {
    app: "LM Studio",
    address: "localhost:1234",
    start: "lmstudio",
  });

describe("local models in the model sheet", () => {
  it("lists ready, weak and stopped models; a stopped one cannot be chosen", async () => {
    const { user } = await newChat(withLocal(fakeApi()));

    await user.click(screen.getByRole("button", { name: /^Model: / }));
    const local = await screen.findByRole("group", { name: "Local" });

    expect(within(local).getByText("On this Mac, free, no limits")).toBeInTheDocument();
    const ready = within(local).getByRole("menuitemradio", { name: /qwen3-coder-30b/ });
    expect(ready).toHaveTextContent("LM Studio · 64k context");
    expect(ready).toBeEnabled();
    const weak = within(local).getByRole("menuitemradio", { name: /qwen3-4b/ });
    expect(weak).toHaveTextContent("Weak at tools: edits may fail");
    expect(weak).toBeEnabled();
    const stopped = within(local).getByRole("menuitemradio", { name: /devstral-small-2/ });
    expect(stopped).toHaveTextContent("Ollama is not running");
    expect(stopped).toBeDisabled();
  });

  it("starts a new chat on the chosen local model, with no thinking to pick", async () => {
    const api = withLocal(fakeApi());
    api.createSession.mockResolvedValue(session({ id: "new", model: "local:lm_ready" }));
    const { user } = await newChat(api);

    await user.click(screen.getByRole("button", { name: /^Model: / }));
    await user.click(await screen.findByRole("menuitemradio", { name: /qwen3-coder-30b/ }));

    expect(screen.getByRole("button", { name: "Model: qwen3-coder-30b" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Thinking: No thinking" })).toBeDisabled();
    await user.type(screen.getByLabelText("Message"), "Validate the form");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(api.createSession).toHaveBeenCalledWith(
        expect.objectContaining({ model: "local:lm_ready", provider: "claude" }),
      );
    });
  });
});

describe("a chat on a local model", () => {
  it("keeps a refused message, says the server is down, and Retry sends it again", async () => {
    const api = withLocal(fakeApi());
    const chat = session({ id: "c1", title: "Contact form", model: "local:lm_ready" });
    api.sendMessage.mockRejectedValueOnce(downRefusal());
    const { user } = await openChat(chat, api);
    const header = screen.getByRole("region", { name: "Contact form" }).querySelector(".ch-h");
    expect(within(header as HTMLElement).getByText("Local")).toBeInTheDocument();

    await user.type(screen.getByLabelText("Message"), "Validate the form");
    await user.click(screen.getByRole("button", { name: "Send" }));

    const card = await screen.findByRole("group", {
      name: "LM Studio is not running at localhost:1234",
    });
    expect(card).toHaveTextContent(
      "Start LM Studio's server, then Retry. Your message is kept and nothing was lost.",
    );
    expect(screen.getByLabelText("Message")).toHaveValue("Validate the form");
    // A refusal the card explains is not also a toast.
    expect(screen.queryByText("LM Studio is not running")).not.toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(api.sendMessage).toHaveBeenCalledTimes(2);
    });
    expect(api.sendMessage).toHaveBeenLastCalledWith("c1", "Validate the form", []);
    await waitFor(() => {
      expect(screen.queryByRole("group", { name: /not running/ })).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("starts the app's server from the card", async () => {
    const api = withLocal(fakeApi());
    const chat = session({ id: "c1", title: "Contact form", model: "local:lm_ready" });
    api.sendMessage.mockRejectedValueOnce(downRefusal());
    const { user } = await openChat(chat, api);
    await user.type(screen.getByLabelText("Message"), "Validate the form");
    await user.click(screen.getByRole("button", { name: "Send" }));
    const card = await screen.findByRole("group", { name: /not running/ });

    await user.click(within(card).getByRole("button", { name: "Start LM Studio" }));

    expect(api.startLocalServer).toHaveBeenCalledWith("lmstudio");
  });

  it("shows a turn that failed on a gone server, and a model LM Studio could not load", async () => {
    const api = withLocal(fakeApi());
    const chat = session({ id: "c1", title: "Contact form", model: "local:lm_ready" });
    const { push } = await openChat(chat, api);

    push({
      type: "session.state",
      session_id: "c1",
      payload: {
        state: "idle",
        code: "local_model_not_loaded",
        detail: "LM Studio could not load qwen3-coder-30b with 64k of context.",
        app: "LM Studio",
        address: "localhost:1234",
        model: "qwen3-coder-30b",
      },
    });

    const card = await screen.findByRole("group", {
      name: "Could not load qwen3-coder-30b in LM Studio",
    });
    expect(card).toHaveTextContent("LM Studio could not load qwen3-coder-30b with 64k of context.");

    push({ type: "session.state", session_id: "c1", payload: { state: "running" } });
    await waitFor(() => {
      expect(screen.queryByRole("group", { name: /Could not load/ })).not.toBeInTheDocument();
    });
  });

  it("warns about a model weak at tools until Don't show again, kept on this device", async () => {
    const api = withLocal(fakeApi());
    const chat = session({ id: "c1", title: "Contact form", model: "local:lm_weak" });
    const storage = memoryStorage();
    const { user, unmount } = await openChat(chat, api, storage);

    const bar = await screen.findByRole("group", { name: "Weak at tools" });
    expect(bar).toHaveTextContent("qwen3-4b is likely too weak at tool use");

    await user.click(within(bar).getByRole("button", { name: "Don't show again" }));

    expect(screen.queryByRole("group", { name: "Weak at tools" })).not.toBeInTheDocument();
    expect(storage.getItem(WEAK_DISMISSED_KEY)).toBe(JSON.stringify(["lm_weak"]));
    unmount();
    window.history.replaceState(null, "", "/");
    await openChat(chat, api, storage);
    expect(screen.queryByRole("group", { name: "Weak at tools" })).not.toBeInTheDocument();
  });
});
