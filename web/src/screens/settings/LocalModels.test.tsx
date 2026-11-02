import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LOCAL_MODELS_CHANGED } from "../../api/events.ts";
import type { LocalModel } from "../../api/types.ts";
import { downloadedModel, foundModel, localModel } from "../../test/accounts.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { openSettings } from "../../test/settings.ts";

function withModels(models: LocalModel[]) {
  const api = fakeApi();
  api.localModels.mockResolvedValue({ models, engine: "claude", local_only: false });
  return api;
}

const local = () => screen.getByRole("region", { name: "Local models" });
const modelRow = (name: string) => within(local()).getByRole("button", { name: new RegExp(name) });

describe("local models in Accounts (B106)", () => {
  it("shows each model's app, context and state as the Mac says them", async () => {
    await openSettings("Accounts", {
      api: withModels([
        localModel(),
        localModel({ id: "ol-dev", name: "devstral-small-2", app: "Ollama", running: false }),
        localModel({ id: "lm-4b", name: "qwen3-4b", context: 32768, tools: "weak" }),
        localModel({
          id: "lm-120b",
          name: "gpt-oss-120b",
          memory_warning: "Needs about 65 GB of this Mac's 24 GB",
        }),
      ]),
    });

    await within(await screen.findByRole("region", { name: "Local models" })).findByText(
      "qwen3-4b",
    );
    expect(modelRow("qwen3-coder-30b")).toHaveTextContent(
      "LM Studio · localhost:1234 · 64k context",
    );
    expect(modelRow("qwen3-coder-30b")).toHaveTextContent("Ready");
    expect(modelRow("devstral-small-2")).toHaveTextContent("Server not running");
    expect(modelRow("qwen3-4b")).toHaveTextContent("Weak at tools");
    expect(modelRow("gpt-oss-120b")).toHaveTextContent("Needs about 65 GB of this Mac's 24 GB");
    expect(within(local()).getByRole("button", { name: /Local chats run on/ })).toHaveTextContent(
      "Claude Code",
    );
  });

  it("removes a model after a confirmation, starts its app and follows local_models.changed", async () => {
    const api = withModels([localModel({ app: "Ollama", running: false })]);
    const { user, push } = await openSettings("Accounts", { api });

    await user.click(
      await within(await screen.findByRole("region", { name: "Local models" })).findByRole(
        "button",
        { name: /qwen3-coder-30b/ },
      ),
    );
    await user.click(screen.getByRole("menuitem", { name: "Start Ollama" }));
    expect(api.startLocalServer).toHaveBeenCalledWith("ollama");

    await user.click(modelRow("qwen3-coder-30b"));
    await user.click(screen.getByRole("menuitem", { name: "Remove" }));
    const confirm = screen.getByRole("alertdialog", { name: "Remove qwen3-coder-30b?" });
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.removeLocalModel).not.toHaveBeenCalled();
    await user.click(modelRow("qwen3-coder-30b"));
    await user.click(screen.getByRole("menuitem", { name: "Remove" }));
    await user.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Remove" }),
    );
    expect(api.removeLocalModel).toHaveBeenCalledWith("lm-qwen");

    api.localModels.mockResolvedValue({ models: [], engine: "claude", local_only: false });
    push({ type: LOCAL_MODELS_CHANGED, payload: {} });
    await waitFor(() => {
      expect(within(local()).queryByText("qwen3-coder-30b")).toBeNull();
    });
  });

  it("changes the engine local chats run on", async () => {
    const api = withModels([localModel()]);
    const { user } = await openSettings("Accounts", { api });

    await user.click(await screen.findByRole("button", { name: /Local chats run on/ }));
    await user.click(screen.getByRole("menuitemradio", { name: "Codex" }));

    expect(api.setLocalEngine).toHaveBeenCalledWith("codex");
  });
});

describe("add local model (B106)", () => {
  it("adds the models ticked among those running on the Mac", async () => {
    const api = withModels([]);
    api.findLocalModels.mockResolvedValue({
      running: [
        foundModel(),
        foundModel({ model: "gpt-oss-20b", name: "gpt-oss-20b", context: 131072 }),
        foundModel({ model: "qwen3-4b", name: "qwen3-4b", tools: "weak" }),
        foundModel({
          model: "gpt-oss-120b",
          name: "gpt-oss-120b",
          memory_warning: "Needs about 65 GB of this Mac's 24 GB",
        }),
      ],
      downloaded: [downloadedModel()],
    });
    const { user } = await openSettings("Accounts", { api });

    await user.click(await screen.findByRole("button", { name: "Add local model" }));
    const sheet = screen.getByRole("dialog", { name: "Add local model" });
    // Those good at tools that fit the Mac's memory start ticked.
    expect(
      await within(sheet).findByRole("checkbox", { name: "Add qwen3-coder-30b" }),
    ).toBeChecked();
    expect(within(sheet).getByRole("checkbox", { name: "Add gpt-oss-20b" })).toBeChecked();
    expect(within(sheet).getByRole("checkbox", { name: "Add qwen3-4b" })).not.toBeChecked();
    expect(within(sheet).getByRole("checkbox", { name: "Add gpt-oss-120b" })).not.toBeChecked();
    expect(
      within(sheet).getByText("Likely too weak at tools: edits and commands may fail"),
    ).toBeInTheDocument();
    expect(within(sheet).getByText("Ollama models folder · start Ollama to use it")).toBeVisible();

    await user.click(within(sheet).getByRole("checkbox", { name: "Add gpt-oss-20b" }));
    await user.click(within(sheet).getByRole("checkbox", { name: "Add qwen3-4b" }));
    await user.click(within(sheet).getByRole("button", { name: "Add 2 models" }));

    expect(api.addLocalModels).toHaveBeenCalledWith("localhost:1234", null, [
      "qwen3-coder-30b",
      "qwen3-4b",
    ]);
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Add local model" })).toBeNull();
    });
  });

  it("starts a downloaded model's app, then looks again", async () => {
    const api = withModels([]);
    api.findLocalModels.mockResolvedValue({ running: [], downloaded: [downloadedModel()] });
    const { user } = await openSettings("Accounts", { api });

    await user.click(await screen.findByRole("button", { name: "Add local model" }));
    const sheet = screen.getByRole("dialog", { name: "Add local model" });
    expect(await within(sheet).findByText("No model server is running on this Mac.")).toBeVisible();
    await user.click(within(sheet).getByRole("button", { name: "Start Ollama" }));

    expect(api.startLocalServer).toHaveBeenCalledWith("ollama");
    await waitFor(() => {
      expect(api.findLocalModels).toHaveBeenCalledTimes(2);
    });
  });

  it("adds the models a server at an address serves, with its key", async () => {
    const api = withModels([]);
    const served = foundModel({
      address: "localhost:8080",
      app: null,
      model: "qwen",
      name: "Qwen3",
    });
    api.checkLocalServer.mockResolvedValue({
      ok: true,
      error: null,
      server: { address: "localhost:8080", app: null, messages: true, responses: true, chat: true },
      models: [served],
    });
    const { user } = await openSettings("Accounts", { api });

    await user.click(await screen.findByRole("button", { name: "Add local model" }));
    const sheet = screen.getByRole("dialog", { name: "Add local model" });
    await user.click(within(sheet).getByRole("button", { name: "Enter address" }));
    await user.type(within(sheet).getByLabelText("Where the model runs"), "localhost:8080");
    await user.type(within(sheet).getByLabelText("Key, only if the server asks for one"), "sk-1");
    await user.click(within(sheet).getByRole("button", { name: "Check" }));

    expect(api.checkLocalServer).toHaveBeenCalledWith("localhost:8080", "sk-1");
    expect(
      await within(sheet).findByText(
        "Found a server at localhost:8080 with 1 model. It works with Claude Code and Codex.",
      ),
    ).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Add 1 model" }));

    expect(api.addLocalModels).toHaveBeenCalledWith("localhost:8080", "sk-1", ["qwen"]);
  });
});
