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
import "./desktop.css";
import "./ui/ui.css";

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("Missing #root element in desktop.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <DesktopRoot
      bridge={platformBridge()}
      pill={new URLSearchParams(window.location.search).get("view") === "pill"}
    />
  </StrictMode>,
);
