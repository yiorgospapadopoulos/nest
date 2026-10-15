import { useEffect } from "react";
import { useStore } from "../../store/context.ts";
import { AgentDefaultsCard } from "./AgentDefaultsCard.tsx";
import { AppearanceCard } from "./AppearanceCard.tsx";
import { ConnectorsCard } from "./ConnectorsCard.tsx";
import { NotificationsCard } from "./NotificationsCard.tsx";
import { ProfileCard } from "./ProfileCard.tsx";
import { RestartCard } from "./RestartCard.tsx";
import { UsageCard } from "./UsageCard.tsx";

export function Account() {
  const { actions } = useStore();

  useEffect(() => {
    void actions.loadAccount();
    void actions.loadChoices();
  }, [actions]);

  return (
    <>
      <div className="navr" />
      <h1 className="lt">Account</h1>
      <ProfileCard />
      <UsageCard />
      <AgentDefaultsCard />
      <ConnectorsCard />
      <NotificationsCard />
      <AppearanceCard />
      <RestartCard />
    </>
  );
}
