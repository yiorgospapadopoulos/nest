import { useCallback, useRef, type CSSProperties } from "react";
import type { Pixie, UpdatePixieBody } from "../../api/types.ts";
import { PIXIE_COLORS } from "../../generated/mascots.ts";
import { MASCOTS } from "./options.ts";
import { Sprite } from "./Sprite.tsx";

interface Props {
  pixie: Pixie;
  save: (body: UpdatePixieBody) => void;
}

/** The mascot and colour rows, each saved on tap. */
export function PixieLook({ pixie, save }: Props) {
  const picker = useRef<HTMLInputElement | null>(null);
  // The colour is saved when the system picker closes ("change"), not on every move ("input").
  const listen = useCallback(
    (input: HTMLInputElement) => {
      picker.current = input;
      const onChange = () => {
        save({ color: input.value.toUpperCase() });
      };
      input.addEventListener("change", onChange);
      return () => {
        input.removeEventListener("change", onChange);
      };
    },
    [save],
  );
  const custom = !PIXIE_COLORS.includes(pixie.color);

  return (
    <>
      <div className="pxpick" role="group" aria-label="Mascot">
        {MASCOTS.map((mascot) => (
          <button
            key={mascot}
            className="pxm"
            aria-pressed={pixie.mascot === mascot}
            onClick={() => {
              save({ mascot });
            }}
          >
            <Sprite mascot={mascot} color={pixie.color} size={32} />
          </button>
        ))}
      </div>
      <div className="pxpick" role="group" aria-label="Colour">
        {PIXIE_COLORS.map((color) => (
          <button
            key={color}
            className="pxdot"
            style={{ "--px": color } as CSSProperties}
            aria-label={`Colour ${color}`}
            aria-pressed={pixie.color === color}
            onClick={() => {
              save({ color });
            }}
          />
        ))}
        <button
          className="pxdot pxcustom"
          aria-label="Custom colour"
          aria-pressed={custom}
          onClick={() => picker.current?.click()}
        />
        <input
          ref={listen}
          className="sr"
          type="color"
          tabIndex={-1}
          aria-label="Custom colour value"
          defaultValue={pixie.color.toLowerCase()}
        />
      </div>
    </>
  );
}
