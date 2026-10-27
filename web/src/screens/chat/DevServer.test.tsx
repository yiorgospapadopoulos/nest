import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { RunOutput, RunStatus, Session } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, repo, runStatus, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

const ESC = "\x1b";

const stopped = runStatus({ available: true, command: "npm run dev" });
const running = (listening = [41020, 41021], started_at = "2026-10-26T22:41:07Z") =>
  runStatus({
    available: true,
    command: "npm run dev",
    state: "running",
    listening,
    started_at,
  });

async function openChat(status: RunStatus | Error, chat: Session = session()) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  if (status instanceof Error) api.run.mockRejectedValue(status);
  else api.run.mockResolvedValue(status);
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  const region = await screen.findByRole("region", { name: chat.title });
  await waitFor(() => {
    expect(api.run).toHaveBeenCalledWith(chat.id);
  });
  const header = () => defined(region.querySelector("header"));
  const changed = (next: RunStatus) => {
    rendered.push({
      type: "run.changed",
      payload: { folder: next.folder, repo: "todo-ui", status: { ...next } },
    });
  };
  const chunk = (text: string, folder = "/w/s1") => {
    rendered.push({ type: "run.output", payload: { folder, text } });
  };
  return { ...rendered, region, header, changed, chunk };
}

function defined<T>(value: T | null | undefined): T {
  if (value == null) throw new Error("missing");
  return value;
}

describe("a chat's dev server", () => {
  it("shows nothing when the repo has no run command", async () => {
    const { header } = await openChat(runStatus());
    expect(within(header()).queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
    expect(header().querySelector(".ch-st")).toBeNull();
  });

  it("shows nothing, quietly, when the Mac's daemon has no runs yet", async () => {
    const { header } = await openChat(new ApiError(404, "Not Found"));
    expect(within(header()).queryByRole("button", { name: "Run" })).not.toBeInTheDocument();
    expect(screen.queryByText("Not Found")).not.toBeInTheDocument();
  });

  it("starts from Run and shows the output as it comes, in colour", async () => {
    const { api, header, user, changed, chunk } = await openChat(stopped);
    expect(header().querySelector(".ch-st")).toHaveTextContent(/^agent\/contact$/);
    api.runControl.mockResolvedValue(
      runStatus({ ...stopped, state: "starting", started_at: "2026-10-26T22:41:07Z" }),
    );
    api.runOutput.mockResolvedValue({ folder: "/w/s1", text: `$ npm run dev\n` });

    await user.click(within(header()).getByRole("button", { name: "Run" }));

    expect(api.runControl).toHaveBeenCalledWith("s1", "start");
    const sheet = await screen.findByRole("dialog", { name: "npm run dev" });
    const output = within(sheet).getByLabelText("Output");
    await waitFor(() => {
      expect(output).toHaveTextContent("$ npm run dev");
    });
    // Starting: the stop square, and the line under the name opens the output.
    expect(within(header()).getByRole("button", { name: "Stop npm run dev" })).toBeInTheDocument();
    expect(within(header()).getByRole("button", { name: "Starting" })).toBeInTheDocument();

    chunk(`  ${ESC}[32mVITE${ESC}[39m ready in ${ESC}[1m412${ESC}[22m ms\n`);
    chunk("elsewhere", "/w/other");
    expect(output).toHaveTextContent("$ npm run dev VITE ready in 412 ms");
    expect(within(output).getByText("VITE")).toHaveClass("a32");
    expect(within(output).getByText("412")).toHaveClass("ab");
    expect(output).not.toHaveTextContent("elsewhere");

    changed(running());
    expect(header().querySelector(".ch-st")).toHaveTextContent("agent/contact41020, 41021");
  });

  it("shows the listening ports, the first two of more than three", async () => {
    const { header, changed } = await openChat(running([41020, 41021, 41022, 41023]));
    const ports = within(header()).getByRole("button", {
      name: "Ports 41020, 41021, 41022, 41023",
    });
    expect(ports).toHaveTextContent(/^41020, 41021 \+2$/);
    expect(ports.querySelector(".rlive")).not.toBeNull();

    changed(running([5173]));
    expect(within(header()).getByRole("button", { name: "Ports 5173" })).toHaveTextContent(
      /^5173$/,
    );
  });

  it("stops from the stop square", async () => {
    const { api, header, user } = await openChat(running());
    api.runControl.mockResolvedValue(stopped);
    await user.click(within(header()).getByRole("button", { name: "Stop npm run dev" }));
    expect(api.runControl).toHaveBeenCalledWith("s1", "stop");
    expect(await within(header()).findByRole("button", { name: "Run" })).toBeInTheDocument();
    expect(within(header()).queryByRole("button", { name: /^Ports/ })).not.toBeInTheDocument();
  });

  it("restarts and stops from the sheet, which loads the output of each new start", async () => {
    const { api, header, user, changed } = await openChat(running());
    api.runOutput.mockResolvedValue({ folder: "/w/s1", text: "first run\n" });
    await user.click(within(header()).getByRole("button", { name: "Ports 41020, 41021" }));
    const sheet = await screen.findByRole("dialog", { name: "npm run dev" });
    const output = within(sheet).getByLabelText("Output");
    await waitFor(() => {
      expect(output).toHaveTextContent("first run");
    });
    expect(output).toHaveFocus();

    api.runOutput.mockResolvedValue({ folder: "/w/s1", text: "second run\n" });
    api.runControl.mockResolvedValue(running([41020], "2026-10-26T23:00:00Z"));
    await user.click(within(sheet).getByRole("button", { name: "Restart" }));
    expect(api.runControl).toHaveBeenCalledWith("s1", "restart");
    await waitFor(() => {
      expect(output).toHaveTextContent(/^second run$/);
    });
    expect(api.runOutput).toHaveBeenCalledTimes(2);

    api.runControl.mockResolvedValue(stopped);
    await user.click(within(sheet).getByRole("button", { name: "Stop" }));
    expect(api.runControl).toHaveBeenLastCalledWith("s1", "stop");
    await waitFor(() => {
      expect(within(sheet).getByRole("button", { name: "Stop" })).toBeDisabled();
    });

    // Another device starts it again: the sheet follows.
    const loads = api.runOutput.mock.calls.length;
    changed(running([41020], "2026-10-26T23:10:00Z"));
    await waitFor(() => {
      expect(api.runOutput).toHaveBeenCalledTimes(loads + 1);
    });
    expect(within(sheet).getByRole("button", { name: "Stop" })).toBeEnabled();
  });

  it("shows a failed run in red and opens its output to see why", async () => {
    const failed = runStatus({ ...stopped, state: "exited", exit_code: 1 });
    const { api, header, user } = await openChat(failed);
    api.runOutput.mockResolvedValue({ folder: "/w/s1", text: "Error: port in use\n" });
    const button = within(header()).getByRole("button", { name: "Exited 1" });
    expect(button).toHaveClass("bad");

    await user.click(button);
    const sheet = await screen.findByRole("dialog", { name: "npm run dev" });
    expect(await within(sheet).findByText("Error: port in use")).toBeInTheDocument();
    expect(api.runControl).not.toHaveBeenCalled();
    expect(within(sheet).getByRole("button", { name: "Stop" })).toBeDisabled();

    api.runControl.mockResolvedValue(running());
    await user.click(within(sheet).getByRole("button", { name: "Run again" }));
    expect(api.runControl).toHaveBeenCalledWith("s1", "start");
  });

  it("treats a run that exited cleanly as stopped", async () => {
    const { header } = await openChat(runStatus({ ...stopped, state: "exited", exit_code: 0 }));
    expect(within(header()).getByRole("button", { name: "Run" })).toBeInTheDocument();
  });

  it("says why when the Mac refuses, and keeps the control as it was", async () => {
    const { api, header, user } = await openChat(stopped);
    api.runControl.mockRejectedValue(new ApiError(409, "This chat has no run command"));
    await user.click(within(header()).getByRole("button", { name: "Run" }));
    expect(await screen.findByText("This chat has no run command")).toBeInTheDocument();
    expect(within(header()).getByRole("button", { name: "Run" })).toBeInTheDocument();
  });

  it("shows live output even when the earlier output could not be loaded", async () => {
    const { api, header, user, chunk } = await openChat(running());
    api.runOutput.mockRejectedValue(new ApiError(500, "Could not read the output"));
    await user.click(within(header()).getByRole("button", { name: "Ports 41020, 41021" }));
    expect(await screen.findByText("Could not read the output")).toBeInTheDocument();
    chunk("hmr update\n");
    expect(screen.getByLabelText("Output")).toHaveTextContent("hmr update");
  });

  it("drops output that arrives after the sheet closed", async () => {
    const { api, header, user } = await openChat(running());
    let answer: (output: RunOutput) => void = () => undefined;
    api.runOutput.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    await user.click(within(header()).getByRole("button", { name: "Ports 41020, 41021" }));
    await screen.findByRole("dialog", { name: "npm run dev" });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => {
      answer({ folder: "/w/s1", text: "late" });
      await Promise.resolve();
    });

    api.runOutput.mockReturnValue(new Promise(() => undefined));
    await user.click(within(header()).getByRole("button", { name: "Ports 41020, 41021" }));
    const sheet = await screen.findByRole("dialog", { name: "npm run dev" });
    expect(within(sheet).getByLabelText("Output")).toHaveTextContent(/^$/);
  });

  it("keeps the output scrolled to the end unless scrolled up", async () => {
    const { header, user, chunk } = await openChat(running());
    await user.click(within(header()).getByRole("button", { name: "Ports 41020, 41021" }));
    const output = await screen.findByLabelText("Output");
    let height = 1000;
    Object.defineProperty(output, "scrollHeight", { get: () => height });
    Object.defineProperty(output, "clientHeight", { value: 300 });

    chunk("one\n");
    expect(output.scrollTop).toBe(1000);

    output.scrollTop = 200;
    fireEvent.scroll(output);
    height = 1200;
    chunk("two\n");
    expect(output.scrollTop).toBe(200);

    output.scrollTop = 900;
    fireEvent.scroll(output);
    height = 1400;
    chunk("three\n");
    expect(output.scrollTop).toBe(1400);
  });

  it("is fetched again after a reconnect, as run events are not stored", async () => {
    const { api, header, push, sockets, changed } = await openChat(running());

    // Without a cursor the reconnect cannot resume: everything on screen is reloaded.
    api.run.mockResolvedValue(stopped);
    sockets.reconnect();
    expect(await within(header()).findByRole("button", { name: "Run" })).toBeInTheDocument();

    // A stored event moves the cursor, so this one resumes; the run is still asked again.
    push({ id: 7, type: "session.context", payload: {} });
    changed(running());
    api.run.mockResolvedValue(runStatus({ ...stopped, state: "exited", exit_code: 2 }));
    sockets.reconnect();
    expect(await within(header()).findByRole("button", { name: "Exited 2" })).toBeInTheDocument();
    expect(api.run).toHaveBeenCalledTimes(3);
  }, 15_000);
});
