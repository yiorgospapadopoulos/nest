# Nest's design guide for artifacts

Read this once before you make an html page, a design or a design system. It applies to
everything the user opens in Nest's reader, on a Mac window or on an iPhone held upright.
The reader shows your page in a sandbox; the rules in the content field of
create_artifact (allowed hosts, links, no fetch or storage) still hold.

The goal is a page the user understands at a glance and trusts: calm, legible, with one
clear idea per screen. Decoration that does not help someone read or decide is noise.

## Before you start

- Say in one sentence what the page is for and who reads it. Design for that.
- Pick the kind that fits: a document for a long read, slides for a talk, a design for
  mockups, a design system for tokens and components, html when the reader must interact.
- Use real content from the task: real names, real numbers, real labels; never lorem
  ipsum text. If data is missing, say so on the page instead of inventing it.
- Keep the first view useful: the answer or the main chart first, details below.

## Layout and spacing

- Use a spacing scale and stick to it: 4, 8, 12, 16, 24, 32, 48. Mixing 13 px here and
  17 px there reads as careless even when nobody can say why.
- Group related things by putting them closer together than unrelated things. Space does
  more than borders or boxes; reach for a line only when space is not enough.
- One column of text should be 60 to 75 characters wide. Cap long text at about 720 px
  and centre it; let tables and charts be wider when they need it.
- Align to a few edges. A page where every element has its own left edge feels busy.
- Use cards sparingly. A list of rows with clear spacing is often easier to scan than a
  grid of boxes.
- Give the page a gutter of at least 16 px on each side so text never touches the edge.
- Make hit targets at least 44 by 44 px for anything the user taps.

## Type

- Use the system font stack (-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif)
  unless the content calls for something else; it is fast and looks native.
- Use a short type scale with clear steps, for example 13, 15, 17, 22, 28 and 36 px.
  Three or four sizes on a page is plenty.
- Body text at 15 to 17 px with a line height of 1.5 to 1.6. Headings tighter, about 1.2.
- Make hierarchy with size and weight, not with colour alone. Two weights (regular and
  semibold) are usually enough.
- Use tabular numbers (font-variant-numeric: tabular-nums) in tables and counters so
  digits line up.
- Keep line length and paragraph length short on a phone; break long paragraphs.
- Monospace only for code, paths and identifiers.

## Colour

- Define every colour once, as a CSS variable on :root, and use the variables everywhere.
  Then add a dark block:

  ```css
  :root { --bg: #f6f6f4; --text: #1a1b20; --muted: #5c5f66; --accent: #2f5bd3; }
  @media (prefers-color-scheme: dark) {
    :root { --bg: #111113; --text: #f2f3f7; --muted: #a3a6ad; --accent: #7b9bff; }
  }
  body { background: var(--bg); color: var(--text); }
  ```

- Always set the body background explicitly; never rely on the frame's default.
- Start from neutrals and add one accent colour for the thing that matters most. A second
  accent only if it means something different (for example good and bad).
- Check contrast: body text at least 4.5 to 1 against its background, large text and
  icons at least 3 to 1. Muted text is the usual failure; test it in both themes.
- In dark mode, do not just invert. Use a near-black background, slightly lighter
  surfaces for raised areas, and soften saturated colours so they do not glow.
- Never carry meaning by colour alone: add a label, an icon or a pattern as well.

## Motion

- Motion should explain a change: where something came from, where it went, what is now
  selected. If it explains nothing, leave it out.
- Keep it short: 150 to 250 ms for most transitions, ease-out for things arriving.
- Animate opacity and transform only; they stay smooth on a phone.
- Respect the user's setting. Wrap motion so it turns off when asked:

  ```css
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }
  ```

- No looping animations around content the user is trying to read.

## Charts

Choose the chart by the question it answers:

- How does a value change over time? A line chart (or columns for a few periods).
- How do categories compare? A horizontal bar chart, sorted by value, labels on the left.
- What is the share of a whole? A stacked bar, or a pie only with two to four slices.
- How are values spread? A histogram or a box plot.
- Do two measures move together? A scatter plot.
- One number that matters? Show the number large, with its change and period, no chart.

Make every chart readable on its own:

- A title that states the finding ("Build time fell 40% after caching"), not just the
  measure.
- Axis labels with units (ms, MB, %, requests per minute). Start bar axes at zero.
- Label lines and bars directly where you can, instead of a legend far away.
- Light grid lines or none; no heavy borders, shadows or gradients.
- No 3D charts, ever: depth distorts the values.
- Use a colour-blind safe palette, such as blue #3b6fd8, orange #e08a1e, teal #1b9e8f,
  purple #8a5cc7, red #d1495b and grey #8a8d93, and keep the order stable across charts.
- Canvas charts (Chart.js and similar) cannot read var() strings. Read the real colours
  first with getComputedStyle(document.documentElement).getPropertyValue("--accent")
  and pass those, and redraw when the colour scheme changes.
- Give tables of numbers right-aligned columns and the same decimals in each column.

## When interactivity earns its place

Interactivity is worth it when the user needs to explore: filter a long list, switch a
chart between measures, compare two options side by side, try an input and see the
result. It is not worth it for content that reads fine as a static document; then choose
a document or slides.

- Make the default state useful before anyone touches anything.
- Keep controls near what they change, and show the current state clearly.
- Everything works with touch: no hover-only information.
- A 3D scene (three.js) earns its place only when the third dimension is the content: a
  model, a spatial layout, a physical part. Give it a sensible starting camera, let the
  user orbit and zoom, keep the frame rate smooth on a phone, and offer a flat view or a
  short text summary alongside.

## Phone width

Many users open artifacts on an iPhone, about 375 to 430 px wide.

- Build for the narrow width first, then let wider screens add columns.
- No sideways scroll on the page. Wide tables scroll inside their own container, and long
  words or URLs wrap (overflow-wrap: anywhere).
- Images and SVGs take max-width: 100%.
- Use relative units for widths and media queries for layout changes; avoid fixed pixel
  widths above 340 px.
- Check that text does not grow on rotation: -webkit-text-size-adjust: 100%.

## Pages that remember, read usage and ask Claude

A page can keep what the user enters: a tracker's ticks, a form's draft, a list. Nest
keeps it per artifact, for every version, on all of the user's devices.

- To remember what the user enters, use localStorage as you normally would
  (localStorage.getItem/setItem work as usual; Nest keeps it); window.nest.storage offers
  the same with get/set and onChange for changes from the user's other devices. Keep values small and JSON-encoded; a page holds at most 1,000
  keys, 256 KiB a value and 2 MiB in all.
- Load the stored state first, then render, so the page opens as the user left it.
- Listen with window.nest.storage.onChange so a change on another device shows at once.
- Usage, in one line: await nest.usage() returns {limits: {five_hour: {utilization: a fraction 0 to 1 (0.42 is 42%), resets_at: ISO time} or null, seven_day: same}, today: {tokens, sessions}, week: {tokens, sessions}}; there are no token limits, only how full each window is; nest.onUsage(fn) gets the same object on changes.
- Asking, in one line: await nest.ask(prompt, {system}) returns {text, remaining, limit}; errors have .code budget, busy, disabled or unavailable.
- Ask Claude only for a small text task, such as a summary of what the user entered or a
  short line. It is limited (20 asks a day per artifact by default, short answers, no
  tools), so ask only when the user presses something, never on load or in a loop, show
  "Asking..." while it runs, and show the answer as text, not HTML.
- An <input type=file> works; keep a picked file's text in storage only when it is small.
- window.nest.saveFile({name, content, encoding, mime}) offers a file to save, such as an
  export as CSV.
- A multi-file page sends its files with the page and names them by relative paths; read
  data files with window.nest.files (list, text, dataUrl, blobUrl).
- Offer a quiet way to reset, and never lose entries when you update the page: keep the
  keys and their shape, or read the old shape and convert it.

## Documents and slides

- A document reads top to bottom: a short summary first, then sections under ## headings
  (they become the table of contents), each with one job. Keep headings short.
- Slides: one idea per slide, a heading that states it, at most five bullets of a few
  words each. Put detail in a document instead. Tables and diagrams should fit the slide
  without shrinking text below a readable size.

## Design systems

- Name colours by role (background, surface, text, muted, accent, danger), not by hue, and
  give each a light and a dark value.
- Include the colour named background so contrast is measured against it.
- Keep the type scale, spacing and radii short and consistent with each other.
- Each component's html shows its real states side by side: default, hover or pressed,
  disabled, and with long text.

## Mockup mode

When the user asks you to mock something up, sketch a screen, or explore a design before
a change, make a design artifact rather than a single html page. Nest shows it as a short
presentation: the intro, then each option with its label, title, description and framed
mockup.

- Start with the intro: what is being decided, in 2 to 4 sentences.
- Make 2 to 4 clearly different options, each with a clear label (A, B, C or 1, 2, 3), a
  title, and a description of its idea and trade-off in one or two sentences. Different
  means a different idea (layout, hierarchy, interaction), not another colour.
- Pick the layout by content: stack for full screens, grid for many small designs or
  elements, tabs when options are big and best compared one at a time.
- Pick the frame: window for Mac apps, browser for websites (with a url), phone or tablet
  bezels for mobile; none only if the html draws its own chrome.
- Use real content from the product, the repository or the conversation, not lorem ipsum;
  include an awkward case such as a long name or an empty state.
- Screens are static: no scripts. Show states as separate screens (for example "A,
  Settings" and "A, Settings with an error").
- Each screen renders in its own shadow root and :root in its CSS becomes :host, so define
  its variables on :root as usual and they stay inside that screen.
- For live 3D or animated pieces, make an html page laid out the same way (an intro, then
  labelled items with a title and description), since design screens are static.
- End the chat reply by asking the user to answer with a label. After they pick, refine
  that option with update_artifact, or build it for real.

## Mockup checklist

Before you save a design, check:

- [ ] An intro says what is being decided.
- [ ] Each option has a label, a title and a description of a different idea.
- [ ] Real content, no placeholders, one awkward case shown.
- [ ] Spacing from the scale, a short type scale, contrast that passes.
- [ ] Both light and dark look right, if the product has both.
- [ ] Hit targets of 44 px, nothing hidden behind hover.
- [ ] Nothing wider than its device frame, no sideways scroll on the phone.
- [ ] The layout and frames fit the content and the device.

## Before you save any page

- [ ] A short <title> and a heading that says what this is.
- [ ] Colours as variables with a dark block and an explicit body background.
- [ ] Fits a phone with no sideways scroll.
- [ ] Charts have titles, labels and units.
- [ ] Motion is short and turns off with prefers-reduced-motion.
- [ ] Libraries only from the allowed hosts, each with an exact version.
