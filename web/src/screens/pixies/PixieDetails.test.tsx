import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { agentDefaults, pixie, session } from "../../test/fixtures.ts";
import { openPixie } from "../../test/pixies.ts";

const details = (api = fakeApi(), shown = pixie()) => openPixie(api, shown, "Details");

const sheet = (name: string) => screen.getByRole("dialog", { name });

/** Each group of the skill sheet: its heading and its rows' text. */
const groups = (picker: HTMLElement) =>
  within(picker)
    .queryAllByRole("region")
    .map((group) => [
      group.querySelector("h3")?.textContent,
      [...group.querySelectorAll("button")].map((row) => row.textContent),
    ]);

const skill = (name: string, description: string | null = null, plugin: string | null = null) => ({
  name,
  description,
  plugin,
});

describe("Pixie details", () => {
  it("saves a mascot at once", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    expect(screen.getByRole("button", { name: "invader" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "ghost" }));

    expect(api.updatePixie).toHaveBeenCalledWith("p1", { mascot: "ghost" });
    expect(screen.getByRole("button", { name: "ghost" })).toHaveAttribute("aria-pressed", "true");
  });

  it("saves a preset and a custom colour, and offers no background", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    expect(screen.getByRole("button", { name: "Colour #8B7CF6" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "Colour #E5484D" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { color: "#E5484D" });

    const custom = screen.getByLabelText<HTMLInputElement>("Custom colour value");
    let opened = false;
    custom.addEventListener("click", () => {
      opened = true;
    });
    await user.click(screen.getByRole("button", { name: "Custom colour" }));
    expect(opened).toBe(true);
    fireEvent.change(custom, { target: { value: "#12ab34" } });
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { color: "#12AB34" });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Custom colour" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    expect(screen.queryByRole("group", { name: "Background" })).not.toBeInTheDocument();
  });

  it("renames inline and shows why a slug is refused", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    await user.click(screen.getByRole("button", { name: "Edit name, Tester" }));
    const name = screen.getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Checker{Enter}");
    expect(api.updatePixie).toHaveBeenCalledWith("p1", { name: "Checker" });
    expect(api.updatePixie).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Edit name, Checker" })).toBeInTheDocument();

    api.updatePixie.mockRejectedValueOnce(new ApiError(409, "That slug is taken", null));
    await user.click(screen.getByRole("button", { name: "Edit slug, @tester" }));
    const slug = screen.getByRole("textbox", { name: "Slug" });
    await user.clear(slug);
    await user.type(slug, "reviewer{Enter}");
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { slug: "reviewer" });
    expect(await screen.findByText("That slug is taken")).toBeInTheDocument();

    // A successful change clears the message.
    await user.click(screen.getByRole("button", { name: "Edit slug, @tester" }));
    await user.clear(screen.getByRole("textbox", { name: "Slug" }));
    await user.type(screen.getByRole("textbox", { name: "Slug" }), "checker");
    await user.click(screen.getByRole("button", { name: "ghost" }));
    expect(api.updatePixie).toHaveBeenCalledWith("p1", { slug: "checker" });
    await waitFor(() => {
      expect(screen.queryByText("That slug is taken")).not.toBeInTheDocument();
    });
  });

  it("leaves the name alone when the edit is cancelled, blank or the same", async () => {
    const api = fakeApi();
    api.updatePixie.mockRejectedValueOnce(new Error("Mac asleep"));
    const { user } = await details(api);

    await user.click(screen.getByRole("button", { name: "Edit name, Tester" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "x{Escape}");
    await user.click(screen.getByRole("button", { name: "Edit name, Tester" }));
    await user.clear(screen.getByRole("textbox", { name: "Name" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "  {Enter}");
    await user.click(screen.getByRole("button", { name: "Edit name, Tester" }));
    await user.type(screen.getByRole("textbox", { name: "Name" }), "{Enter}");
    await user.click(screen.getByRole("button", { name: "Edit slug, @tester" }));
    await user.type(screen.getByRole("textbox", { name: "Slug" }), "{Escape}");
    await user.click(screen.getByRole("button", { name: "Edit slug, @tester" }));
    await user.type(screen.getByRole("textbox", { name: "Slug" }), "{Enter}");
    expect(api.updatePixie).not.toHaveBeenCalled();
    // Escape in a field cancels the edit, not the page.
    expect(screen.getByRole("tab", { name: "Details" })).toBeInTheDocument();

    // Other failures are a toast, not a note under the slug.
    await user.click(screen.getByRole("button", { name: "Edit slug, @tester" }));
    await user.type(screen.getByRole("textbox", { name: "Slug" }), "2{Enter}");
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit slug, @tester" })).toBeInTheDocument();
  });

  it("has no projects, tools or phone alerts of its own (B85)", async () => {
    await details();

    const panel = screen.getByRole("tabpanel", { name: "Details" });
    expect(within(panel).getByRole("heading", { name: "Skills" })).toBeInTheDocument();
    for (const gone of ["Projects", "Tools"]) {
      expect(within(panel).queryByRole("heading", { name: gone })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /^Phone alerts/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add project" })).not.toBeInTheDocument();
  });

  it("keeps both of two quick chip removals, saving them one after the other", async () => {
    const api = fakeApi();
    const shown = pixie({ skills: ["a", "b", "c"] });
    const { user } = await details(api, shown);
    let finish: () => void = () => undefined;
    api.updatePixie.mockImplementation(
      (_id, body) =>
        new Promise((resolve) => {
          finish = () => {
            resolve({ ...shown, ...body });
          };
        }),
    );

    await user.click(screen.getByRole("button", { name: "Remove a" }));
    await user.click(screen.getByRole("button", { name: "Remove b" }));
    expect(screen.queryByRole("button", { name: "Remove a" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove b" })).not.toBeInTheDocument();
    // The second waits for the first.
    expect(api.updatePixie).toHaveBeenCalledTimes(1);
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { skills: ["b", "c"] });

    finish();
    await waitFor(() => {
      expect(api.updatePixie).toHaveBeenCalledTimes(2);
    });
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { skills: ["c"] });
    // The first answer does not bring "b" back while the second is on its way.
    expect(screen.queryByRole("button", { name: "Remove b" })).not.toBeInTheDocument();
    finish();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Remove c" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: "Remove b" })).not.toBeInTheDocument();
  });

  it("puts a chip back when the Mac refuses its removal", async () => {
    const api = fakeApi();
    const { user } = await details(api, pixie({ skills: ["review"] }));
    api.updatePixie.mockRejectedValueOnce(new Error("Mac asleep"));

    await user.click(screen.getByRole("button", { name: "Remove review" }));
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove review" })).toBeInTheDocument();
  });

  it("sets project files, autonomy and permissions from picker sheets", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    await user.click(screen.getByRole("button", { name: "Project files: Edit" }));
    expect(
      within(sheet("Project files")).getByText("Works only in its own folder"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("menuitemradio", { name: /^Read only/ }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { project_access: "read" });

    await user.click(await screen.findByRole("button", { name: "Autonomy: Observe" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Start/ }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { autonomy: "start" });

    await user.click(await screen.findByRole("button", { name: "Permissions: Ask" }));
    // The default model takes Auto.
    expect(screen.getByRole("menuitemradio", { name: /^Auto/ })).toBeInTheDocument();
    await user.click(screen.getByRole("menuitemradio", { name: /^Plan/ }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { permission_mode: "plan" });
  });

  it("sets the model and thinking with the composer's rules", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    await user.click(await screen.findByRole("button", { name: "Model: Default" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Haiku 4.5/ }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { model: "haiku" });
    // Haiku takes no thinking level.
    expect(await screen.findByRole("button", { name: "Thinking: Not available" })).toBeDisabled();
    // Nor the Auto permission mode.
    await user.click(screen.getByRole("button", { name: "Permissions: Ask" }));
    expect(screen.queryByRole("menuitemradio", { name: /^Auto/ })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    await user.click(screen.getByRole("button", { name: "Model: Haiku 4.5" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Opus 5.5/ }));
    await user.click(await screen.findByRole("button", { name: "Thinking: Default" }));
    await user.click(screen.getByRole("menuitemradio", { name: "High" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { effort: "high" });
    expect(await screen.findByRole("button", { name: "Thinking: High" })).toBeInTheDocument();
  });

  it("sets the model and thinking back to Default", async () => {
    const api = fakeApi();
    const { user } = await details(api, pixie({ model: "opus", effort: "high" }));

    await user.click(await screen.findByRole("button", { name: "Thinking: High" }));
    await user.click(screen.getByRole("menuitemradio", { name: "Default" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { effort: null });
    expect(await screen.findByRole("button", { name: "Thinking: Default" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Model: Opus 5.5" }));
    const picker = sheet("Model");
    await user.click(within(picker).getByRole("menuitemradio", { name: /Your agent default/ }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { model: null });
    expect(await screen.findByRole("button", { name: "Model: Default" })).toBeInTheDocument();
  });

  it("shows the mode the Mac falls back to when the new model has no Auto", async () => {
    const api = fakeApi();
    const shown = pixie({ permission_mode: "auto" });
    const { user } = await details(api, shown);
    // The Mac moves a pixie in Auto to asking when its new model does not take Auto.
    api.updatePixie.mockResolvedValueOnce({ ...shown, model: "haiku", permission_mode: "default" });

    expect(await screen.findByRole("button", { name: "Permissions: Auto" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Model: Default" }));
    await user.click(screen.getByRole("menuitemradio", { name: /^Haiku 4.5/ }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { model: "haiku" });
    expect(await screen.findByRole("button", { name: "Permissions: Ask" })).toBeInTheDocument();
  });

  it("follows the agent default model while the pixie has none", async () => {
    const api = fakeApi();
    api.agentDefaults.mockResolvedValue(agentDefaults({ model: "haiku" }));
    await details(api);

    expect(await screen.findByRole("button", { name: "Thinking: Not available" })).toBeDisabled();
  });

  it("adds a skill from the list Claude Code offers, never one already chosen (B85)", async () => {
    const api = fakeApi();
    let answer: (list: ReturnType<typeof skill>[]) => void = () => undefined;
    api.pixieSkills.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );
    const { user } = await details(api, pixie({ skills: ["triage"] }));

    // At the full right of the Skills heading row.
    const add = screen.getByRole("button", { name: "Add skill" });
    expect(add.parentElement).toHaveClass("pxhrow");
    expect(add.previousElementSibling).toHaveTextContent("Skills");
    await user.click(add);
    // The sheet opens at once and says it is loading.
    expect(sheet("Add skill")).toHaveTextContent("Loading skills");
    expect(api.skills).not.toHaveBeenCalled();
    answer([
      skill("deploy", "Ships the app"),
      // A plugin's skill named without the prefix keeps its name.
      skill("lint", null, "zeta"),
      skill("review:pr", "Reviews a pull request", "review"),
      skill("review:style", null, "review"),
      skill("triage"),
      skill("zeta:go", "Goes", "zeta"),
    ]);
    const picker = sheet("Add skill");
    await within(picker).findByRole("region", { name: "Your skills" });
    expect(picker).not.toHaveTextContent("Loading skills");
    // Your skills first, then each plugin's, named without the plugin's prefix.
    expect(groups(picker)).toEqual([
      ["Your skills", ["deployShips the app"]],
      ["review", ["prReviews a pull request", "style"]],
      ["zeta", ["lint", "goGoes"]],
    ]);
    // A long list scrolls in the sheet's body, and descriptions are clamped.
    expect(picker.querySelector(".pxskills")?.closest(".sh-b")).not.toBeNull();
    await user.click(within(picker).getByRole("button", { name: /^pr/ }));
    // The full name is saved.
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { skills: ["triage", "review:pr"] });
    expect(screen.queryByRole("dialog", { name: "Add skill" })).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Remove review:pr" })).toBeInTheDocument();

    api.pixieSkills.mockResolvedValue([
      skill("deploy", "Ships the app"),
      skill("review:pr", "Reviews a pull request", "review"),
    ]);
    await user.click(screen.getByRole("button", { name: "Add skill" }));
    await within(sheet("Add skill")).findByRole("region", { name: "Your skills" });
    expect(groups(sheet("Add skill"))).toEqual([["Your skills", ["deployShips the app"]]]);
    await user.click(within(sheet("Add skill")).getByRole("button", { name: "Done" }));
    expect(api.updatePixie).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Remove triage" }));
    expect(api.updatePixie).toHaveBeenLastCalledWith("p1", { skills: ["review:pr"] });
  });

  it("filters the skills by name and description", async () => {
    const api = fakeApi();
    api.pixieSkills.mockResolvedValue([
      skill("deploy", "Ships the app"),
      skill("review:pr", "Reviews a pull request", "review"),
      skill("review:style", null, "review"),
    ]);
    const { user } = await details(api);

    await user.click(screen.getByRole("button", { name: "Add skill" }));
    const picker = sheet("Add skill");
    const search = await within(picker).findByRole("searchbox", { name: "Search skills" });
    await user.type(search, "PULL");
    expect(groups(picker)).toEqual([["review", ["prReviews a pull request"]]]);
    await user.clear(search);
    await user.type(search, "sty");
    expect(groups(picker)).toEqual([["review", ["style"]]]);
    await user.clear(search);
    await user.type(search, "nothing like it");
    expect(groups(picker)).toEqual([]);
    expect(picker).toHaveTextContent("No matching skills");
  });

  it("says when no skills are available, or every one is chosen", async () => {
    const api = fakeApi();
    api.pixieSkills.mockResolvedValueOnce([]);
    const { user } = await details(api);

    expect(screen.getByText("All skills")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add skill" }));
    expect(await within(sheet("Add skill")).findByText("No skills installed")).toBeInTheDocument();
    expect(within(sheet("Add skill")).queryByRole("searchbox")).not.toBeInTheDocument();
    await user.keyboard("{Escape}");

    api.pixieSkills.mockResolvedValue([skill("review")]);
    await user.click(screen.getByRole("button", { name: "Add skill" }));
    await user.click(await within(sheet("Add skill")).findByRole("button", { name: /^review/ }));
    await user.click(await screen.findByRole("button", { name: "Add skill" }));
    expect(
      await within(sheet("Add skill")).findByText("Every skill is chosen"),
    ).toBeInTheDocument();
  });

  it("closes the skill list when the skills cannot load", async () => {
    const api = fakeApi();
    api.pixieSkills.mockRejectedValue(new Error("claude plugin failed"));
    const { user } = await details(api);

    await user.click(screen.getByRole("button", { name: "Add skill" }));
    expect(await screen.findByText("claude plugin failed")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Add skill" })).not.toBeInTheDocument();
  });

  it("opens the soul, counts memory facts and habits", async () => {
    const api = fakeApi();
    api.pixieFile.mockImplementation((_id, name) =>
      Promise.resolve(
        name === "memory"
          ? {
              text: "# Memory\n\n- 2026-10-01: Uses pnpm\n- 2026-10-02: Likes short PRs\n",
              hash: "m",
            }
          : { text: "Be kind.", hash: "s" },
      ),
    );
    const { user } = await details(api);

    expect(await screen.findByRole("button", { name: /^Memory.*2 facts/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Habits.*0 habits/ })).toBeInTheDocument();
    expect(screen.getByText("Who this pixie is and the rules it follows")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Soul/ }));
    expect(await screen.findByDisplayValue("Be kind.")).toBeInTheDocument();
    await user.click(within(sheet("Soul")).getByRole("button", { name: "Close" }));

    await user.click(screen.getByRole("button", { name: /^Memory/ }));
    expect(await within(sheet("Memory")).findByText("Uses pnpm")).toBeInTheDocument();
  });

  it("counts one fact as one", async () => {
    const api = fakeApi();
    api.pixieFile.mockResolvedValueOnce({ text: "- 2026-10-01: Uses pnpm\n", hash: "m" });
    await details(api);
    expect(await screen.findByRole("button", { name: /^Memory.*1 fact$/ })).toBeInTheDocument();
  });

  it("counts memory facts again, quietly, when the pixie changes or its turn ends", async () => {
    const api = fakeApi();
    const shown = pixie({ chat_session_id: "c1" });
    api.sessions.mockImplementation((archived) =>
      Promise.resolve(
        archived ? [] : [session({ id: "c1", repo: "pixie:p1", pixie_id: "p1", state: "running" })],
      ),
    );
    api.pixieFile.mockResolvedValueOnce({ text: "- a\n", hash: "m" });
    const { push } = await details(api, shown);
    expect(await screen.findByRole("button", { name: /^Memory.*1 fact$/ })).toBeInTheDocument();

    // The turn ends: the pixie may have saved a fact.
    api.pixieFile.mockResolvedValueOnce({ text: "- a\n- b\n", hash: "m2" });
    push({ type: "session.state", session_id: "c1", payload: { state: "idle" } });
    expect(await screen.findByRole("button", { name: /^Memory.*2 facts$/ })).toBeInTheDocument();

    // A failed count keeps the last one, without a toast.
    api.pixieFile.mockRejectedValueOnce(new Error("Mac asleep"));
    push({
      type: "pixie.updated",
      session_id: null,
      payload: { pixie: { ...shown, updated_at: "2026-10-14T10:00:00Z" } },
    });
    await waitFor(() => {
      expect(api.pixieFile).toHaveBeenCalledTimes(3);
    });
    expect(screen.queryByText("Mac asleep")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Memory.*2 facts$/ })).toBeInTheDocument();
  });

  it("hides the pixie", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    await user.click(screen.getByRole("switch", { name: "Hidden" }));
    expect(api.updatePixie).toHaveBeenCalledWith("p1", { hidden: true });
  });

  it("resets the conversation after asking", async () => {
    const api = fakeApi();
    const { user } = await details(api);

    expect(screen.getByText("Clear all messages and start fresh")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reset conversation" }));
    const confirm = screen.getByRole("alertdialog", { name: "Reset conversation?" });
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(api.resetPixie).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Reset conversation" }));
    await user.click(
      within(screen.getByRole("alertdialog", { name: "Reset conversation?" })).getByRole("button", {
        name: "Reset",
      }),
    );
    expect(api.resetPixie).toHaveBeenCalledWith("p1");
  });

  it("deletes the pixie after asking and goes back", async () => {
    const api = fakeApi();
    api.deletePixie.mockRejectedValueOnce(new Error("Mac asleep"));
    const { user } = await details(api);

    const remove = async () => {
      await user.click(screen.getByRole("button", { name: "Delete pixie" }));
      await user.click(
        within(screen.getByRole("alertdialog", { name: "Delete Tester?" })).getByRole("button", {
          name: "Delete",
        }),
      );
    };
    await remove();
    expect(await screen.findByText("Mac asleep")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Details" })).toBeInTheDocument();

    await remove();
    expect(api.deletePixie).toHaveBeenLastCalledWith("p1");
    await waitFor(() => {
      expect(screen.queryByRole("tab", { name: "Details" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: /Pixies/ })).toBeInTheDocument();
  });
});
