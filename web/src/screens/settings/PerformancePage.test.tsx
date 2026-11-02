import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import { fakeApi } from "../../test/fakeApi.ts";
import { NOW, perfMetric, perfNeverRun, perfSection, perfView } from "../../test/fixtures.ts";
import { openSettings } from "../../test/settings.ts";

const openPerformance = (api = fakeApi()) => openSettings("Performance", { api });
const section = (title: string) => screen.getByRole("region", { name: title });
const button = (name: string) => screen.getByRole("button", { name });
// A metric's two bars, previous then this run, as their widths.
const bars = (name: string) =>
  [...screen.getByRole("img", { name }).children].map((i) => (i as HTMLElement).style.width);

describe("performance", () => {
  it("shows the last run, the top numbers, each section's rows and what changed", async () => {
    await openPerformance();

    expect(await screen.findByText(/^Last run .* · 1 min 42 s$/)).toBeInTheDocument();
    expect(window.location.pathname).toBe("/settings/performance");
    expect(screen.getByText("39.7k", { selector: ".pf-big" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "System prompt 23k, Tools 5.2k, Nest tools 6.2k" }));
    const load = section("Load speed");
    const row = within(load).getByText("Biggest chat").closest(".pf-m");
    expect(row).toHaveTextContent("1.8 s");
    expect(within(row as HTMLElement).getByText("▼ 25%")).toHaveClass("pf-better");
    expect(within(load).getByText("▲ 20%")).toHaveClass("pf-worse");
    expect(within(section("Activity")).getByText("▲ 18%")).toHaveClass("pf-same");
    expect(within(section("Context cost")).getByText("Spends usage")).toBeInTheDocument();
    expect(within(section("What changed")).getByText(/new MCP server linear/)).toBeInTheDocument();
  });

  it("scales the bars against the section's largest value of the same unit", async () => {
    const api = fakeApi();
    api.perf.mockResolvedValue(
      perfView({
        sections: [
          perfSection({
            metrics: [
              perfMetric({ id: "a", value: 1000, previous: 4000, text: "1 s" }),
              perfMetric({
                id: "b",
                value: 2000,
                previous: null,
                previous_text: null,
                text: "2 s",
              }),
              // Another unit is scaled on its own.
              perfMetric({ id: "c", unit: "bytes", value: 50, previous: 100, text: "50 B" }),
              // A share is drawn against the whole, even when it is the only one.
              perfMetric({
                id: "d",
                unit: "percent",
                value: 13,
                previous: null,
                previous_text: null,
                text: "13%",
              }),
            ],
          }),
        ],
      }),
    );
    await openPerformance(api);

    expect(await screen.findByRole("img", { name: "Previous run 2.4 s, This run 1 s" }));
    expect(bars("Previous run 2.4 s, This run 1 s")).toEqual(["100%", "25%"]);
    expect(bars("This run 2 s")).toEqual(["50%"]);
    expect(bars("Previous run 2.4 s, This run 50 B")).toEqual(["100%", "50%"]);
    expect(bars("This run 13%")).toEqual(["13%"]);
  });

  it("before any run says so and still offers Run all", async () => {
    const api = fakeApi();
    api.perf.mockResolvedValue(perfNeverRun());
    await openPerformance(api);

    expect(await screen.findByText("Never run")).toBeInTheDocument();
    expect(within(section("Load speed")).getByText("Not run yet")).toBeInTheDocument();
    expect(button("Run all")).toBeEnabled();
    expect(button("Clear old runs")).toBeDisabled();
    expect(screen.queryByText("Previous run")).not.toBeInTheDocument();
  });

  it("while running, disables the buttons and marks the sections being run", async () => {
    const api = fakeApi();
    api.perf.mockResolvedValue(
      perfView({ running: { id: "r1", sections: ["load"], started_at: NOW } }),
    );
    await openPerformance(api);

    expect(await screen.findByText("Running...")).toBeInTheDocument();
    expect(button("Run all")).toBeDisabled();
    expect(button("Clear old runs")).toBeDisabled();
    expect(within(section("Load speed")).getByText("Running")).toBeInTheDocument();
    expect(within(section("Load speed")).queryByRole("button")).not.toBeInTheDocument();
    expect(button("Run Context cost")).toBeDisabled();
  });

  it("shows a section's error in that section", async () => {
    const api = fakeApi();
    api.perf.mockResolvedValue(
      perfView({ sections: [perfSection({ error: "Claude is not signed in", metrics: [] })] }),
    );
    await openPerformance(api);

    const load = await screen.findByRole("region", { name: "Load speed" });
    expect(within(load).getByText("Claude is not signed in")).toHaveClass("pf-err");
    expect(within(load).queryByText("Not run yet")).not.toBeInTheDocument();
  });

  it("runs one section and shows what the Mac answers", async () => {
    const api = fakeApi();
    api.runPerf.mockResolvedValue(
      perfView({ running: { id: "r1", sections: ["load"], started_at: NOW } }),
    );
    const { user } = await openPerformance(api);

    await user.click(await screen.findByRole("button", { name: "Run Load speed" }));

    expect(api.runPerf).toHaveBeenCalledWith(["load"]);
    expect(await screen.findByText("Running...")).toBeInTheDocument();
    expect(within(section("Load speed")).getByText("Running")).toBeInTheDocument();
  });

  it("asks for every section with Run all, and keeps two runs with Clear", async () => {
    const api = fakeApi();
    const { user } = await openPerformance(api);

    await user.click(await screen.findByRole("button", { name: "Run all" }));
    expect(api.runPerf).toHaveBeenCalledWith([]);
    await waitFor(() => {
      expect(button("Clear old runs")).toBeEnabled();
    });
    api.clearPerf.mockResolvedValue(perfView({ runs: 2, changes: [] }));
    await user.click(button("Clear old runs"));

    expect(api.clearPerf).toHaveBeenCalled();
    await waitFor(() => {
      expect(screen.queryByRole("region", { name: "What changed" })).not.toBeInTheDocument();
    });
  });

  it("reloads when a run starts or ends, here or on the Mac", async () => {
    const api = fakeApi();
    const { push } = await openPerformance(api);
    await screen.findByText(/^Last run/);

    api.perf.mockResolvedValue(
      perfView({ running: { id: "r1", sections: ["context"], started_at: NOW } }),
    );
    push({ id: null, type: "perf.run", payload: { state: "running" } });

    expect(await screen.findByText("Running...")).toBeInTheDocument();
    expect(within(section("Context cost")).getByText("Running")).toBeInTheDocument();
  });

  it("shows what is true now when a run is refused", async () => {
    const api = fakeApi();
    api.runPerf.mockRejectedValue(new ApiError(409, "A run is already running"));
    const { user } = await openPerformance(api);
    await screen.findByText(/^Last run/);
    api.perf.mockResolvedValue(perfView({ running: { id: "r1", sections: [], started_at: NOW } }));

    await user.click(button("Run all"));

    expect(await screen.findByText("A run is already running")).toBeInTheDocument();
    expect(await screen.findByText("Running...")).toBeInTheDocument();
  });

  it("keeps Advanced closed on every open, without a Run button for the Mac's section", async () => {
    const { user } = await openPerformance();

    const advanced = await screen.findByRole("button", { name: "Advanced" });
    expect(advanced).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "Daemon" })).not.toBeInTheDocument();
    await user.click(advanced);

    expect(within(section("Daemon")).getByRole("button", { name: "Run Daemon" }));
    expect(within(section("Mac app")).queryByRole("button")).not.toBeInTheDocument();
    await user.click(button("Back to Settings"));
    await user.click(await screen.findByRole("button", { name: "Performance" }));

    expect(await screen.findByRole("button", { name: "Advanced" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});
