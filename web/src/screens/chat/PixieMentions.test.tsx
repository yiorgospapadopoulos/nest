import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Pixie, PixieTeam } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi, type FakeApi } from "../../test/fakeApi.ts";
import { detail, pixie, repo, session, team } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";
import { renderApp } from "../../test/render.tsx";

const PIXIES = [
  pixie({ id: "lead", slug: "qa-lead", name: "Lead", position: 0, team_id: "qa" }),
  pixie({
    id: "bugs",
    slug: "bugs",
    name: "Bug hunter",
    mascot: "owl",
    position: 1,
    team_id: "qa",
  }),
  pixie({ id: "rev", slug: "reviewer", name: "Reviewer", position: 2 }),
  pixie({ id: "shy", slug: "shy", name: "Shy", position: 3, hidden: true }),
  pixie({ id: "none", slug: "blind", name: "Blind", position: 4, project_access: "none" }),
  pixie({ id: "other", slug: "other", name: "Elsewhere", position: 5, projects: ["narrative"] }),
];
const TEAMS = [
  team({ id: "qa", name: "QA crew", handle: "qa", leader_id: "lead" }),
  team({ id: "empty", name: "Nobody", handle: "nobody", position: 1 }),
];

function withPixies(api: FakeApi, pixies: Pixie[] = PIXIES, teams: PixieTeam[] = TEAMS) {
  api.pixies.mockResolvedValue(pixies);
  api.teams.mockResolvedValue(teams);
  api.pixieFile.mockImplementation((id) =>
    Promise.resolve({ text: `\n# Soul of ${id}\nMore lines`, hash: "h" }),
  );
  return api;
}

async function openChat(api: FakeApi) {
  const chat = session();
  api.repos.mockResolvedValue([repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : [chat]));
  api.session.mockResolvedValue(detail(chat));
  const rendered = await renderApp({ api });
  await rendered.user.click(screen.getByRole("tab", { name: "Projects" }));
  await rendered.user.click(screen.getByRole("button", { name: new RegExp(`^${chat.title},`) }));
  await screen.findByRole("region", { name: chat.title });
  return { ...rendered, field: screen.getByLabelText("Message") };
}

const optionsIn = (group: string) =>
  within(screen.getByRole("group", { name: group }))
    .getAllByRole("option")
    .map((o) => o.textContent);

describe("pixie mentions", () => {
  it("lists callable teams, then the pixies in none of them, before files (B46)", async () => {
    const api = withPixies(fakeApi());
    api.files.mockResolvedValue({ files: ["src/app.py"] });
    const { user, field } = await openChat(api);

    await user.type(field, "@");
    const list = await screen.findByRole("listbox", { name: "Pixies and files" });
    await screen.findByRole("option", { name: /src\/app\.py/ });
    await waitFor(() => {
      // A team's pixies are called with their team only.
      expect(optionsIn("Pixies")).toEqual(["QA crew @qa", "Reviewer @reviewerSoul of rev"]);
    });
    expect(optionsIn("Files")).toEqual(["src/app.py"]);
    // Pixies come first.
    expect(within(list).getAllByRole("option")[0]).toHaveTextContent("QA crew");
    // The team shows its members' mascots.
    const crew = screen.getByRole("option", { name: /QA crew/ });
    expect(crew.querySelectorAll("svg")).toHaveLength(2);
    expect(api.pixieFile.mock.calls.map(([id]) => id)).toEqual(["rev"]);
    // Each soul is read once.
    await user.type(field, "x{Backspace}");
    expect(api.pixieFile.mock.calls.filter(([id]) => id === "rev")).toHaveLength(1);
  });

  it("filters by name or handle and inserts the handle", async () => {
    const api = withPixies(fakeApi());
    const { user, field } = await openChat(api);

    await user.type(field, "Ask @REV");
    await waitFor(() => {
      expect(optionsIn("Pixies")).toEqual(["Reviewer @reviewerSoul of rev"]);
    });
    expect(screen.queryByRole("group", { name: "Files" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: /Reviewer/ }));
    expect(field).toHaveValue("Ask @reviewer ");

    await user.type(field, "and @crew");
    await user.click(await screen.findByRole("option", { name: /QA crew/ }));
    expect(field).toHaveValue("Ask @reviewer and @qa ");
  });

  it("picks with the keyboard and leaves a soul unread out", async () => {
    const api = withPixies(fakeApi(), [defined(PIXIES[2])], []);
    api.pixieFile.mockRejectedValue(new Error("down"));
    const { user, field } = await openChat(api);

    await user.type(field, "@rev");
    await screen.findByRole("option", { name: "Reviewer@reviewer" });
    await act(() => new Promise((done) => setTimeout(done, 20)));
    expect(screen.getByRole("option", { name: "Reviewer@reviewer" })).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(field).toHaveValue("@reviewer ");
    expect(screen.queryByText("down")).not.toBeInTheDocument();
  });

  it("offers pixies in a new project chat", async () => {
    const api = withPixies(fakeApi());
    api.repos.mockResolvedValue([repo("cv-page")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    await user.type(screen.getByLabelText("Message"), "@rev");
    expect(await screen.findByRole("listbox", { name: "Pixies" })).toBeInTheDocument();
    expect(optionsIn("Pixies")).toEqual(["Reviewer @reviewerSoul of rev"]);
    expect(api.files).not.toHaveBeenCalled();
  });

  it("will not send a team's pixie called alone, and says why (B46)", async () => {
    const api = withPixies(fakeApi());
    const { user, field } = await openChat(api);

    await user.type(field, "@bugs look at the form");
    expect(
      screen.getByText("Bug hunter is in @qa; call the team or a solo copy"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(api.sendMessage).not.toHaveBeenCalled();

    await user.clear(field);
    await user.type(field, "@qa look at the form");
    expect(screen.queryByText(/call the team or a solo copy/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(api.sendMessage).toHaveBeenCalledWith("s1", "@qa look at the form", []);
  });

  it("shows the Mac's refusal of a team's pixie called alone (B46)", async () => {
    const api = withPixies(fakeApi());
    const why = "Ghost is in @spooks; call the team or a solo copy";
    api.sendMessage.mockRejectedValueOnce(new ApiError(422, why, "pixie_in_team"));
    const { user, field } = await openChat(api);

    await user.type(field, "@ghost boo");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(why)).toBeInTheDocument();
    expect(field).toHaveValue("@ghost boo");
    // Typing on clears it.
    await user.type(field, "!");
    expect(screen.queryByText(why)).not.toBeInTheDocument();
  });

  it("will not start a new chat calling a team's pixie alone (B46)", async () => {
    const api = withPixies(fakeApi());
    api.repos.mockResolvedValue([repo("cv-page")]);
    const { user } = await renderApp({ api });
    await user.click(screen.getByRole("tab", { name: "Projects" }));
    await user.click(screen.getByRole("button", { name: "New chat in cv-page" }));

    await user.type(screen.getByLabelText("Message"), "@qa-lead go");
    expect(screen.getByText("Lead is in @qa; call the team or a solo copy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("is not offered in a pixie's chat", async () => {
    const api = withPixies(fakeApi(), [pixie()], []);
    const { user } = await openPixie(api, pixie());

    await user.type(screen.getByLabelText("Message"), "@te");
    await act(() => new Promise((done) => setTimeout(done, 200)));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
