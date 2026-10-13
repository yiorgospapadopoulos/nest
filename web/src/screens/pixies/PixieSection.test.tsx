import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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
});
