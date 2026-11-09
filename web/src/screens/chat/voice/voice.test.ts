// Voice input's own logic (B154): the WAV the daemon accepts, and words that land in the
// draft without touching what is there.
import { describe, expect, it } from "vitest";
import { withSpoken } from "./spoken.ts";
import { resample, VOICE_RATE, wavRecording } from "./wav.ts";

async function header(blob: Blob) {
  const view = new DataView(await blob.arrayBuffer());
  const text = (at: number) =>
    String.fromCharCode(...[0, 1, 2, 3].map((i) => view.getUint8(at + i)));
  return {
    riff: text(0),
    wave: text(8),
    format: view.getUint16(20, true),
    channels: view.getUint16(22, true),
    rate: view.getUint32(24, true),
    bits: view.getUint16(34, true),
    dataBytes: view.getUint32(40, true),
    first: view.getInt16(44, true),
    size: blob.size,
  };
}

describe("recordings as the daemon takes them", () => {
  it("is a 16 kHz mono 16-bit PCM WAV, from a microphone at 48 kHz", async () => {
    const second = new Float32Array(48_000).fill(0.5);

    const wav = await header(wavRecording([second.slice(0, 24_000), second.slice(24_000)], 48_000));

    expect(wav).toMatchObject({
      riff: "RIFF",
      wave: "WAVE",
      format: 1,
      channels: 1,
      rate: VOICE_RATE,
      bits: 16,
      dataBytes: VOICE_RATE * 2,
      size: 44 + VOICE_RATE * 2,
    });
    expect(wav.first).toBe(Math.round(0.5 * 0x7fff - 0.5));
  });

  it("averages what it drops going down, and clips what is too loud", async () => {
    expect([...resample(new Float32Array([0, 0.3, 0.6, 1, 1, 1]), 48_000)]).toEqual([
      expect.closeTo(0.3),
      1,
    ]);
    const loud = await header(wavRecording([new Float32Array([-3])], VOICE_RATE));
    expect(loud.first).toBe(-0x8000);
  });
});

describe("what was said, put into the draft", () => {
  it("goes into an empty draft as it is, with the caret after it", () => {
    expect(withSpoken("", 0, " Run the tests. ")).toEqual({ text: "Run the tests.", caret: 14 });
  });

  it("gets a space where it would touch the words around it", () => {
    expect(withSpoken("Please now", 6, "run the tests")).toEqual({
      text: "Please run the tests now",
      caret: 20,
    });
    expect(withSpoken("Please ", 7, "go")).toEqual({ text: "Please go", caret: 9 });
  });

  it("changes nothing when nothing was heard", () => {
    expect(withSpoken("draft", 5, "  ")).toEqual({ text: "draft", caret: 5 });
  });
});
