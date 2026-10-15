import { ActionSheet } from "../../ui/Sheet.tsx";
import type { Review } from "./hooks.ts";

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
