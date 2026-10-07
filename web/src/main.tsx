import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HttpApi } from "./api/client.ts";
import type { SocketLike } from "./api/events.ts";
import { App } from "./App.tsx";
import "./generated/tokens.css";
import { registerServiceWorker } from "./pwa/register.ts";
import "./styles/base.css";
import "./styles/chat.css";
import "./styles/screens.css";

const rootElement = document.getElementById("root");
if (rootElement === null) {
  throw new Error("Missing #root element in index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <App api={new HttpApi()} connect={(url) => new WebSocket(url) as unknown as SocketLike} />
  </StrictMode>,
);

void registerServiceWorker(navigator, import.meta.env.PROD);
