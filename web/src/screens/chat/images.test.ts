import { afterEach, describe, expect, it, vi } from "vitest";
import { MAX_EDGE, prepareImage } from "./images.ts";

interface Drawn {
  width: number;
  height: number;
  type: string | undefined;
}

/** A decoder for images of the given size, and a canvas that records what it encoded. */
function fakeDecoding(width: number, height: number, { blob = true, context = true } = {}) {
  const close = vi.fn();
  const decode = vi.fn(() => Promise.resolve({ width, height, close }));
  vi.stubGlobal("createImageBitmap", decode);
  const drawn: Drawn[] = [];
  const draw = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(function () {
    return context ? ({ drawImage: draw } as unknown as CanvasRenderingContext2D) : null;
  } as typeof HTMLCanvasElement.prototype.getContext);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(function (
    this: HTMLCanvasElement,
    done: BlobCallback,
    type?: string,
  ) {
    drawn.push({ width: this.width, height: this.height, type });
    done(blob ? new Blob(["encoded"], { type: type ?? "image/png" }) : null);
  });
  return { decode, close, draw, drawn };
}

const image = (name: string, type: string) => new File(["raw"], name, { type });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("prepareImage", () => {
  it("leaves files that are not images, GIFs and SVGs as they are", async () => {
    const { decode } = fakeDecoding(4000, 3000);
    for (const file of [
      image("notes.txt", "text/plain"),
      image("cat.gif", "image/gif"),
      image("logo.svg", "image/svg+xml"),
    ]) {
      expect(await prepareImage(file)).toBe(file);
    }
    expect(decode).not.toHaveBeenCalled();
  });

  it("sends an image whose long edge fits as it is", async () => {
    const { close } = fakeDecoding(MAX_EDGE, 1200);
    const file = image("shot.png", "image/png");
    expect(await prepareImage(file)).toBe(file);
    expect(close).toHaveBeenCalled();
  });

  it("scales a large photo down to 2000 px on its long edge as JPEG", async () => {
    const { drawn, draw, close } = fakeDecoding(3000, 4000);
    const prepared = await prepareImage(image("IMG_1.JPG", "image/jpeg"));

    expect(drawn).toEqual([{ width: 1500, height: 2000, type: "image/jpeg" }]);
    expect(draw).toHaveBeenCalledWith(expect.anything(), 0, 0, 1500, 2000);
    expect(close).toHaveBeenCalled();
    expect(prepared.name).toBe("IMG_1.jpg");
    expect(prepared.type).toBe("image/jpeg");
  });

  it("keeps a large screenshot a PNG", async () => {
    const { drawn } = fakeDecoding(5000, 1000);
    const prepared = await prepareImage(image("image.png", "image/png"));
    expect(drawn).toEqual([{ width: 2000, height: 400, type: "image/png" }]);
    expect(prepared.name).toBe("image.png");
  });

  it("converts HEIC to JPEG, even a small one, by type or by name", async () => {
    const { drawn } = fakeDecoding(800, 600);
    const byType = await prepareImage(image("IMG_2.HEIC", "image/heic"));
    const byName = await prepareImage(image("photo.heif", ""));
    const noExtension = await prepareImage(image("photo", "image/heif"));

    expect(drawn).toEqual([
      { width: 800, height: 600, type: "image/jpeg" },
      { width: 800, height: 600, type: "image/jpeg" },
      { width: 800, height: 600, type: "image/jpeg" },
    ]);
    expect([byType.name, byName.name, noExtension.name]).toEqual([
      "IMG_2.jpg",
      "photo.jpg",
      "photo.jpg",
    ]);
    expect(byType.type).toBe("image/jpeg");
  });

  it("sends the original when the browser cannot decode or encode it", async () => {
    const heic = image("IMG_3.heic", "image/heic");
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn(() => Promise.reject(new Error("unsupported"))),
    );
    expect(await prepareImage(heic)).toBe(heic);

    const { close } = fakeDecoding(800, 600, { context: false });
    expect(await prepareImage(heic)).toBe(heic);
    expect(close).toHaveBeenCalled();

    vi.restoreAllMocks();
    fakeDecoding(800, 600, { blob: false });
    expect(await prepareImage(heic)).toBe(heic);
  });
});
