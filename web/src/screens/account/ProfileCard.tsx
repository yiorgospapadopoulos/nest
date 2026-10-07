import { useState } from "react";
import { useStore } from "../../store/context.ts";

/** Who Claude Code is signed in as; the email stays hidden until asked for. */
export function ProfileCard() {
  const { state } = useStore();
  const [showEmail, setShowEmail] = useState(false);
  const account = state.account;
  return (
    <section aria-labelledby="profile-title">
      <h2 className="pg-h" id="profile-title">
        Profile
      </h2>
      {account === null ? (
        <div className="lgrp gl pad note">Loading...</div>
      ) : (
        <div className="lgrp gl">
          <div className="srow">
            <span>{account.display_name ?? "Claude account"}</span>
            <span className="hint">{account.plan ?? "Plan not reported"}</span>
          </div>
          {account.email !== null && (
            <div className="srow">
              <span>Email</span>
              {showEmail ? (
                <span className="hint">{account.email}</span>
              ) : (
                <button
                  className="b"
                  aria-label="Show email"
                  onClick={() => {
                    setShowEmail(true);
                  }}
                >
                  Show
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
