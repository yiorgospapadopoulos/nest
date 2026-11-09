// The Linux app's mic (B154), over the logic it shares with the phone: the words go where
// the caret is.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as recorder from "../../screens/chat/voice/recorder.ts";
import { StoreProvider } from "../../store/StoreProvider.tsx";
import { fakeApi } from "../../test/fakeApi.ts";
import { socketFactory } from "../../test/fakeSocket.ts";
import { session } from "../../test/fixtures.ts";
import { memoryStorage } from "../../test/render.tsx";
import { Composer } from "./Composer.tsx";

function renderComposer(api: ReturnType<typeof fakeApi>) {
  const storage = memoryStorage();
  render(
    <StoreProvider
      api={api}
      connect={socketFactory().connect}
      storage={() => storage}
      location={{ protocol: "http:", host: "127.0.0.1:8765" }}
    >
      <Composer target={{ kind: "chat", session: session() }} />
    </StoreProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("dictating in a pane (B154)", () => {
  it("puts what was said at the caret", async () => {
    vi.spyOn(recorder, "canRecord").mockReturnValue(true);
    vi.spyOn(recorder, "startRecording").mockResolvedValue({
      stop: () => new Blob(["wav"]),
      cancel: vi.fn(),
    });
    const api = fakeApi();
    renderComposer(api);
    const field = screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Message" });
    await waitFor(() => {
      expect(api.voiceStatus).toHaveBeenCalled();
    });
    fireEvent.change(field, { target: { value: "Please now" } });
    field.focus();
    field.setSelectionRange(6, 6);
    const mic = screen.getByRole("button", { name: "Dictate" });

    fireEvent.click(mic);
    await waitFor(() => {
      expect(mic).toHaveAttribute("aria-pressed", "true");
    });
    fireEvent.click(mic);

    await waitFor(() => {
      expect(field).toHaveValue("Please run the tests now");
    });
  });

  it("shows no mic where the app cannot record", () => {
    vi.spyOn(recorder, "canRecord").mockReturnValue(false);
    renderComposer(fakeApi());

    expect(screen.queryByRole("button", { name: "Dictate" })).not.toBeInTheDocument();
  });
});
