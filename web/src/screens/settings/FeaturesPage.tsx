import { useEffect, useState } from "react";
import type { Feature, FeatureGroup, FeaturesCatalog } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { Icon } from "../../ui/Icon.tsx";
import { newIds } from "./featureNew.ts";
import { textRuns } from "./featureText.ts";
import { Loading } from "./rows.tsx";

const INTRO = "What makes Nest different, by area. The README has every detail.";

type Open = Record<string, boolean>;

/** The ids of the features the open groups show. */
const shownIds = (catalog: FeaturesCatalog, open: Open) =>
  catalog.groups.filter((g) => open[g.id]).flatMap((g) => g.features.map((f) => f.id));

interface Props {
  // The features new when the page first showed in this visit to Settings, if it did.
  visitNew: string[] | null;
  onShow: (newIds: string[]) => void;
}

/**
 * Settings > Features (B103): what makes Nest different, by area, as the Mac's page. What
 * was new when the page first showed stays new until the user leaves Settings, and a group
 * opens when it has something new, unless the user opened or closed it by hand.
 */
export function FeaturesPage(props: Props) {
  const { state } = useStore();
  const catalog = state.settings.features;
  if (catalog === null) return <Loading />;
  return <Groups catalog={catalog} {...props} />;
}

function Groups({ catalog, visitNew, onShow }: Props & { catalog: FeaturesCatalog }) {
  const { actions } = useStore();
  // Fixed while the page shows, so the report that ends "New" on the Mac changes nothing here.
  const [fresh] = useState(() => newIds(catalog, visitNew));
  const [open, setOpen] = useState<Open>(() => {
    const chosen = actions.featureGroups();
    return Object.fromEntries(
      catalog.groups.map((g) => [g.id, chosen[g.id] ?? g.features.some((f) => fresh.has(f.id))]),
    );
  });
  const [firstShown] = useState(() => shownIds(catalog, open));

  useEffect(() => {
    onShow([...fresh]);
    void actions.markFeaturesShown(firstShown);
  }, [actions, firstShown, fresh, onShow]);

  const toggle = (group: FeatureGroup) => {
    const opening = open[group.id] !== true;
    const next = { ...open, [group.id]: opening };
    setOpen(next);
    actions.setFeatureGroup(group.id, opening);
    if (opening) void actions.markFeaturesShown(shownIds(catalog, next));
  };

  const count = catalog.groups.flatMap((g) => g.features).filter((f) => fresh.has(f.id)).length;
  return (
    <>
      <p className="ft-intro">
        {count > 0 ? `${INTRO} ${String(count)} new since your last update.` : INTRO}
      </p>
      <div className="ft-groups">
        {catalog.groups.map((group) => {
          const shown = open[group.id] === true;
          return (
            <section key={group.id} className="ft-grp">
              <button
                className="ft-row"
                aria-expanded={shown}
                onClick={() => {
                  toggle(group);
                }}
              >
                <span className="ft-name">{group.name}</span>
                {group.features.some((f) => fresh.has(f.id)) && (
                  <span className="sdot ft-dot" aria-hidden="true" />
                )}
                <span className="ft-n">{group.features.length}</span>
                <Icon name="chevr" className="ft-cv" />
              </button>
              {shown && (
                <div className="ft-body">
                  {group.features.map((f) => (
                    <FeatureRow key={f.id} feature={f} isNew={fresh.has(f.id)} />
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </>
  );
}

function FeatureRow({ feature, isNew }: { feature: Feature; isNew: boolean }) {
  return (
    <div className="feat">
      <div className="ftext">
        {isNew && <span className="fnew">New</span>}
        <span className="fname">{feature.name}</span>
        <span className="fdesc">
          {textRuns(feature.text).map((run, index) =>
            run.code ? <code key={index}>{run.text}</code> : run.text,
          )}
        </span>
      </div>
      <span className="fwhere">{feature.where}</span>
    </div>
  );
}
