import { describe, expect, it } from "vitest";
import type { StorageUsage, StoredAttachment } from "../../../api/types.ts";
import {
  ARCHIVE_CHOICES,
  WARN_CHOICES,
  archiveLabel,
  attachmentSource,
  bytes,
  ledger,
  linuxKeys,
  movedBy,
  refreshInterval,
  segments,
  shareText,
  shares,
  stuckChoices,
  STUCK_THRESHOLDS,
  warnLevel,
} from "./words.ts";

const usage = (
  total: number,
  chats: number,
  attachments: number,
  artifacts: number,
  other: number,
): StorageUsage => ({
  total_bytes: total,
  chats_bytes: chats,
  attachments_bytes: attachments,
  artifacts_bytes: artifacts,
  other_bytes: other,
});

// Ported from NestKitTests' SettingsTests.
describe("storage words", () => {
  it("reads bytes as Finder counts them", () => {
    expect([540, 12_400, 820_000_000, 1_420_000_000].map(bytes)).toEqual([
      "540 bytes",
      "12 KB",
      "820 MB",
      "1.4 GB",
    ]);
  });

  it("shares each part of the total, none while empty", () => {
    const parts = shares(usage(1_000_000_000, 500_000_000, 250_000_000, 0, 250_000_000));
    expect(parts.map((p) => p.share)).toEqual([0.5, 0.25, 0, 0.25]);
    expect(shares(usage(0, 0, 0, 0, 0))).toEqual([]);
  });

  it("names the ledger's parts with sizes and whole percents", () => {
    expect([0, 0.0004, 0.0099, 0.01, 0.746, 1].map(shareText)).toEqual([
      "0%",
      "<1%",
      "<1%",
      "1%",
      "75%",
      "100%",
    ]);
    const lines = ledger(usage(18_900_000, 14_000_000, 1_500_000, 8_000, 3_392_000));
    expect(lines.map((l) => l.size)).toEqual(["14 MB", "2 MB", "8 KB", "3 MB"]);
    expect(lines.map((l) => l.share)).toEqual(["74%", "8%", "<1%", "18%"]);
    expect(ledger(usage(0, 0, 0, 0, 0)).map((l) => l.share)).toEqual(["0%", "0%", "0%", "0%"]);
  });

  it("keeps tiny parts visible and fills the width", () => {
    const widths = segments(
      [
        { part: "chats", share: 0.75 },
        { part: "attachments", share: 0.25 },
        { part: "artifacts", share: 0 },
        { part: "other", share: 0 },
      ],
      300,
      2,
      3,
    );
    expect(widths).toEqual([
      { part: "chats", width: 223.5 },
      { part: "attachments", width: 74.5 },
    ]);
    const tiny = segments(
      [
        { part: "chats", share: 0.999 },
        { part: "artifacts", share: 0.001 },
      ],
      102,
      2,
      3,
    );
    expect(tiny.map((s) => s.width)).toEqual([97, 3]);
    expect(segments([], 100, 2, 3)).toEqual([]);
  });

  it("words archiving and where an attachment came from", () => {
    expect(ARCHIVE_CHOICES.map(archiveLabel)).toEqual([
      "Never",
      "1 day",
      "2 days",
      "3 days",
      "7 days",
      "30 days",
      "90 days",
    ]);
    const attachment = (session_id: string | null, session_title: string | null) =>
      ({ session_id, session_title }) as StoredAttachment;
    expect(attachmentSource(attachment("s1", "Fix it"))).toBe("Fix it");
    expect(attachmentSource(attachment("s1", null))).toBe("Untitled chat");
    expect(attachmentSource(attachment(null, null))).toBe("No chat");
  });
});

describe("usage settings words", () => {
  it("offers the warning levels and refresh intervals as the Mac does", () => {
    expect(WARN_CHOICES.map(warnLevel)).toEqual(["70%", "80%", "90%", "Off"]);
    expect([null, 0, 1, 3].map(refreshInterval)).toEqual([
      "-",
      "Off",
      "Every minute",
      "Every 3 minutes",
    ]);
  });

  it("moves a top bar account by one, not past either end", () => {
    expect(movedBy(["a", "b", "c"], "b", -1)).toEqual(["b", "a", "c"]);
    expect(movedBy(["a", "b", "c"], "b", 1)).toEqual(["a", "c", "b"]);
    expect(movedBy(["a", "b", "c"], "a", -1)).toEqual(["a", "b", "c"]);
  });
});

describe("feature keys", () => {
  it("names the Mac's modifier symbols as Linux keys", () => {
    expect(linuxKeys("⌘K")).toBe("Ctrl+K");
    expect(linuxKeys("⌘1 to ⌘9")).toBe("Ctrl+1 to Ctrl+9");
    expect(linuxKeys("⇧⌥⌘T")).toBe("Ctrl+Alt+Shift+T");
    expect(linuxKeys("Project menu")).toBe("Project menu");
  });
});

describe("other words", () => {
  it("keeps a stuck threshold set elsewhere among the choices", () => {
    const [waiting] = STUCK_THRESHOLDS;
    if (waiting === undefined) throw new Error("no thresholds");
    expect(stuckChoices(waiting, 15)).toEqual(waiting.base);
    expect(stuckChoices(waiting, 25)).toEqual([0, 5, 10, 15, 20, 25, 30, 45, 60]);
  });
});
