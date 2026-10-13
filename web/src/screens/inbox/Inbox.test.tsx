import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Approval } from "../../api/types.ts";
import { defined } from "../../test/defined.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import {
  approval,
  check,
  detail,
  diff,
  mergeApproval,
  pixie,
  prStatus,
  question,
  repo,
  review,
  session,
} from "../../test/fixtures.ts";
import { renderApp } from "../../test/render.tsx";

function withItems(items: Approval[], sessions = [session()]) {
  const api = fakeApi();
  api.repos.mockResolvedValue([repo("narwhal"), repo("todo-ui")]);
  api.sessions.mockImplementation((archived) => Promise.resolve(archived ? [] : sessions));
  api.approvals.mockResolvedValue(items);
  api.resolveApproval.mockImplementation((id) =>
    Promise.resolve({ ...defined(items.find((a) => a.id === id)), status: "resolved" }),
  );
  return api;
}

const card = (name: RegExp) => screen.getByRole("article", { name });

function swipe(element: HTMLElement, dx: number, dy = 0) {
  fireEvent.pointerDown(element, { button: 0, clientX: 200, clientY: 100 });
  fireEvent.pointerMove(element, { clientX: 203, clientY: 101 });
  fireEvent.pointerMove(element, { clientX: 200 + dx, clientY: 100 + dy });
  fireEvent.pointerUp(element);
}

describe("Inbox", () => {
  it("groups pending items by project with counts", async () => {
    const api = withItems([
      approval(),
      question({ repo: "narwhal", session_id: "n1", title: "Parser" }),
    ]);
    await renderApp({ api });

    const groups = screen.getAllByRole("heading", { level: 2 });
    expect(groups.map((h) => h.textContent)).toEqual(["Nnarwhal1", "TUtodo-ui1"]);
    expect(screen.getByLabelText("2 need you")).toBeInTheDocument();
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
    const { user } = await renderApp({ api });

    const groups = screen.getAllByRole("heading", { level: 2 });
    expect(groups.map((h) => h.textContent)).toEqual(["Pixie1", "Tester1"]);
    expect(screen.queryByText("pixie:p1")).not.toBeInTheDocument();
    expect(screen.getByRole("img", { name: "invader" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open Pixie" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open Tester" }));
    expect(screen.getByRole("tab", { name: "Chat", selected: true })).toBeInTheDocument();
  });

  it("approves, rejects and always allows permissions with buttons", async () => {
    const api = withItems([approval(), approval({ id: "q8" }), approval({ id: "q9" })]);
    const { user } = await renderApp({ api });
    const [first, second, third] = screen.getAllByRole("article");

    await user.click(within(defined(first)).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Approved: npm install zod")).toBeInTheDocument();
    await user.click(within(defined(second)).getByRole("button", { name: "Reject" }));
    await user.click(within(defined(third)).getByRole("button", { name: "Always allow" }));

    expect(api.resolveApproval.mock.calls).toEqual([
      ["q1", { behavior: "allow", always: false }],
      ["q8", { behavior: "deny", always: false }],
      ["q9", { behavior: "allow", always: true }],
    ]);
    await waitFor(() => {
      expect(screen.getByText("All clear")).toBeInTheDocument();
    });
    expect(screen.getByText("Always allowed: Bash")).toBeInTheDocument();
  });

  it("shows why Claude Code asks, when it says", async () => {
    const why = "Path is outside the allowed working directories";
    const api = withItems([
      approval({
        payload: { tool: "Bash", input: { command: "ls /etc" }, title: null, reason: why },
      }),
      approval({ id: "q8", payload: { tool: "Bash", input: { command: "ls" }, reason: null } }),
    ]);
    await renderApp({ api });
    const [first, second] = screen.getAllByRole("article");

    expect(within(defined(first)).getByText(why)).toBeInTheDocument();
    expect(defined(second).querySelectorAll(".why")).toHaveLength(0);
  });

  it("keeps the card usable when resolving fails", async () => {
    const api = withItems([approval()]);
    api.resolveApproval.mockRejectedValueOnce(new ApiError(409, "approval q1 is expired"));
    const { user } = await renderApp({ api });

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText("approval q1 is expired")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("swipes right to approve and left to reject", async () => {
    const api = withItems([approval(), approval({ id: "q8" })]);
    await renderApp({ api });

    const [top] = screen.getAllByRole("article");
    swipe(defined(top), 40);
    swipe(defined(top), 0, 120);
    expect(api.resolveApproval).not.toHaveBeenCalled();

    const [first] = screen.getAllByRole("article");
    swipe(defined(first), 140);
    await waitFor(() => {
      expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    swipe(card(/Permission/), -140);

    await waitFor(() => {
      expect(api.resolveApproval.mock.calls).toEqual([
        ["q1", { behavior: "allow", always: false }],
        ["q8", { behavior: "deny", always: false }],
      ]);
    });
  });

  it("shows swipe hints while dragging and ignores gestures from buttons", () => {
    return (async () => {
      const api = withItems([approval()]);
      await renderApp({ api });
      const article = card(/Permission/);
      const wrapper = defined(article.parentElement);

      fireEvent.pointerDown(article, { button: 0, clientX: 100, clientY: 100 });
      fireEvent.pointerMove(article, { clientX: 140, clientY: 100 });
      expect(wrapper).toHaveClass("r");
      expect(article).toHaveClass("drag");
      fireEvent.pointerMove(article, { clientX: 60, clientY: 100 });
      expect(wrapper).toHaveClass("l");
      fireEvent.pointerCancel(article);
      expect(wrapper).not.toHaveClass("l");

      fireEvent.pointerDown(article, { button: 2, clientX: 100, clientY: 100 });
      fireEvent.pointerMove(article, { clientX: 300, clientY: 100 });
      fireEvent.pointerDown(screen.getByRole("button", { name: "Reject" }), { button: 0 });
      fireEvent.pointerMove(article, { clientX: 300, clientY: 100 });
      fireEvent.pointerUp(article);
      expect(api.resolveApproval).not.toHaveBeenCalled();
    })();
  });

  it("opens the chat from the card", async () => {
    const api = withItems([approval()]);
    const { user } = await renderApp({ api });

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
    await renderApp({ api: withItems([approval()], [session(), failing, stuck]) });

    expect(screen.getAllByRole("article").map((a) => a.getAttribute("aria-label"))).toEqual([
      "Permission: Validate contact form",
      "Checks failed: Failing checks",
      "Stuck: Stuck one",
    ]);
    expect(screen.getByLabelText("3 need you")).toBeInTheDocument();
  });

  it("falls back to the approval's title when the session is unknown", async () => {
    await renderApp({ api: withItems([approval({ title: "Gone" })], []) });

    expect(screen.getByRole("button", { name: "Gone" })).toBeInTheDocument();
  });
});

describe("question cards", () => {
  it("preselect the recommended option and send the choice", async () => {
    const api = withItems([question()]);
    const { user } = await renderApp({ api });

    expect(screen.getByRole("radio", { name: /DAG/ })).toHaveAttribute("aria-checked", "true");
    await user.click(screen.getByRole("radio", { name: /Tree/ }));
    expect(screen.getByRole("radio", { name: /DAG/ })).toHaveAttribute("aria-checked", "false");
    await user.click(screen.getByRole("button", { name: "Send answer" }));

    expect(api.resolveApproval).toHaveBeenCalledWith("q2", { answers: { "DAG or tree?": "Tree" } });
    expect(await screen.findByText("Answer sent")).toBeInTheDocument();
  });

  it("send typed text instead of a choice", async () => {
    const api = withItems([question()]);
    const { user } = await renderApp({ api });

    await user.type(screen.getByLabelText("Your own answer"), "  Both  {Enter}");

    expect(api.resolveApproval).toHaveBeenCalledWith("q2", { answers: { "DAG or tree?": "Both" } });
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
    const { user } = await renderApp({ api });
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
    const { user } = await renderApp({ api });
    const message = screen.getByLabelText("Commit message");

    expect(message).toHaveValue("Validate contact form");
    expect(screen.getByText("Raised contrast")).toBeInTheDocument();
    await user.clear(message);
    await user.type(message, "Polish dark mode");
    await user.click(screen.getByRole("button", { name: "Approve and open PR" }));

    expect(api.approve).toHaveBeenCalledWith("s1", { commit_message: "Polish dark mode" });
    expect(await screen.findByText("Pull request opened")).toBeInTheDocument();
    expect(screen.getByText("All clear")).toBeInTheDocument();
  });

  it("push in-place work with only its changed files, falling back to the title", async () => {
    const api = withItems(
      [review({ payload: { paths: ["a.ts"] } })],
      [session({ mode: "in_place" })],
    );
    const { user } = await renderApp({ api });

    await user.clear(screen.getByLabelText("Commit message"));
    await user.click(screen.getByRole("button", { name: "Approve and push" }));

    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      files: ["a.ts"],
      open_pr: false,
    });
    expect(await screen.findByText("Approved and committed")).toBeInTheDocument();
  });

  it("stay up for review when approving or sending feedback fails", async () => {
    const api = withItems([review()]);
    api.approve.mockRejectedValueOnce(new ApiError(409, "the agent changed git refs itself"));
    api.feedback.mockRejectedValueOnce(new ApiError(409, "session is working"));
    const { user } = await renderApp({ api });

    await user.click(screen.getByRole("button", { name: "Approve and open PR" }));
    expect(await screen.findByText("the agent changed git refs itself")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Feedback" }));
    await user.type(screen.getByLabelText("Feedback"), "More{Enter}");

    expect(await screen.findByText("session is working")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send feedback" })).toBeEnabled();
  });

  it("swipe to approve or reject", async () => {
    const api = withItems([review(), review({ id: "q4", session_id: "s2" })]);
    const { user } = await renderApp({ api });

    const [first, second] = screen.getAllByRole("article");
    swipe(defined(second), -150);
    const confirm = await screen.findByRole("alertdialog", { name: "Reject this work?" });
    expect(api.reject).not.toHaveBeenCalled();
    await user.click(within(confirm).getByRole("button", { name: "Reject" }));
    swipe(defined(first), 150);

    await waitFor(() => {
      expect(api.reject).toHaveBeenCalledWith("s2");
    });
    expect(api.approve).toHaveBeenCalledWith("s1", { commit_message: "Validate contact form" });
    expect(await screen.findByText("All clear")).toBeInTheDocument();
  });

  it("name what a swipe to approve does", async () => {
    const hint = (article: HTMLElement) => {
      fireEvent.pointerDown(article, { button: 0, clientX: 100, clientY: 10 });
      fireEvent.pointerMove(article, { clientX: 140, clientY: 10 });
      const text = article.parentElement?.querySelector(".swbg .sl")?.textContent;
      fireEvent.pointerCancel(article);
      return text;
    };
    await renderApp({
      api: withItems(
        [review(), review({ id: "q4", session_id: "s2" })],
        [session(), session({ id: "s2", mode: "in_place", worktree_path: null })],
      ),
    });

    const [worktree, inPlace] = screen.getAllByRole("article");
    expect(hint(defined(worktree))).toBe("Approve and open PR");
    expect(hint(defined(inPlace))).toBe("Approve and push");
  });

  it("reject the work after confirming", async () => {
    const api = withItems([review()]);
    api.reject.mockRejectedValueOnce(new ApiError(502, "push failed"));
    const { user } = await renderApp({ api });
    const reject = async () => {
      await user.click(screen.getByRole("button", { name: "Reject" }));
      const confirm = await screen.findByRole("alertdialog", { name: "Reject this work?" });
      expect(confirm).toHaveTextContent(
        "The chat closes and its worktree and branch are removed. Nothing is merged.",
      );
      return confirm;
    };

    await user.click(within(await reject()).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(api.reject).not.toHaveBeenCalled();
    await user.click(within(await reject()).getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("push failed")).toBeInTheDocument();
    await user.click(within(await reject()).getByRole("button", { name: "Reject" }));

    expect(await screen.findByText("Rejected. Nothing merged")).toBeInTheDocument();
  });

  it("say that rejecting in-place work leaves its changes in the folder", async () => {
    const api = withItems([review()], [session({ mode: "in_place", worktree_path: null })]);
    const { user } = await renderApp({ api });

    await user.click(screen.getByRole("button", { name: "Reject" }));

    expect(await screen.findByRole("alertdialog")).toHaveTextContent(
      "The chat closes. Its changes stay in your folder.",
    );
  });

  it("need the agent's own git changes checked before publishing", async () => {
    const api = withItems([review()], [session({ git_violation: true })]);
    api.session.mockResolvedValue(detail({ git_violation: true }));
    const { user } = await renderApp({ api });
    const approve = screen.getByRole("button", { name: "Approve and open PR" });

    expect(
      screen.getByText(
        "The agent ran git itself and changed this chat's branch. Check its commits before publishing.",
      ),
    ).toBeInTheDocument();
    expect(approve).toBeDisabled();
    // A swipe does not publish it either: it opens the chat instead.
    swipe(card(/Ready for review/), 150);
    expect(
      await screen.findByRole("region", { name: "Validate contact form" }),
    ).toBeInTheDocument();
    expect(api.approve).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Back to todo-ui" }));

    await user.click(screen.getByRole("switch", { name: "I checked, publish anyway" }));
    await user.click(screen.getByRole("button", { name: "Approve and open PR" }));

    expect(api.approve).toHaveBeenCalledWith("s1", {
      commit_message: "Validate contact form",
      acknowledge_violation: true,
    });
  });

  it("send feedback instead", async () => {
    const api = withItems([review()]);
    const { user } = await renderApp({ api });

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
    const { user } = await renderApp({ api });

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
    await user.click(within(sheet).getByRole("button", { name: "Approve and open PR" }));

    expect(api.approve).toHaveBeenCalledWith("s1", { commit_message: "Validate contact form" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("ignore a diff that arrives after the sheet closed", async () => {
    const api = withItems([review()]);
    let finish: (value: ReturnType<typeof diff>) => void = () => undefined;
    api.diff.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { user } = await renderApp({ api });

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
    api.diff.mockResolvedValueOnce(renamed);
    api.diff.mockResolvedValueOnce({ ...diff(), files: [] });
    api.diff.mockRejectedValueOnce(new ApiError(404, "gone"));
    const { user } = await renderApp({ api });
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
    await user.click(within(sheet).getByRole("button", { name: "Reject" }));
    const confirm = await screen.findByRole("alertdialog", { name: "Reject this work?" });
    await user.click(within(confirm).getByRole("button", { name: "Reject" }));
    expect(api.reject).toHaveBeenCalledWith("s1");
  });
});

describe("pull request cards", () => {
  const opened = session({
    pr: prStatus(),
    pr_url: "https://github.com/me/todo-ui/pull/7",
    pr_summary: "Validated the form\n2 files changed, +30 -4",
  });

  it("merge a pull request whose checks passed", async () => {
    const api = withItems([mergeApproval()], [opened]);
    const { user } = await renderApp({ api });
    const merge = card(/Ready to merge/);

    expect(within(merge).getByText("#7 Validate contact form")).toBeInTheDocument();
    expect(within(merge).getByText(/Validated the form/)).toBeInTheDocument();
    expect(within(merge).getByText("2 checks passed")).toBeInTheDocument();
    expect(within(merge).getByRole("link", { name: "Open on GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/me/todo-ui/pull/7",
    );
    await user.click(within(merge).getByRole("button", { name: "Merge (squash)" }));

    expect(api.merge).toHaveBeenCalledWith("s1", { method: "squash" });
    expect(await screen.findByText("Merged #7")).toBeInTheDocument();
    expect(screen.getByText("All clear")).toBeInTheDocument();
  });

  it.each([
    [{ checks: { state: "none", passed: 0, failed: 0, pending: 0 } }, "No checks"],
    [{ checks: { state: "success", passed: 1, failed: 0, pending: 0 } }, "1 check passed"],
  ])("say how many checks passed: %s", async (payload, text) => {
    const item = mergeApproval();
    const api = withItems([{ ...item, payload: { ...item.payload, ...payload } }], []);
    await renderApp({ api });

    expect(within(card(/Ready to merge/)).getByText(text)).toBeInTheDocument();
  });

  it("stay up when the merge fails", async () => {
    const api = withItems([mergeApproval()], [opened]);
    api.merge.mockRejectedValueOnce(new ApiError(502, "git merge failed: not mergeable"));
    const { user } = await renderApp({ api });

    await user.click(screen.getByRole("button", { name: "Merge (squash)" }));

    expect(await screen.findByText("git merge failed: not mergeable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Merge (squash)" })).toBeEnabled();
  });

  it("send failed checks to the agent", async () => {
    const failing = session({
      pr: prStatus({ checks: [check("unit", "failure"), check("lint"), check("e2e", "failure")] }),
    });
    const api = withItems([], [failing]);
    const { user } = await renderApp({ api });
    const failed = card(/Checks failed/);

    expect(within(failed).getByText("#7 Validate contact form")).toBeInTheDocument();
    expect(
      within(within(failed).getByRole("list", { name: "Failing checks" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["unit", "e2e"]);
    expect(within(failed).getByRole("link", { name: "Open on GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/me/todo-ui/pull/7",
    );
    expect(screen.getByLabelText("1 need you")).toBeInTheDocument();
    await user.click(within(failed).getByRole("button", { name: "Send to agent" }));

    expect(api.sendMessage).toHaveBeenCalledWith(
      "s1",
      "CI failed: unit, e2e. Please fix. You can't use gh or reach GitHub from here, so work " +
        "from the code and the check names, and ask me for the logs if you need them.",
      [],
    );
    expect(await screen.findByText("Sent to the agent")).toBeInTheDocument();
  });

  it("keep the failed checks card when sending fails, and open the chat from it", async () => {
    const failing = session({ pr: prStatus({ checks: [check("unit", "failure")] }) });
    const api = withItems([], [failing]);
    api.sendMessage.mockRejectedValueOnce(new ApiError(409, "session 's1' is closed"));
    const { user } = await renderApp({ api });

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
    const { user, push } = await renderApp({ api });
    const flagged = card(/Stuck: Validate contact form/);

    expect(within(flagged).getByText("No new output for 12 minutes.")).toBeInTheDocument();
    expect(screen.getByLabelText("1 need you")).toBeInTheDocument();
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
    expect(screen.getByText("All clear")).toBeInTheDocument();
  });

  it("interrupt the chat, and stay usable when that fails", async () => {
    const api = withItems([], [stuck("Called Bash 5 times in a row with the same input")]);
    api.interrupt.mockRejectedValueOnce(new ApiError(409, "no turn in progress"));
    const { user } = await renderApp({ api });

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
    const { user } = await renderApp({ api });

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
    const { push } = await renderApp({ api });
    expect(screen.getByText("All clear")).toBeInTheDocument();

    push({ type: "session.stuck", session_id: "s1", payload: { reason: "odd", since: "x" } });
    expect(screen.getByText("All clear")).toBeInTheDocument();
    push({
      type: "session.stuck",
      session_id: "s1",
      payload: { reason: "long_turn", since: "2026-10-06T09:00:00Z" },
    });

    expect(card(/Stuck/)).toBeInTheDocument();
  });
});
