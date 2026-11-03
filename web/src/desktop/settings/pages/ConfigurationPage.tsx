import { ConfigModalsProvider } from "../config/ConfigModals.tsx";
import { ConfigurationView } from "../config/ConfigurationView.tsx";

/** Settings > Configuration (B97), with its editor and forms over it. */
export function ConfigurationPage() {
  return (
    <ConfigModalsProvider>
      <ConfigurationView />
    </ConfigModalsProvider>
  );
}
