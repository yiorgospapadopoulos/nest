// The service worker entry, built to /sw.js.
import { installWorker, type WorkerScope } from "./serviceWorker.ts";

installWorker(self as unknown as WorkerScope);
