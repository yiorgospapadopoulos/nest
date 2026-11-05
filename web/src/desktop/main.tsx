// Bundled, as the window's CSP allows no web fonts; the phone keeps the system font.
import "@fontsource-variable/inter";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../generated/tokens.css";
import "../styles/base.css";
import "../styles/chat.css";
import "../styles/screens.css";
import "../styles/settings.css";
import { platformBridge } from "./bridge.ts";
import { DesktopRoot } from "./DesktopApp.tsx";
import { transcriptTarget } from "./chat/transcriptTarget.ts";
import "./desktop.css";
import "./ui/ui.css";

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("Missing #root element in desktop.html");
}

const query = new URLSearchParams(window.location.search);
const view = query.get("view");
const transcript = view === "transcript" ? transcriptTarget(query) : null;
if (transcript !== null) {
  document.documentElement.classList.add("pane");
}

createRoot(rootElement).render(
  <StrictMode>
    <DesktopRoot bridge={platformBridge()} pill={view === "pill"} transcript={transcript} />
  </StrictMode>,
);
