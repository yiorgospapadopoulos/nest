import { useId } from "react";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";
import type { Review } from "./hooks.ts";

/** The agent ran git itself; publishing waits for the switch, as on the Mac. */
export function ViolationNotice({ review }: { review: Review }) {
  const id = useId();
  if (!review.violation) return null;
  return (
    <div className="vio">
      <p>
        <Icon name="shield" />
        The agent ran git itself and changed this chat&apos;s branch. Check its commits before
        publishing.
      </p>
      <div className="vio-r">
        <span id={id}>I checked, publish anyway</span>
        <button
          className="sw"
          role="switch"
          aria-checked={review.acknowledged}
          aria-labelledby={id}
          // What was checked is the loaded review; a new one asks again.
          disabled={review.diff === null}
          onClick={() => {
            review.setAcknowledged(!review.acknowledged);
          }}
        />
      </div>
    </div>
  );
}

/**
 * Publishing waits until the user confirms where origin pushes (D050). With one address,
 * "Push there" approves again with it; otherwise origin needs fixing on the Mac first.
 */
export function RemoteConfirmation({ review }: { review: Review }) {
  const prompt = review.remote;
  if (prompt === null) return null;
  const [url, ...others] = prompt.urls;
  const single = url !== undefined && others.length === 0;
  return (
    <ActionSheet
      label="Confirm the push address"
      role="alertdialog"
      onClose={review.cancelRemote}
      title={
        <>
          <b>Confirm the push address</b>
          {!single ? (
            <>
              {url === undefined
                ? "origin has no push address."
                : `origin pushes to more than one address: ${prompt.urls.join(", ")}.`}{" "}
              Fix origin on your Mac, then approve again.
            </>
          ) : prompt.confirmed === null ? (
            `origin pushes to ${url}. Nest pushes only to an address you confirmed.`
          ) : (
            `origin now pushes to ${url} instead of ${prompt.confirmed}, the address Nest recorded.`
          )}
        </>
      }
    >
      {single && (
        <button
          className="asi mid"
          disabled={!review.ready}
          onClick={() => void review.pushThere(prompt.message, url)}
        >
          Push there
        </button>
      )}
    </ActionSheet>
  );
}
