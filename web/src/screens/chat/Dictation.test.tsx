// The phone's mic (B154): it asks once to fetch voice input, records, and puts what was
// said into the draft; without a usable microphone it says why.
import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Session } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { detail, repo, session, voiceStatus } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";
import * as recorder from "./voice/recorder.ts";

const recorded = new Blob(["wav"], { type: "audio/wav" });

async function openChat(api = fakeApi(), chat: Session = session()) {
  api.repos.mockResolvedValue([repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Chats" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return rendered;
}

const mic = () => screen.getByRole("button", { name: "Dictate" });

beforeEach(() => {
  vi.spyOn(recorder, "canRecord").mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("dictating on the phone (B154)", () => {
  it("records, then puts what was said after the draft", async () => {
    const api = fakeApi();
    const stop = vi.fn(() => recorded);
    vi.spyOn(recorder, "startRecording").mockResolvedValue({ stop, cancel: vi.fn() });
    const { user } = await openChat(api);
    await user.type(screen.getByLabelText("Message"), "Please");
    await waitFor(() => {
      expect(api.voiceStatus).toHaveBeenCalled();
    });

    await user.click(mic());
    await waitFor(() => {
      expect(mic()).toHaveAttribute("aria-pressed", "true");
    });
    await user.click(mic());

    await waitFor(() => {
      expect(screen.getByLabelText("Message")).toHaveValue("Please run the tests");
    });
    expect(stop).toHaveBeenCalled();
    expect(api.transcribe).toHaveBeenCalledWith(recorded);
    expect(mic()).toHaveAttribute("aria-pressed", "false");
  });

  it("asks before fetching voice input, saying how big it is", async () => {
    const api = fakeApi();
    api.voiceStatus.mockResolvedValue(voiceStatus({ state: "not_installed", download_mb: 665 }));
    const start = vi.spyOn(recorder, "startRecording");
    const { user } = await openChat(api);
    await waitFor(() => {
      expect(api.voiceStatus).toHaveBeenCalled();
    });

    await user.click(mic());

    const question = await screen.findByRole("alertdialog", { name: "Turn on voice input?" });
    expect(question).toHaveTextContent("about 670 MB");
    await user.click(screen.getByRole("button", { name: "Download" }));
    expect(api.installVoice).toHaveBeenCalled();
    expect(start).not.toHaveBeenCalled();
  });

  it("says when the microphone is not allowed", async () => {
    vi.spyOn(recorder, "startRecording").mockRejectedValue(
      new DOMException("denied", "NotAllowedError"),
    );
    const api = fakeApi();
    const { user } = await openChat(api);
    await waitFor(() => {
      expect(api.voiceStatus).toHaveBeenCalled();
    });

    await user.click(mic());

    expect(await screen.findByText("Nest is not allowed to use the microphone")).toBeVisible();
    expect(api.transcribe).not.toHaveBeenCalled();
  });

  it("puts the words at the caret and leaves the caret after them", async () => {
    vi.spyOn(recorder, "startRecording").mockResolvedValue({
      stop: () => recorded,
      cancel: vi.fn(),
    });
    const api = fakeApi();
    const { user } = await openChat(api);
    const field = screen.getByLabelText<HTMLTextAreaElement>("Message");
    await user.type(field, "Please now");
    field.setSelectionRange(6, 6);
    await waitFor(() => {
      expect(api.voiceStatus).toHaveBeenCalled();
    });

    await user.click(mic());
    await waitFor(() => {
      expect(mic()).toHaveAttribute("aria-pressed", "true");
    });
    await user.click(mic());

    await waitFor(() => {
      expect(field).toHaveValue("Please run the tests now");
    });
    expect(field.selectionStart).toBe(20);
  });

  it("asks to download again when the recording is refused as not set up", async () => {
    vi.spyOn(recorder, "startRecording").mockResolvedValue({
      stop: () => recorded,
      cancel: vi.fn(),
    });
    const api = fakeApi();
    api.transcribe.mockRejectedValue(new ApiError(409, "voice input is not set up"));
    const { user } = await openChat(api);
    await waitFor(() => {
      expect(api.voiceStatus).toHaveBeenCalled();
    });
    api.voiceStatus.mockResolvedValue(voiceStatus({ state: "not_installed", download_mb: 485 }));

    await user.click(mic());
    await waitFor(() => {
      expect(mic()).toHaveAttribute("aria-pressed", "true");
    });
    await user.click(mic());

    expect(await screen.findByRole("alertdialog", { name: "Turn on voice input?" })).toBeVisible();
  });

  it("gives up on the microphone with a second tap while it is asked for", async () => {
    let grant: (recording: recorder.Recording) => void = () => undefined;
    vi.spyOn(recorder, "startRecording").mockReturnValue(
      new Promise((resolve) => {
        grant = resolve;
      }),
    );
    const cancel = vi.fn();
    const api = fakeApi();
    const { user } = await openChat(api);
    await waitFor(() => {
      expect(api.voiceStatus).toHaveBeenCalled();
    });

    await user.click(mic());
    expect(mic()).toHaveAttribute("aria-pressed", "true");
    await user.click(mic());
    expect(mic()).toHaveAttribute("aria-pressed", "false");
    grant({ stop: () => recorded, cancel });

    await waitFor(() => {
      expect(cancel).toHaveBeenCalled();
    });
    expect(mic()).toHaveAttribute("aria-pressed", "false");
  });

  it("falls back to the keyboard's dictation where the page cannot record", async () => {
    vi.spyOn(recorder, "canRecord").mockReturnValue(false);
    const api = fakeApi();
    const { user } = await openChat(api);

    await user.click(mic());

    expect(screen.getByLabelText("Message")).toHaveFocus();
    expect(api.voiceStatus).not.toHaveBeenCalled();
  });
});
