import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Pixie } from "../../api/types.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { pixie, session } from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

describe("Pixies section", () => {
  it("lists pixies above projects and opens one", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie({ id: "p1", name: "Tester", slug: "tester" })]);
    api.sessions.mockResolvedValue([session({ id: "c1", repo: "pixie:p1", pixie_id: "p1" })]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    expect(screen.getByRole("heading", { name: /Pixies/ })).toBeInTheDocument();
    expect(screen.queryByText("pixie:p1")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Tester/ }));
    expect(screen.getByRole("tab", { name: "Chat" })).toBeInTheDocument();
  });

  it("offers templates when there are no pixies and creates only on tap", async () => {
    const api = fakeApi();
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    expect(api.createPixie).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Reviewer" }));
    expect(api.createPixie).toHaveBeenCalledWith(expect.objectContaining({ name: "Reviewer" }));
  });

  it("shows hidden pixies on request, and no templates while they exist", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([
      pixie({ id: "p1", name: "Shown", slug: "shown" }),
      pixie({ id: "p2", name: "Secret", slug: "secret", hidden: true, position: 1 }),
    ]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    expect(screen.queryByRole("button", { name: /Secret/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show hidden (1)" }));
    expect(screen.getByRole("button", { name: /Secret/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hide hidden" }));
    expect(screen.queryByRole("button", { name: /Secret/ })).not.toBeInTheDocument();
  });

  it("offers no templates when every pixie is hidden", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie({ hidden: true })]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    expect(screen.queryByText("Or start from a template")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show hidden (1)" }));
    expect(screen.getByRole("button", { name: /Tester/ })).toBeInTheDocument();
  });

  it("New pixie creates one and opens its details", async () => {
    const api = fakeApi();
    api.createPixie.mockResolvedValue(pixie({ id: "p9", name: "New pixie", slug: "new-pixie" }));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: "New pixie" }));

    expect(api.createPixie).toHaveBeenCalledWith({ name: "New pixie" });
    expect(screen.getByRole("tab", { name: "Details", selected: true })).toBeInTheDocument();
  });

  it("opens a template on its chat, and stays put when creating fails", async () => {
    const api = fakeApi();
    api.createPixie
      .mockRejectedValueOnce(new Error("Disk full"))
      .mockResolvedValueOnce(pixie({ id: "p2", name: "Tester", mascot: "robot" }));
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    await user.click(screen.getByRole("button", { name: "Tester" }));
    expect(await screen.findByText("Disk full")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Chat" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tester" }));
    expect(api.createPixie).toHaveBeenLastCalledWith(
      expect.objectContaining({
        name: "Tester",
        mascot: "robot",
        soul: expect.any(String) as string,
      }),
    );
    expect(screen.getByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
  });

  it("shows which pixies are at work and leaves hidden ones out", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([
      pixie({ id: "p1", name: "Tester", chat_session_id: "c1" }),
      pixie({ id: "p2", name: "Shy", slug: "shy", hidden: true }),
    ]);
    api.sessions.mockImplementation((archived) =>
      Promise.resolve(
        archived ? [] : [session({ id: "c1", repo: "pixie:p1", pixie_id: "p1", state: "running" })],
      ),
    );
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));

    expect(screen.getByRole("button", { name: "Tester, @tester, running" })).toBeInTheDocument();
    expect(screen.queryByText("Shy")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reviewer" })).not.toBeInTheDocument();
  });

  it("gives focus back to the pixie's row when its page closes", async () => {
    const api = fakeApi();
    api.pixies.mockResolvedValue([pixie()]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: /^Tester/ }));
    await user.click(screen.getByRole("button", { name: "Back to Projects" }));

    expect(screen.getByRole("button", { name: /^Tester/ })).toHaveFocus();
  });

  describe("Edit order", () => {
    const three = () => [
      pixie({ id: "a", name: "Ada", slug: "ada" }),
      pixie({ id: "b", name: "Bo", slug: "bo", position: 1, hidden: true }),
      pixie({ id: "c", name: "Cy", slug: "cy", position: 2 }),
    ];
    // The order on screen, read from the Move up buttons.
    const shown = () =>
      screen
        .getAllByRole("button", { name: /^Move .* up$/ })
        .map((b) => b.getAttribute("aria-label")?.slice(5, -3));
    const inOrder = (list: Pixie[], ids: string[]) =>
      ids.flatMap((id, position) =>
        list.filter((p) => p.id === id).map((p) => ({ ...p, position })),
      );

    async function editOrder(api = fakeApi()) {
      api.pixies.mockResolvedValue(three());
      const rendered = await renderApp({ api });
      await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
      await rendered.user.click(screen.getByRole("button", { name: "Edit order" }));
      return rendered;
    }

    it("moves a pixie at once, past the hidden ones, and saves the whole order", async () => {
      const api = fakeApi();
      api.reorderPixies.mockImplementation((ids) => Promise.resolve(inOrder(three(), ids)));
      const { user } = await editOrder(api);

      expect(shown()).toEqual(["Ada", "Cy"]);
      expect(screen.getByRole("button", { name: "Move Ada up" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Move Cy down" })).toBeDisabled();
      // While ordering, a row does not open its pixie.
      expect(screen.queryByRole("button", { name: /^Ada,/ })).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Move Cy up" }));
      expect(shown()).toEqual(["Cy", "Ada"]);
      expect(api.reorderPixies).toHaveBeenLastCalledWith(["c", "a", "b"]);

      await user.click(screen.getByRole("button", { name: "Move Cy down" }));
      await waitFor(() => {
        expect(api.reorderPixies).toHaveBeenLastCalledWith(["a", "c", "b"]);
      });
      await waitFor(() => {
        expect(shown()).toEqual(["Ada", "Cy"]);
      });

      await user.click(screen.getByRole("button", { name: "Done" }));
      expect(screen.getByRole("button", { name: /^Ada,/ })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Edit order" })).toBeInTheDocument();
    });

    it("sends a quick second move only after the first, keeping both", async () => {
      const api = fakeApi();
      let finish: (list: Pixie[]) => void = () => undefined;
      api.reorderPixies
        .mockImplementationOnce(
          (ids) =>
            new Promise((resolve) => {
              finish = () => {
                resolve(inOrder(three(), ids));
              };
            }),
        )
        .mockImplementation((ids) => Promise.resolve(inOrder(three(), ids)));
      const { user } = await editOrder(api);

      await user.click(screen.getByRole("button", { name: "Move Cy up" }));
      await user.click(screen.getByRole("button", { name: "Move Cy down" }));
      expect(shown()).toEqual(["Ada", "Cy"]);
      expect(api.reorderPixies).toHaveBeenCalledTimes(1);

      finish([]);
      await waitFor(() => {
        expect(api.reorderPixies).toHaveBeenCalledTimes(2);
      });
      expect(api.reorderPixies).toHaveBeenLastCalledWith(["a", "c", "b"]);
      expect(shown()).toEqual(["Ada", "Cy"]);
    });

    it("puts the order back when the Mac refuses it", async () => {
      const api = fakeApi();
      api.reorderPixies.mockRejectedValue(
        new Error("the order must name every pixie exactly once"),
      );
      const { user } = await editOrder(api);

      await user.click(screen.getByRole("button", { name: "Move Cy up" }));
      expect(
        await screen.findByText("the order must name every pixie exactly once"),
      ).toBeInTheDocument();
      expect(shown()).toEqual(["Ada", "Cy"]);
      // The list is read again, in case a pixie was added meanwhile.
      expect(api.pixies).toHaveBeenCalledTimes(2);
    });

    it("is offered only with two pixies or more to order", async () => {
      const api = fakeApi();
      api.pixies.mockResolvedValue([pixie(), pixie({ id: "p2", hidden: true, position: 1 })]);
      const { user } = await renderApp({ api });
      await user.click(screen.getByRole("tab", { name: "Projects" }));

      expect(screen.queryByRole("button", { name: "Edit order" })).not.toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Show hidden (1)" }));
      expect(screen.getByRole("button", { name: "Edit order" })).toBeInTheDocument();
    });
  });
});
