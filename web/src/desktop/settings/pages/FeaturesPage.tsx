import { useEffect, useState } from "react";
import type { Feature, FeatureGroup, FeaturesCatalog } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { newIds } from "../../../screens/settings/featureNew.ts";
import { textRuns } from "../../../screens/settings/featureText.ts";
import { Fireflies } from "../../../ui/Fireflies.tsx";
import { Icon } from "../../../ui/Icon.tsx";
import { useSettingsVisit } from "../context.ts";
import { featuresFooter, featuresIntro, linuxKeys } from "../parts1/words.ts";
import "../parts1/parts1.css";

type Open = Record<string, boolean>;

/** The ids of the features the open groups show. */
const shownIds = (catalog: FeaturesCatalog, open: Open) =>
  catalog.groups.filter((g) => open[g.id] === true).flatMap((g) => g.features.map((f) => f.id));

/**
 * The Mac's Features (B103): what makes Nest different, one fold-open row per area. The
 * features the page shows are reported at once; their "New", the groups' dots and the
 * sidebar's count stay until Settings closes.
 */
export function FeaturesPage() {
  const { state } = useStore();
  const catalog = state.settings.features;
  if (catalog === null) {
    return (
      <div className="dkf">
        <p className="dkf-intro">{featuresIntro(0)}</p>
        <div className="dkf-loading">
          <Fireflies />
        </div>
      </div>
    );
  }
  return <Groups catalog={catalog} />;
}

function Groups({ catalog }: { catalog: FeaturesCatalog }) {
  const { actions } = useStore();
  const { visitNew, setVisitNew } = useSettingsVisit();
  // Fixed while the page shows, so the report that ends "New" on the daemon changes nothing.
  const [fresh] = useState(() => newIds(catalog, visitNew));
  const [open, setOpen] = useState<Open>(() => {
    const chosen = actions.featureGroups();
    return Object.fromEntries(
      catalog.groups.map((g) => [g.id, chosen[g.id] ?? g.features.some((f) => fresh.has(f.id))]),
    );
  });
  const [firstShown] = useState(() => shownIds(catalog, open));

  useEffect(() => {
    setVisitNew([...fresh]);
    void actions.markFeaturesShown(firstShown);
  }, [actions, firstShown, fresh, setVisitNew]);

  const toggle = (group: FeatureGroup) => {
    const opening = open[group.id] !== true;
    const next = { ...open, [group.id]: opening };
    setOpen(next);
    actions.setFeatureGroup(group.id, opening);
    if (opening) void actions.markFeaturesShown(shownIds(catalog, next));
  };

  const all = catalog.groups.flatMap((g) => g.features);
  const count = all.filter((f) => fresh.has(f.id)).length;
  return (
    <div className="dkf">
      <p className="dkf-intro">{featuresIntro(count)}</p>
      <div className="dkf-groups">
        {catalog.groups.map((group) => {
          const shown = open[group.id] === true;
          return (
            <div key={group.id} className="dkf-group">
              <button
                type="button"
                className="dkf-row"
                aria-expanded={shown}
                aria-label={`${group.name}, ${String(group.features.length)} features`}
                onClick={() => {
                  toggle(group);
                }}
              >
                <span className="dkf-name">{group.name}</span>
                {group.features.some((f) => fresh.has(f.id)) && (
                  <i className="dkf-dot" aria-label="Has new" />
                )}
                <span className="dkf-count">{group.features.length}</span>
                <Icon name="chevr" className={shown ? "dkf-cv open" : "dkf-cv"} />
              </button>
              {shown && (
                <div className="dkf-body">
                  {group.features.map((feature) => (
                    <FeatureRow key={feature.id} feature={feature} isNew={fresh.has(feature.id)} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p className="dkf-footer">{featuresFooter(all.length)}</p>
    </div>
  );
}

/** A feature: an optional New badge, its name and text, and where to find it on the right. */
function FeatureRow({ feature, isNew }: { feature: Feature; isNew: boolean }) {
  return (
    <div className="dkf-feature">
      <p>
        {isNew && <span className="dkf-new">New</span>}
        <b>{feature.name}</b>
        {"  "}
        <span className="dkf-text">
          {textRuns(feature.text).map((run, index) =>
            run.code ? <code key={index}>{run.text}</code> : run.text,
          )}
        </span>
      </p>
      <span className="dkf-where">{linuxKeys(feature.where)}</span>
    </div>
  );
}
