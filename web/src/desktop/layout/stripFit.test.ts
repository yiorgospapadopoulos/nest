// Regression (VM, 2026-11-03): with four tabs and the pill's gap in a 1280 px window the
// strip overflowed, cutting search and pushing the window buttons out of view. As the
// Mac's TabStrip, the right cluster always shows and the tabs shrink to make room.
import { describe, expect, it } from "vitest";
import { CURRENT_MIN, stripFit, TAB_MAX, TAB_MIN } from "./stripFit.ts";

// The VM's strip: the Pixies tab and its divider, the +, the usage chip, search and the
// window buttons.
const lead = 140;
const trail = 520;

describe("the tab strip's fit", () => {
  it("keeps tabs at full width while they fit", () => {
    expect(stripFit({ width: 1600, gap: null, tabs: 3, lead, trail })).toEqual({
      tabWidth: TAB_MAX,
      currentWidth: TAB_MAX,
      keepsGap: false,
      overflows: false,
    });
  });

  it("shrinks the tabs, all to one width, before the right cluster gives way", () => {
    const fit = stripFit({ width: 1280, gap: null, tabs: 4, lead, trail });
    expect(fit.overflows).toBe(false);
    expect(fit.tabWidth).toBeLessThan(TAB_MAX);
    // The tabs, their spacing and the right cluster fit the window.
    expect(lead + 4 * fit.tabWidth + 3 * 2 + 12 + trail).toBeLessThanOrEqual(1280);
  });

  it("keeps the pill's gap only while the tabs fit left of it at the Mac's width", () => {
    // The VM: a 1280 window at x=66 on a 1920 screen, the 272 wide pill at 824 to 1096.
    const gap = { left: 750, width: 288, right: 242 };
    // Right of the gap there is no room for the right cluster: the pill covers the strip.
    expect(stripFit({ width: 1280, gap, tabs: 4, lead, trail })).toMatchObject({
      keepsGap: false,
      overflows: false,
    });
    // With room on both sides at the tabs' own width, the gap stays.
    const wide = { left: 900, width: 288, right: 600 };
    const kept = stripFit({ width: 1788, gap: wide, tabs: 4, lead, trail });
    expect(kept).toMatchObject({ keepsGap: true, tabWidth: TAB_MAX });
    expect(lead + 4 * kept.tabWidth + 3 * 2).toBeLessThanOrEqual(900);
    // Keeping it would make the tabs narrower than the Mac's: the gap goes.
    const narrower = stripFit({ width: 1788, gap: wide, tabs: 6, lead, trail });
    expect(narrower.keepsGap).toBe(false);
    expect(narrower.tabWidth).toBeGreaterThan((900 - lead) / 6);
  });

  it("gives the tabs the Mac's width at the smallest window, the pill's gap or not", () => {
    // Wave 7: at 1000 by 640 the gap left the current tab only its icon, count and close.
    const gap = { left: 360, width: 280, right: 360 };
    const small = { width: 1000, tabs: 3, lead, trail: 300 };
    const mac = stripFit({ ...small, gap: null });
    expect(stripFit({ ...small, gap })).toEqual({ ...mac, keepsGap: false });
    expect(mac.tabWidth).toBeGreaterThan(150);
  });

  it("stops at the smallest width and lets the tabs scroll", () => {
    expect(stripFit({ width: 900, gap: null, tabs: 8, lead, trail })).toEqual({
      tabWidth: TAB_MIN,
      currentWidth: CURRENT_MIN,
      keepsGap: false,
      overflows: true,
    });
  });

  // Regression (production check, 2026-11-03): with twelve tabs the current one showed only
  // its icon and close button.
  it("keeps the current tab wide enough for its name while the others shrink", () => {
    const fit = stripFit({ width: 1280, gap: null, tabs: 6, lead, trail });
    expect(fit.currentWidth).toBe(CURRENT_MIN);
    expect(fit.tabWidth).toBeLessThan(CURRENT_MIN);
    expect(fit.overflows).toBe(false);
    expect(lead + fit.currentWidth + 5 * fit.tabWidth + 5 * 2 + 12 + trail).toBeLessThanOrEqual(
      1280,
    );
    const many = stripFit({ width: 1280, gap: null, tabs: 13, lead, trail });
    expect(many).toMatchObject({ currentWidth: CURRENT_MIN, tabWidth: TAB_MIN, overflows: true });
  });
});
