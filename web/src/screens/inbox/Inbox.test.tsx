import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Approval } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import {
  approval,
  check,
  diff,
  mergeApproval,
  pixie,
  prStatus,
  plan,
  question,
  report,
  repo,
  review,
  session,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

function withItems(items: Approval[], sessions = [session()]) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("narrative"), repo("cv-page")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : sessions));
  api.approvals.mockResolvedValue(items);
  api.resolveApproval.mockImplementation((id) =>
    Promise.resolve({ ...defined(items.find((a) => a.id === id)), status: "resolved" }),
  );
  return api;
}

const card = (name: RegExp) => screen.getByRole("article", { name });

// What approving sends from the default diff fixture: the HEAD and the review it showed.
const SEEN = {
  expected_fingerprint: "f1ngerprint",
  expected_head: "c0ffee0000000000000000000000000000000000",
};

/** The review card's diff has loaded, so approving is possible. */
async function reviewLoaded(name = "Approve and open PR") {
  const button = screen.getAllByRole("button", { name })[0];
  await waitFor(() => {
    expect(button).toBeEnabled();
  });
  return defined(button);
}

/** Opens every row that is closed, as rows start closed (B102 item 10). */
function openAll() {
  for (const button of screen.queryAllByRole("button", { name: "Show details" })) {
    fireEvent.click(button);
  }
}

/** The app on Needs you, the tab it opens on, with every row open to its full item. */
async function renderInbox(options: Parameters<typeof renderApp>[0]) {
  const rendered = await renderApp(options);
  openAll();
  return rendered;
}

describe("Needs you rows (B102 item 10)", () => {
  const line = (item: HTMLElement) => item.querySelector(".nline")?.textContent;
  const mark = (item: HTMLElement) => item.querySelector(".nrow")?.firstElementChild;

  it("show one short line per item, closed, under a flat header with the count", async () => {
    const failing = session({
      id: "s2",
      title: "Failing checks",
      pr: prStatus({ checks: [check("unit", "failure"), check("e2e", "failure")] }),
    });
    const stuck = session({
      id: "s3",
      title: "Stuck one",
      state: "running",
      stuck: { reason: "repeating", since: "2026-10-06T09:48:00Z", details: "Same call." },
    });
    const api = withItems([approval(), review({ session_id: "s3" })], [session(), failing, stuck]);
    await renderApp({ api });

    expect(screen.getByRole("heading", { level: 1, name: "Needs you" })).toBeInTheDocument();
    expect(screen.getByRole("banner")).toHaveTextContent("Needs you4");
    const items = screen.getAllByRole("article");
    expect(items.map(line)).toEqual([
      "Permission · Bash npm install zod",
      "Ready for review · +48 -19 in 3 files",
      "Checks failed · unit, e2e",
      "Stuck · Repeating a call",
    ]);
    expect(items.map((item) => mark(item)?.className)).toEqual([
      "dot s-wait",
      "dot s-rev",
      "dot s-fail",
      "dot s-wait",
    ]);
    // Closed by default: no Approve until the row opens.
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    for (const chevron of screen.getAllByRole("button", { name: "Show details" })) {
      expect(chevron).toHaveAttribute("aria-expanded", "false");
    }
  });

  it("open in place from the chevron or a tap on the row, and close again", async () => {
    const { user } = await renderApp({ api: withItems([approval()]) });
    const item = card(/Permission/);

    await user.click(within(item).getByRole("button", { name: "Show details" }));
    expect(within(item).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(within(item).getByText("npm install zod")).toHaveClass("cmdbox");
    await user.click(within(item).getByRole("button", { name: "Hide details" }));
    expect(within(item).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();

    await user.click(defined(item.querySelector<HTMLElement>(".nline")));
    expect(within(item).getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("do not repeat the row's name or line inside the open item", async () => {
    const api = withItems(
      [review(), mergeApproval({ session_id: "s2" })],
      [session(), session({ id: "s2", title: "Merge me" })],
    );
    await renderInbox({ api });

    const open = (name: RegExp) => defined(card(name).querySelector(".nexp"));
    expect(open(/Ready for review/)).not.toHaveTextContent("Validate contact form");
    expect(open(/Ready to merge/)).not.toHaveTextContent("#7");
  });

  it("name a review whose chat is not loaded after the review, as its commit message", async () => {
    await renderInbox({ api: withItems([review({ title: "Raise contrast" })], []) });

    const item = card(/Ready for review/);
    expect(within(item).getByRole("button", { name: "Raise contrast" })).toBeInTheDocument();
    expect(within(item).getByLabelText("Commit message")).toHaveValue("Raise contrast");
  });

  it("open the chat from its name without opening the row", async () => {
    const { user } = await renderApp({ api: withItems([approval()]) });

    await user.click(screen.getByRole("button", { name: "Validate contact form" }));

    expect(
      await screen.findByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("open a plan in place, named by its first line", async () => {
    const { user } = await renderApp({ api: withItems([plan()]) });
    const item = card(/^Plan/);

    expect(item.querySelector(".nline")).toHaveTextContent("Plan · Plan");
    await user.click(within(item).getByRole("button", { name: "Show details" }));
    expect(within(item).getByText("zod")).toBeInTheDocument();
  });

  it("dismiss a report from its open row, and open its pixie", async () => {
    const api = withItems([]);
    api.pixies.mockResolvedValue([pixie()]);
    api.pixieReports.mockResolvedValue([report()]);
    const { user } = await renderApp({ api });
    const item = card(/^Report/);

    await user.click(within(item).getByRole("button", { name: "Show details" }));
    expect(within(item).getByText("Two runs failed on the lint step.")).toBeInTheDocument();
    await user.click(within(item).getByRole("button", { name: "Dismiss" }));
    expect(api.readReport).toHaveBeenCalledWith("rep1");
    await waitFor(() => {
      expect(item).not.toBeInTheDocument();
    });
  });

  it("open a report's pixie from its open row", async () => {
    const api = withItems([]);
    api.pixies.mockResolvedValue([pixie()]);
    api.pixieReports.mockResolvedValue([report({ body: "" })]);
    const { user } = await renderApp({ api });
    const item = card(/^Report/);

    await user.click(within(item).getByRole("button", { name: "Show details" }));
    expect(item.querySelector(".pxrb")).toBeNull();
    await user.click(within(item).getByRole("button", { name: "Open" }));
    expect(screen.getByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
  });

  it("name a report's pixie, with its severity and title, opening the pixie", async () => {
    const api = withItems([]);
    api.pixies.mockResolvedValue([pixie()]);
    api.pixieReports.mockResolvedValue([
      report(),
      report({
        id: "r2",
        severity: "warn",
        title: "Flaky tests",
        created_at: "2026-10-14T08:00:00Z",
      }),
    ]);
    const { user } = await renderApp({ api });

    const [flaky, failing] = screen.getAllByRole("article");
    expect(line(defined(failing))).toBe("Needs action · CI is failing on main");
    expect(mark(defined(failing))).toHaveClass("s-fail");
    expect(line(defined(flaky))).toBe("Warning · Flaky tests");
    expect(mark(defined(flaky))).toHaveClass("s-wait");
    await user.click(within(defined(flaky)).getByRole("button", { name: "Tester" }));
    expect(screen.getByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
  });
});

describe("Inbox", () => {
  it("groups pending items by project with counts", async () => {
    const api = withItems([
      approval(),
      question({ repo: "narrative", session_id: "n1", title: "Parser" }),
    ]);
    await renderInbox({ api });

    const groups = screen.getAllByRole("heading", { level: 2 });
    expect(groups.map((h) => h.textContent)).toEqual(["narrative1", "cv-page1"]);
    expect(screen.getByRole("tab", { name: "Needs you 2" })).toBeInTheDocument();
  });

  it("groups a pixie's items under the pixie and opens its page", async () => {
    const api = withItems(
      [
        approval({ repo: "pixie:p1", session_id: "c1" }),
        approval({ id: "q2", repo: "pixie:gone", session_id: "c2" }),
      ],
      [session({ id: "c1", repo: "pixie:p1", pixie_id: "p1" })],
    );
    api.pixies.mockResolvedValue([pixie()]);
    const { user } = await renderInbox({ api });

    const groups = screen.getAllByRole("heading", { level: 2 });
    expect(groups.map((h) => h.textContent)).toEqual(["Pixie1", "Tester1"]);
    expect(screen.queryByText("pixie:p1")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "bluebell" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Pixie" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open Tester" }));
    expect(screen.getByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
  });

  it("approves, rejects and always allows permissions with buttons", async () => {
    const api = withItems([approval(), approval({ id: "q8" }), approval({ id: "q9" })]);
    const { user } = await renderInbox({ api });
    const [first, second, third] = screen.getAllByRole("article");

    await user.click(within(defined(first)).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Approved: npm install zod")).toBeInTheDocument();
    await user.click(within(defined(second)).getByRole("button", { name: "Reject" }));
    await user.click(within(defined(third)).getByRole("button", { name: "Always allow Bash" }));

    expect(api.resolveApproval.mock.calls).toEqual([
      ["q1", { behavior: "allow", always: false }],
      ["q8", { behavior: "deny", always: false }],
      ["q9", { behavior: "allow", always: true }],
    ]);
    await waitFor(() => {
      expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
    });
    expect(screen.getByText("Always allowed: Bash")).toBeInTheDocument();
  });

  it("names Claude Code's suggested rule on Always allow", async () => {
    const api = withItems([
      approval({
        payload: { tool: "Bash", input: { command: "npm test" }, always_rule: "Bash(npm test:*)" },
      }),
    ]);
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Always allow Bash(npm test:*)" }));

    expect(api.resolveApproval).toHaveBeenCalledWith("q1", { behavior: "allow", always: true });
    expect(await screen.findByText("Always allowed: Bash(npm test:*)")).toBeInTheDocument();
  });

  it("shows why Claude Code asks, when it says", async () => {
    const why = "Path is outside the allowed working directories";
    const api = withItems([
      approval({
        payload: { tool: "Bash", input: { command: "ls /etc" }, title: null, reason: why },
      }),
      approval({ id: "q8", payload: { tool: "Bash", input: { command: "ls" }, reason: null } }),
    ]);
    await renderInbox({ api });
    const [first, second] = screen.getAllByRole("article");

    expect(within(defined(first)).getByText(why)).toBeInTheDocument();
    expect(defined(second).querySelectorAll(".why")).toHaveLength(0);
  });

  it("keeps the card usable when resolving fails", async () => {
    const api = withItems([approval()]);
    api.resolveApproval.mockRejectedValueOnce(new ApiError(409, "approval q1 is expired"));
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("approval q1 is expired")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("returns focus to what opened a chat after closing it", async () => {
    const { user } = await renderInbox({ api: withItems([approval()]) });
    const title = screen.getByRole("button", { name: "Validate contact form" });

    await user.click(title);
    await screen.findByRole("region", { name: "Validate contact form" });
    await user.click(screen.getByRole("button", { name: "Back to cv-page" }));

    expect(screen.getByRole("button", { name: "Validate contact form" })).toHaveFocus();
  });

  it("opens the chat from the card", async () => {
    const api = withItems([approval()]);
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Validate contact form" }));

    expect(
      await screen.findByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
  });

  it("orders a project's cards approvals, failed checks, stuck, and counts them all", async () => {
    const failing = session({
      id: "s2",
      title: "Failing checks",
      pr: prStatus({ checks: [check("unit", "failure")] }),
    });
    const stuck = session({
      id: "s3",
      title: "Stuck one",
      state: "running",
      stuck: { reason: "silent", since: "2026-10-06T09:48:00Z", details: "No new output." },
    });
    await renderInbox({ api: withItems([approval()], [session(), failing, stuck]) });

    expect(screen.getAllByRole("article").map((a) => a.getAttribute("aria-label"))).toEqual([
      "Permission: Validate contact form",
      "Checks failed: Failing checks",
      "Stuck: Stuck one",
    ]);
    expect(screen.getByRole("tab", { name: "Needs you 3" })).toBeInTheDocument();
  });

  it("falls back to the approval's title when the session is unknown", async () => {
    await renderInbox({ api: withItems([approval({ title: "Gone" })], []) });

    expect(screen.getByRole("button", { name: "Gone" })).toBeInTheDocument();
  });
});

describe("question cards", () => {
  it("preselect the recommended option and send the choice", async () => {
    const api = withItems([question()]);
    const { user } = await renderInbox({ api });

    expect(screen.getByRole("radio", { name: /DAG/ })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("radio", { name: /Tree/ }));
    expect(screen.getByRole("radio", { name: /DAG/ })).toHaveAttribute("aria-checked", "false");
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    expect(api.resolveApproval).toHaveBeenCalledWith("q2", { answers: { "DAG or tree?": "Tree" } });
    expect(await screen.findByText("Answer sent")).toBeInTheDocument();
  });

  it("send typed text through Other instead of a choice", async () => {
    const api = withItems([question()]);
    const { user } = await renderInbox({ api });
    const send = screen.getByRole("button", { name: "Send answer" });

    // No text box until Other is chosen.
    expect(screen.queryByPlaceholderText("Type your answer")).not.toBeInTheDocument();
    const other = screen.getByRole("radio", { name: "Other" });
    expect(other).toHaveAttribute("aria-checked", "false");
    await user.click(other);
    expect(other).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: /DAG/ })).toHaveAttribute("aria-checked", "false");
    const box = screen.getByRole("textbox", { name: "Your answer" });
    expect(box).toHaveAttribute("placeholder", "Type your answer");
    expect(box).toHaveFocus();
    expect(send).toBeDisabled();
    await user.type(box, "   ");
    expect(send).toBeDisabled();

    // Another choice puts the text box away, and Other brings it back empty.
    await user.click(screen.getByRole("radio", { name: /Tree/ }));
    expect(other).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("textbox", { name: "Your answer" })).not.toBeInTheDocument();
    expect(send).toBeEnabled();
    await user.click(other);
    expect(screen.getByRole("textbox", { name: "Your answer" })).toHaveValue("");
    await user.type(screen.getByRole("textbox", { name: "Your answer" }), "  Both  ");
    // Choosing Other again keeps what was typed.
    await user.click(other);
    expect(screen.getByRole("textbox", { name: "Your answer" })).toHaveValue("  Both  ");
    await user.type(screen.getByRole("textbox", { name: "Your answer" }), "{Enter}");

    expect(api.resolveApproval).toHaveBeenCalledWith("q2", { answers: { "DAG or tree?": "Both" } });
  });

  it("add Other's text to the picked choices of a multiple choice question", async () => {
    const multi = question({
      payload: {
        questions: [
          {
            question: "Which checks?",
            multi_select: true,
            options: [{ label: "Lint", recommended: true }, { label: "Tests" }],
          },
        ],
      },
    });
    const api = withItems([multi]);
    const { user } = await renderInbox({ api });
    const send = screen.getByRole("button", { name: "Send answer" });

    await user.click(screen.getByRole("checkbox", { name: "Other" }));
    // Other leaves the other choices as they are.
    expect(screen.getByRole("checkbox", { name: /Lint/ })).toHaveAttribute("aria-checked", "true");
    expect(send).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Your answer" }), " Types ");
    expect(send).toBeEnabled();
    await user.click(send);

    expect(api.resolveApproval).toHaveBeenLastCalledWith("q2", {
      answers: { "Which checks?": ["Lint", "Types"] },
    });
  });

  it("drop Other's text when Other is unchecked", async () => {
    const multi = question({
      payload: {
        questions: [
          { question: "Which checks?", multi_select: true, options: [{ label: "Lint" }] },
        ],
      },
    });
    const api = withItems([multi]);
    const { user } = await renderInbox({ api });
    const send = screen.getByRole("button", { name: "Send answer" });

    const other = screen.getByRole("checkbox", { name: "Other" });
    await user.click(other);
    await user.type(screen.getByRole("textbox", { name: "Your answer" }), "Types");
    await user.click(screen.getByRole("checkbox", { name: "Lint" }));
    await user.click(other);
    expect(other).toHaveAttribute("aria-checked", "false");
    expect(screen.queryByRole("textbox", { name: "Your answer" })).not.toBeInTheDocument();
    await user.click(send);

    expect(api.resolveApproval).toHaveBeenLastCalledWith("q2", {
      answers: { "Which checks?": ["Lint"] },
    });
  });

  it("need an answer for every question and allow several choices", async () => {
    const multi = question({
      payload: {
        questions: [
          {
            question: "Which checks?",
            multi_select: true,
            options: [
              { label: "Lint", recommended: true },
              { label: "Tests", recommended: true },
            ],
          },
          { question: "Branch?", options: [{ label: "main" }] },
        ],
      },
    });
    const api = withItems([multi]);
    api.resolveApproval.mockRejectedValueOnce(new TypeError("offline"));
    const { user } = await renderInbox({ api });
    const send = screen.getByRole("button", { name: "Send answer" });

    expect(screen.getAllByRole("checkbox", { checked: true })).toHaveLength(2);
    expect(send).toBeDisabled();
    await user.click(screen.getByRole("radio", { name: "main" }));
    await user.click(screen.getByRole("checkbox", { name: /Lint/ }));
    await user.click(send);
    expect(await screen.findByText("offline")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /Tests/ }));
    expect(send).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: /Lint/ }));
    await user.click(send);

    expect(api.resolveApproval).toHaveBeenLastCalledWith("q2", {
      answers: { "Which checks?": ["Lint"], "Branch?": "main" },
    });
  });
});

describe("review cards", () => {
  it("approve with an editable commit message", async () => {
    const api = withItems([review()]);
    api.approve.mockResolvedValueOnce(session({ pr_url: "https://pr/1" }));
    const { user } = await renderInbox({ api });
    const message = screen.getByLabelText("Commit message");

    expect(message).toHaveValue("Validate contact form");
    expect(screen.getByText("Raised contrast")).toBeInTheDocument();
    await user.clear(message);
    await user.type(message, "Polish dark mode");
    await user.click(await reviewLoaded());

    expect(api.approve).toHaveBeenCalledWith("s1", { commit_message: "Polish dark mode", ...SEEN });
    expect(await screen.findByText("Pull request opened")).toBeInTheDocument();
    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
  });

  it("commit in-place work with only its changed files, without pushing", async () => {
    const api = withItems(
      [review({ payload: { paths: ["a.ts"] } })],
      [session({ mode: "in_place" })],
    );
    const { user } = await renderInbox({ api });

    expect(await screen.findByText("Commits to agent/contact, not pushed")).toBeInTheDocument();
    expect(screen.queryByText(/Pushes to/)).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText("Commit message"));
    await user.click(await reviewLoaded("Approve and commit"));

    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      files: ["a.ts"],
      open_pr: false,
      push: false,
      ...SEEN,
    });
    expect(await screen.findByText("Committed to agent/contact, not pushed")).toBeInTheDocument();
  });

  it("commit in-place work on a detached HEAD without naming a branch", async () => {
    const api = withItems([review()], [session({ mode: "in_place" })]);
    api.diff.mockResolvedValue({ ...diff(), head: { ...diff().head, branch: null } });
    const { user } = await renderInbox({ api });

    await user.click(await reviewLoaded("Approve and commit"));

    expect(await screen.findByText("Committed, not pushed")).toBeInTheDocument();
  });

  it("only commit a worktree chat whose pull request is already open", async () => {
    const url = "https://github.com/me/cv-page/pull/7";
    const api = withItems([review()], [session({ pr_url: url })]);
    api.approve.mockResolvedValueOnce(session({ pr_url: url }));
    const { user } = await renderInbox({ api });

    expect(await screen.findByText("Commits to agent/contact, not pushed")).toBeInTheDocument();
    expect(screen.queryByText(/Pushes to/)).not.toBeInTheDocument();
    await user.click(await reviewLoaded("Approve and commit"));

    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      open_pr: false,
      push: false,
      ...SEEN,
    });
    expect(await screen.findByText("Committed to agent/contact, not pushed")).toBeInTheDocument();
    expect(screen.queryByText("Pull request opened")).not.toBeInTheDocument();
  });

  it("stay up for review when approving or sending feedback fails", async () => {
    const api = withItems([review()]);
    api.approve.mockRejectedValueOnce(new ApiError(409, "the agent changed git refs itself"));
    api.feedback.mockRejectedValueOnce(new ApiError(409, "session is working"));
    const { user } = await renderInbox({ api });

    await user.click(await reviewLoaded());
    expect(await screen.findByText("the agent changed git refs itself")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Feedback" }));
    await user.type(screen.getByLabelText("Feedback"), "More{Enter}");

    expect(await screen.findByText("session is working")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send feedback" })).toBeEnabled();
  });

  it("offer no reject for a review", async () => {
    const { user } = await renderInbox({ api: withItems([review()]) });

    const article = card(/Ready for review/);
    expect(within(article).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    await user.click(within(article).getByRole("button", { name: "View changes" }));
    const sheet = await screen.findByRole("dialog");
    expect(within(sheet).queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Approve and open PR" })).toBeInTheDocument();
  });

  it("send one approval for two quick taps", async () => {
    const api = withItems([review(), approval()]);
    let finish: (value: ReturnType<typeof session>) => void = () => undefined;
    api.approve.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    let allow: (value: Approval) => void = () => undefined;
    api.resolveApproval.mockReturnValueOnce(
      new Promise((resolve) => {
        allow = resolve;
      }),
    );
    await renderInbox({ api });
    await reviewLoaded();

    const approveReview = within(card(/Ready for review/)).getByRole("button", {
      name: "Approve and open PR",
    });
    fireEvent.click(approveReview);
    fireEvent.click(approveReview);
    const allowIt = within(card(/Permission/)).getByRole("button", { name: "Approve" });
    fireEvent.click(allowIt);
    fireEvent.click(within(card(/Permission/)).getByRole("button", { name: "Reject" }));

    expect(api.approve).toHaveBeenCalledTimes(1);
    expect(api.resolveApproval).toHaveBeenCalledTimes(1);
    finish(session());
    allow({ ...approval(), status: "resolved" });
    expect(await screen.findByText("Nothing needs you.")).toBeInTheDocument();
  });

  it("refetch the session and the diff when approving is refused, then say why", async () => {
    const api = withItems([review()]);
    const why = "Large files need git-lfs.";
    api.approve.mockRejectedValueOnce(new ApiError(409, why, "lfs_unsupported"));
    await renderInbox({ api });
    fireEvent.click(await reviewLoaded());

    expect(await screen.findByText(why)).toBeInTheDocument();
    expect(api.session).toHaveBeenCalledWith("s1");
    await waitFor(() => {
      expect(api.diff).toHaveBeenCalledTimes(2);
    });
    // Approving is possible again once the branch as it is now has loaded.
    await reviewLoaded();
  });

  it("show where the work is pushed", async () => {
    const api = withItems([review()]);
    const { user } = await renderInbox({ api });

    // On the card, before the diff is opened.
    const onCard = card(/Ready for review/);
    expect(await within(onCard).findByText("Pushes to agent/contact")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "View changes" }));
    const sheet = await screen.findByRole("dialog", { name: "Validate contact form" });

    expect(await within(sheet).findByText("Pushes to agent/contact")).toBeInTheDocument();
    const approve = within(sheet).getByRole("button", { name: "Approve and open PR" });
    await waitFor(() => {
      expect(approve).toBeEnabled();
    });
    await user.click(approve);

    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      ...SEEN,
    });
  });

  it("keep Approve from publishing until the changes have loaded", async () => {
    const api = withItems([review()]);
    let finish: (value: ReturnType<typeof diff>) => void = () => undefined;
    api.diff.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    await renderInbox({ api });
    const approve = screen.getByRole("button", { name: "Approve and open PR" });

    expect(approve).toBeDisabled();
    fireEvent.click(approve);
    expect(api.approve).not.toHaveBeenCalled();
    await act(async () => {
      finish(diff());
      await Promise.resolve();
    });

    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      ...SEEN,
    });
  });

  it("keep the reviewed changes on screen but not approvable while they reload", async () => {
    const api = withItems([review()]);
    api.approve.mockRejectedValueOnce(
      new ApiError(409, "The changes are different from the review you saw.", "review_changed"),
    );
    let finish: (value: ReturnType<typeof diff>) => void = () => undefined;
    api.diff.mockResolvedValueOnce(diff()).mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await renderInbox({ api });
    await user.click(await reviewLoaded());

    // The daemon's reason, then the review it refused stays shown while the new one loads.
    expect(
      await screen.findByText("The changes are different from the review you saw."),
    ).toBeInTheDocument();
    const approve = screen.getByRole("button", { name: "Approve and open PR" });
    expect(screen.getByText("Pushes to agent/contact")).toBeInTheDocument();
    expect(approve).toBeDisabled();
    await user.click(approve);
    expect(api.approve).toHaveBeenCalledOnce();

    await act(async () => {
      finish({ ...diff(), fingerprint: "changed" });
      await Promise.resolve();
    });
    // Approving now sends the review that is on screen.
    expect(approve).toBeEnabled();
    await user.click(approve);
    expect(api.approve).toHaveBeenLastCalledWith("s1", {
      commit_message: "Validate contact form",
      expected_fingerprint: "changed",
      expected_head: "c0ffee0000000000000000000000000000000000",
    });
  });

  it("load the changes again when the chat changes", async () => {
    const api = withItems([review()]);
    const { push } = await renderInbox({ api });
    await reviewLoaded();
    expect(api.diff).toHaveBeenCalledOnce();

    push({ id: 5, type: "session.state", session_id: "s1", payload: { state: "idle" } });

    await waitFor(() => {
      expect(api.diff).toHaveBeenCalledTimes(2);
    });
  });

  it("say on the card when the changes could not be loaded, and try again", async () => {
    const api = withItems([review()]);
    api.diff.mockRejectedValueOnce(new ApiError(500, "Request failed (500)"));
    const { user } = await renderInbox({ api });
    const onCard = card(/Ready for review/);

    expect(
      await within(onCard).findByText(/The changes could not be loaded\./),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and open PR" })).toBeDisabled();
    await user.click(within(onCard).getByRole("button", { name: "Try again" }));

    expect(await within(onCard).findByText("Pushes to agent/contact")).toBeInTheDocument();
    expect(within(onCard).queryByText(/could not be loaded/)).not.toBeInTheDocument();
    await reviewLoaded();
  });

  it("check the changes again when the branch moved", async () => {
    const api = withItems([review()]);
    api.approve.mockRejectedValueOnce(
      new ApiError(409, "The branch changed since you looked.", "head_changed"),
    );
    api.diff
      .mockResolvedValueOnce(diff())
      .mockResolvedValueOnce(diff())
      .mockResolvedValueOnce({
        ...diff(),
        head: { commit: "beef", branch: "agent/moved" },
        fingerprint: "moved",
      });
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "View changes" }));
    const sheet = await screen.findByRole("dialog", { name: "Validate contact form" });
    await within(sheet).findByText("Pushes to agent/contact");
    const approve = within(sheet).getByRole("button", { name: "Approve and open PR" });
    await waitFor(() => {
      expect(approve).toBeEnabled();
    });
    await user.click(approve);

    expect(
      await screen.findByText("The branch moved since you looked. Check the changes again."),
    ).toBeInTheDocument();
    expect(await within(sheet).findByText("Pushes to agent/moved")).toBeInTheDocument();
    expect(api.diff).toHaveBeenCalledTimes(3);
    await waitFor(() => {
      expect(approve).toBeEnabled();
    });
    await user.click(approve);
    expect(api.approve).toHaveBeenLastCalledWith("s1", {
      commit_message: "Validate contact form",
      expected_fingerprint: "moved",
      expected_head: "beef",
    });
  });

  it("keep the newest diff when an older answer arrives late", async () => {
    const api = withItems([review()]);
    let finish: (value: ReturnType<typeof diff>) => void = () => undefined;
    api.diff
      .mockResolvedValueOnce(diff())
      .mockReturnValueOnce(
        new Promise((resolve) => {
          finish = resolve;
        }),
      )
      .mockResolvedValueOnce({ ...diff(), head: { commit: "new", branch: "agent/new" } });
    const { user } = await renderInbox({ api });
    await reviewLoaded();

    await user.click(screen.getByRole("button", { name: "View changes" }));
    await user.click(screen.getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: "View changes" }));
    const sheet = await screen.findByRole("dialog", { name: "Validate contact form" });
    expect(await within(sheet).findByText("Pushes to agent/new")).toBeInTheDocument();
    await act(async () => {
      finish({ ...diff(), head: { commit: "old", branch: "agent/old" } });
      await Promise.resolve();
    });

    expect(within(sheet).getByText("Pushes to agent/new")).toBeInTheDocument();
    expect(screen.queryByText("Pushes to agent/old")).not.toBeInTheDocument();
  });

  it("leave out the branch and the expected HEAD when HEAD is detached", async () => {
    const api = withItems([review()]);
    api.diff.mockResolvedValue({ ...diff(), head: { commit: null, branch: null } });
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "View changes" }));
    const sheet = await screen.findByRole("dialog", { name: "Validate contact form" });
    await within(sheet).findByRole("region", { name: "app/globals.css" });
    expect(screen.queryByText(/Pushes to/)).not.toBeInTheDocument();
    const approve = within(sheet).getByRole("button", { name: "Approve and open PR" });
    await waitFor(() => {
      expect(approve).toBeEnabled();
    });
    await user.click(approve);

    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      expected_fingerprint: "f1ngerprint",
    });
  });

  it("say why approving failed, and still say why it was refused without the session", async () => {
    const api = withItems([review()]);
    api.approve
      .mockRejectedValueOnce(new ApiError(502, "push failed"))
      .mockRejectedValueOnce(new ApiError(409, "The branch is gone.", "conflict"));
    api.session.mockRejectedValue(new ApiError(500, "Request failed (500)"));
    const { user } = await renderInbox({ api });
    const approve = await reviewLoaded();

    await user.click(approve);
    expect(await screen.findByText("push failed")).toBeInTheDocument();
    // Only the card's own load: a failure that is not a refusal does not load it again.
    expect(api.diff).toHaveBeenCalledOnce();
    await user.click(approve);

    expect(await screen.findByText("The branch is gone.")).toBeInTheDocument();
    expect(api.session).toHaveBeenCalledWith("s1");
    expect(approve).toBeEnabled();
  });

  it("say why approving waits for background work", async () => {
    const api = withItems([review()]);
    const why = "Background tasks are still running. Approve once they finish.";
    api.approve.mockRejectedValueOnce(new ApiError(409, why, "background_running"));
    const { user } = await renderInbox({ api });

    await user.click(await reviewLoaded());

    expect(await screen.findByText(why)).toBeInTheDocument();
    await reviewLoaded();
  });

  it("offer pushing where origin now pushes, and approve again with that address", async () => {
    const api = withItems([review()]);
    const refusal = {
      detail: "origin now pushes to https://github.com/me/new.git instead of ...",
      code: "remote_changed",
      remote_urls: ["https://github.com/me/new.git"],
      confirmed_url: "https://github.com/me/old.git",
    };
    api.approve.mockRejectedValueOnce(new ApiError(409, refusal.detail, "remote_changed", refusal));
    api.approve.mockResolvedValueOnce(session({ pr_url: "https://github.com/me/cv-page/pull/7" }));
    const { user } = await renderInbox({ api });

    await user.click(await reviewLoaded());
    const confirm = await screen.findByRole("alertdialog", { name: "Confirm the push address" });
    expect(confirm).toHaveTextContent(
      "origin now pushes to https://github.com/me/new.git instead of " +
        "https://github.com/me/old.git, the address Nest recorded.",
    );
    expect(api.session).toHaveBeenCalledWith("s1");
    expect(api.diff).toHaveBeenCalledTimes(2);
    const pushThere = within(confirm).getByRole("button", { name: "Push there" });
    await waitFor(() => {
      expect(pushThere).toBeEnabled();
    });
    await user.click(pushThere);

    expect(api.approve).toHaveBeenLastCalledWith("s1", {
      commit_message: "Validate contact form",
      ...SEEN,
      confirm_remote_url: "https://github.com/me/new.git",
    });
    expect(await screen.findByText("Pull request opened")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("ask to confirm a push address never confirmed, and let it be cancelled", async () => {
    const api = withItems([review()]);
    api.approve.mockRejectedValueOnce(
      new ApiError(409, "origin pushes to x", "remote_not_confirmed", {
        remote_urls: ["git@github.com:me/cv-page.git"],
        confirmed_url: null,
      }),
    );
    const { user } = await renderInbox({ api });

    await user.click(await reviewLoaded());
    const confirm = await screen.findByRole("alertdialog", { name: "Confirm the push address" });
    expect(confirm).toHaveTextContent(
      "origin pushes to git@github.com:me/cv-page.git. Nest pushes only to an address " +
        "you confirmed.",
    );
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.approve).toHaveBeenCalledOnce();
    await reviewLoaded();
  });

  it.each([
    [
      ["https://a.example/x.git", "https://b.example/x.git"],
      "origin pushes to more than one address",
    ],
    [[], "origin has no push address"],
  ])("say what to fix when origin has no single push address: %j", async (urls, text) => {
    const api = withItems([review()]);
    api.approve.mockRejectedValueOnce(
      new ApiError(409, "origin pushes to ...", "remote_changed", {
        remote_urls: urls,
        confirmed_url: "https://a.example/x.git",
        extra: 1,
      }),
    );
    const { user } = await renderInbox({ api });

    await user.click(await reviewLoaded());
    const confirm = await screen.findByRole("alertdialog", { name: "Confirm the push address" });

    expect(confirm).toHaveTextContent(text);
    expect(confirm).toHaveTextContent("Fix origin on your Mac, then approve again.");
    for (const url of urls) expect(confirm).toHaveTextContent(url);
    expect(within(confirm).queryByRole("button", { name: "Push there" })).toBeNull();
  });

  it("read a malformed push address refusal as no address", async () => {
    const api = withItems([review()]);
    api.approve.mockRejectedValueOnce(
      new ApiError(409, "origin pushes to ...", "remote_not_confirmed", {
        remote_urls: "nope",
        confirmed_url: 4,
      }),
    );
    const { user } = await renderInbox({ api });

    await user.click(await reviewLoaded());

    expect(
      await screen.findByRole("alertdialog", { name: "Confirm the push address" }),
    ).toHaveTextContent("origin has no push address");
  });

  it("send feedback instead", async () => {
    const api = withItems([review()]);
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Feedback" }));
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Feedback" }));
    const send = screen.getByRole("button", { name: "Send feedback" });
    expect(screen.getByLabelText("Feedback")).toHaveFocus();
    expect(send).toBeDisabled();
    await user.keyboard("   {Enter}");
    expect(api.feedback).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Feedback"), "Add a test");
    await user.click(send);

    expect(api.feedback).toHaveBeenCalledWith("s1", "Add a test");
    expect(await screen.findByText("Feedback sent")).toBeInTheDocument();
  });

  it("show the full diff with review actions", async () => {
    const api = withItems([review()]);
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "View changes" }));
    const sheet = await screen.findByRole("dialog", { name: "Validate contact form" });
    const file = await within(sheet).findByRole("region", { name: "app/globals.css" });

    expect(within(file).getByText("@@ -12,2 +12,3 @@ :root")).toBeInTheDocument();
    expect(
      within(file).getByText("--muted: #aaa;", { normalizer: (t) => t.trim() }).parentElement,
    ).toHaveClass("dl a");
    expect(
      within(file).getByText("--muted: #666;", { normalizer: (t) => t.trim() }).parentElement,
    ).toHaveClass("dl d");
    expect(within(sheet).getByText("Binary file")).toBeInTheDocument();
    const approve = within(sheet).getByRole("button", { name: "Approve and open PR" });
    await waitFor(() => {
      expect(approve).toBeEnabled();
    });
    await user.click(approve);

    // Approving from the diff publishes only the review it showed.
    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      ...SEEN,
    });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("mark a nested repository as not committed", async () => {
    const api = withItems([review()]);
    const nested = diff();
    nested.files = [
      { ...defined(nested.files[1]), path: "vendor/lib", binary: false, nested_repository: true },
      defined(nested.files[0]),
    ];
    api.diff.mockResolvedValue(nested);
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "View changes" }));
    const sheet = await screen.findByRole("dialog", { name: "Validate contact form" });
    const repo = await within(sheet).findByRole("region", { name: "vendor/lib" });
    const plain = within(sheet).getByRole("region", { name: "app/globals.css" });

    expect(within(repo).getByText("Nested repository, not committed")).toHaveClass("dnote");
    expect(within(plain).queryByText("Nested repository, not committed")).not.toBeInTheDocument();
  });

  it("ignore a diff that arrives after the sheet closed", async () => {
    const api = withItems([review()]);
    let finish: (value: ReturnType<typeof diff>) => void = () => undefined;
    api.diff.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "View changes" }));
    expect(screen.getByText("Loading changes...")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Done" }));
    finish(diff());

    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("show renames, truncation and empty or failed diffs", async () => {
    const api = withItems([review()]);
    const renamed = diff();
    renamed.files = [{ ...defined(renamed.files[0]), old_path: "old.css", truncated: true }];
    api.diff.mockResolvedValueOnce(diff());
    api.diff.mockResolvedValueOnce(renamed);
    api.diff.mockResolvedValueOnce({ ...diff(), files: [] });
    api.diff.mockRejectedValueOnce(new ApiError(404, "gone"));
    const { user } = await renderInbox({ api });
    const open = async () => {
      await user.click(screen.getByRole("button", { name: "View changes" }));
      return screen.findByRole("dialog");
    };

    let sheet = await open();
    expect(await within(sheet).findByText("old.css → app/globals.css")).toBeInTheDocument();
    expect(within(sheet).getByText("More lines on the Mac")).toBeInTheDocument();
    await user.click(within(sheet).getByRole("button", { name: "Done" }));

    sheet = await open();
    expect(await within(sheet).findByText("No changes against the base.")).toBeInTheDocument();
    await user.keyboard("{Escape}");

    sheet = await open();
    expect(await within(sheet).findByText("The changes could not be loaded.")).toBeInTheDocument();
    expect(within(sheet).getByRole("button", { name: "Approve and open PR" })).toBeDisabled();
  });
});

describe("pull request cards", () => {
  const opened = session({
    pr: prStatus(),
    pr_url: "https://github.com/me/cv-page/pull/7",
    pr_summary: "Validated the form\n2 files changed, +30 -4",
  });

  it("merge a pull request whose checks passed", async () => {
    const api = withItems([mergeApproval()], [opened]);
    const { user } = await renderInbox({ api });
    const merge = card(/Ready to merge/);

    expect(
      within(merge).getByText("Ready to merge · #7 Validate contact form"),
    ).toBeInTheDocument();
    expect(within(merge).getByText(/Validated the form/)).toBeInTheDocument();
    expect(within(merge).getByText("2 checks passed")).toBeInTheDocument();
    expect(within(merge).getByRole("link", { name: "Open on GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/me/cv-page/pull/7",
    );
    await user.click(within(merge).getByRole("button", { name: "Merge (squash)" }));

    expect(api.merge).toHaveBeenCalledWith("s1", { method: "squash", delete_branch: false });
    expect(await screen.findByText("Merged #7")).toBeInTheDocument();
    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
  });

  it("delete the branch with the merge only when asked (B102 item 30)", async () => {
    const api = withItems([mergeApproval()], [opened]);
    const { user } = await renderInbox({ api });
    const merge = card(/Ready to merge/);
    const box = within(merge).getByRole("checkbox", { name: "Also delete the branch" });

    expect(box).not.toBeChecked();
    await user.click(box);
    await user.click(within(merge).getByRole("button", { name: "Merge (squash)" }));

    expect(api.merge).toHaveBeenCalledWith("s1", { method: "squash", delete_branch: true });
  });

  it.each([
    [{ checks: { state: "none", passed: 0, failed: 0, pending: 0 } }, "No checks"],
    [{ checks: { state: "success", passed: 1, failed: 0, pending: 0 } }, "1 check passed"],
  ])("say how many checks passed: %s", async (payload, text) => {
    const item = mergeApproval();
    const api = withItems([{ ...item, payload: { ...item.payload, ...payload } }], []);
    await renderInbox({ api });

    expect(within(card(/Ready to merge/)).getByText(text)).toBeInTheDocument();
  });

  it("stay up when the merge fails", async () => {
    const api = withItems([mergeApproval()], [opened]);
    api.merge.mockRejectedValueOnce(new ApiError(502, "git merge failed: not mergeable"));
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Merge (squash)" }));

    expect(await screen.findByText("git merge failed: not mergeable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Merge (squash)" })).toBeEnabled();
  });

  it("send failed checks to the agent", async () => {
    const failing = session({
      pr: prStatus({ checks: [check("unit", "failure"), check("lint"), check("e2e", "failure")] }),
    });
    const api = withItems([], [failing]);
    const { user } = await renderInbox({ api });
    const failed = card(/Checks failed/);

    expect(within(failed).getByText("#7 Validate contact form")).toBeInTheDocument();
    expect(
      within(within(failed).getByRole("list", { name: "Failing checks" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["unit", "e2e"]);
    expect(within(failed).getByRole("link", { name: "Open on GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/me/cv-page/pull/7",
    );
    expect(screen.getByRole("tab", { name: "Needs you 1" })).toBeInTheDocument();
    await user.click(within(failed).getByRole("button", { name: "Send to agent" }));

    // The Mac reads the failing checks' logs with its own GitHub login and sends them in.
    expect(api.ciFeedback).toHaveBeenCalledWith("s1");
    expect(api.sendMessage).not.toHaveBeenCalled();
    expect(await screen.findByText("Sent to the agent with the checks' logs")).toBeInTheDocument();
  });

  it("keep the failed checks card when sending fails, and open the chat from it", async () => {
    const failing = session({ pr: prStatus({ checks: [check("unit", "failure")] }) });
    const api = withItems([], [failing]);
    api.ciFeedback.mockRejectedValueOnce(new ApiError(409, "session 's1' is closed"));
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Send to agent" }));
    expect(await screen.findByText("session 's1' is closed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send to agent" })).toBeEnabled();

    await user.click(within(card(/Checks failed/)).getByRole("button", { name: failing.title }));
    expect(await screen.findByRole("region", { name: failing.title })).toBeInTheDocument();
  });
});

describe("stuck cards", () => {
  const stuck = (details = "No new output for 12 minutes.") =>
    session({
      state: "running",
      stuck: { reason: "silent", since: "2026-10-06T09:48:00Z", details },
    });

  it("show why the chat looks stuck and nudge it with an interrupting message", async () => {
    const api = withItems([], [stuck(), session({ id: "s2", title: "Calm one" })]);
    const { user, push } = await renderInbox({ api });
    const flagged = card(/Stuck: Validate contact form/);

    expect(within(flagged).getByText("No new output for 12 minutes.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Needs you 1" })).toBeInTheDocument();
    await user.click(within(flagged).getByRole("button", { name: "Send a nudge" }));

    expect(api.sendMessage).toHaveBeenCalledWith(
      "s1",
      "You seem stuck: no new output for 12 minutes. Step back and try a different approach.",
      [],
      true,
    );
    expect(await screen.findByText("Nudge sent")).toBeInTheDocument();
    expect(within(flagged).getByRole("button", { name: "Interrupt" })).toBeDisabled();

    push({ type: "session.unstuck", session_id: "s1", payload: { reason: "silent" } });
    expect(screen.queryByRole("article", { name: /Stuck/ })).not.toBeInTheDocument();
    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
  });

  it("interrupt the chat, and stay usable when that fails", async () => {
    const api = withItems([], [stuck("Called Bash 5 times in a row with the same input")]);
    api.interrupt.mockRejectedValueOnce(new ApiError(409, "no turn in progress"));
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Interrupt" }));
    expect(await screen.findByText("no turn in progress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Interrupt" })).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Interrupt" }));
    expect(api.interrupt).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Interrupted")).toBeInTheDocument();
  });

  it("keep the card when the nudge fails, and open the chat from it", async () => {
    const api = withItems([], [stuck()]);
    api.sendMessage.mockRejectedValueOnce(new ApiError(409, "session 's1' is closed"));
    const { user } = await renderInbox({ api });

    await user.click(screen.getByRole("button", { name: "Send a nudge" }));
    expect(await screen.findByText("session 's1' is closed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send a nudge" })).toBeEnabled();

    await user.click(within(card(/Stuck/)).getByRole("button", { name: "Validate contact form" }));
    expect(
      await screen.findByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
  });

  it("appear when a chat gets stuck and ignore broken flags", async () => {
    const api = withItems([], [session({ state: "running" })]);
    const { push } = await renderInbox({ api });
    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();

    push({ type: "session.stuck", session_id: "s1", payload: { reason: "odd", since: "x" } });
    expect(screen.getByText("Nothing needs you.")).toBeInTheDocument();
    push({
      type: "session.stuck",
      session_id: "s1",
      payload: { reason: "long_turn", since: "2026-10-06T09:00:00Z" },
    });

    expect(card(/Stuck/)).toBeInTheDocument();
  });
});
