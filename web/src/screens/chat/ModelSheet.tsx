import { isSelected } from "../../store/catalog.ts";
import { useStore } from "../../store/context.ts";
import { modelSections } from "../../store/selectors.ts";
import { Icon } from "../../ui/Icon.tsx";
import { ActionSheet } from "../../ui/Sheet.tsx";

interface Props {
  // The chat's engine and model; a new chat's (`isDraft`) as chosen so far.
  provider: string;
  model: string | null;
  isDraft: boolean;
  onPick: (model: string, provider: string) => void;
  onClose: () => void;
}

/**
 * The composer's one model menu, as the Mac's (B91, B94): a new chat lists each engine's
 * models under its name, with its plan or "Not signed in", and choosing a model chooses
 * its engine; an open chat lists only its own engine's. Real models only, no default entry.
 */
export function ModelSheet({ provider, model, isDraft, onPick, onClose }: Props) {
  const { state } = useStore();
  const sections = modelSections(state, provider, isDraft);
  return (
    <ActionSheet label="Model" onClose={onClose}>
      {sections.map((section) => (
        <div key={section.provider} className="asec" role="group" aria-label={section.title}>
          <div className="ash" aria-hidden="true">
            <b>{section.title}</b>
            {section.detail !== "" && <small>{section.detail}</small>}
          </div>
          {section.catalog.models.length === 0 && (
            <button className="asi" role="menuitem" disabled>
              Models unavailable
            </button>
          )}
          {section.catalog.models.map((option) => {
            const checked =
              section.provider === provider && isSelected(section.catalog, option, model);
            return (
              <button
                key={option.value}
                className="asi"
                role="menuitemradio"
                aria-checked={checked}
                data-autofocus={checked ? true : undefined}
                onClick={() => {
                  onPick(option.value, section.provider);
                  onClose();
                }}
              >
                <span>
                  <span>{option.display_name}</span>
                  {option.description !== "" && <small>{option.description}</small>}
                </span>
                <Icon name="check" className="ck2" />
              </button>
            );
          })}
        </div>
      ))}
    </ActionSheet>
  );
}
