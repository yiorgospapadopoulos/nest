// The desktop reader's frame keeps the phone reader's walls (ArtifactReader.test.tsx,
// ArtifactBridge.test.tsx): the policy first, an opaque sandbox, and links only after a yes.
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ArtifactContent } from "../../api/types.ts";
import { withCsp } from "../../screens/artifacts/html.ts";
import type { Actions } from "../../store/actions.ts";
import { StoreContext } from "../../store/context.ts";
import { initialState } from "../../store/state.ts";
import { artifactContent } from "../../test/fixtures.ts";
import { ArtifactFrame } from "./ArtifactFrame.tsx";

function show(content: ArtifactContent) {
  const actions = {
    onArtifactStorage: vi.fn(() => () => undefined),
    onEvent: vi.fn(() => () => undefined),
  } as unknown as Actions;
  const frame = createRef<HTMLIFrameElement>();
  render(
    <StoreContext value={{ state: initialState, actions, address: "127.0.0.1:8765" }}>
      <ArtifactFrame
        frame={frame}
        content={content}
        editable={false}
        onSaved={vi.fn()}
        onStored={vi.fn()}
        onChangedElsewhere={vi.fn()}
        onAsk={vi.fn()}
      />
    </StoreContext>,
  );
  const page = () => {
    const window = frame.current?.contentWindow;
    if (window == null) throw new Error("no frame window");
    return window;
  };
  return { frame, page };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the artifact frame", () => {
  it("shows the page with the policy first in an opaque sandbox", () => {
    const content = artifactContent({ kind: "html", content: "<p>hi</p>" });
    const { frame } = show(content);
    const element = frame.current;
    expect(element?.getAttribute("srcdoc")).toBe(withCsp(content.page));
    expect(element?.getAttribute("sandbox")).toBe("allow-scripts");
    expect(element?.getAttribute("referrerpolicy")).toBe("no-referrer");
  });

  it("lets only pages that print themselves open the print dialog", () => {
    const { frame } = show(artifactContent({ kind: "slides" }));
    expect(frame.current?.getAttribute("sandbox")).toBe("allow-scripts allow-modals");
  });

  it("asks before opening a link and declines on Cancel", async () => {
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    const { page } = show(artifactContent());
    const sent = vi.spyOn(page(), "postMessage");
    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { nest: 1, id: "1", method: "openLink", params: { url: "https://example.com/" } },
          source: page(),
        }),
      );
    });
    const ask = await screen.findByRole("dialog", { name: "Open link?" });
    expect(ask).toHaveTextContent("https://example.com/");
    await userEvent.click(within(ask).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(sent).toHaveBeenCalledWith(
        expect.objectContaining({
          id: "1",
          ok: false,
          error: expect.objectContaining({ code: "declined" }) as unknown,
        }),
        "*",
      );
    });
    expect(opened).not.toHaveBeenCalled();
  });
});
