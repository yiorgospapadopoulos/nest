// A recording as voice input takes it (B154): WAV, 16-bit PCM, one channel at 16 kHz, what
// Whisper hears, so the daemon needs no audio decoder.

export const VOICE_RATE = 16_000;
const HEADER_BYTES = 44;

/** The samples at 16 kHz; each one going down is the mean of the input it covers. */
export function resample(input: Float32Array, rate: number): Float32Array {
  if (rate === VOICE_RATE) return input.slice();
  const ratio = rate / VOICE_RATE;
  const output = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < output.length; i++) {
    const start = i * ratio;
    if (ratio < 1) {
      // Up from a slower rate: between the two samples around it.
      const before = Math.floor(start);
      const after = Math.min(before + 1, input.length - 1);
      const weight = start - before;
      output[i] = (input[before] ?? 0) * (1 - weight) + (input[after] ?? 0) * weight;
      continue;
    }
    const from = Math.floor(start);
    const to = Math.min(input.length, Math.max(from + 1, Math.floor(start + ratio)));
    let sum = 0;
    for (let j = from; j < to; j++) sum += input[j] ?? 0;
    output[i] = sum / (to - from);
  }
  return output;
}

/** The chunks a recorder heard at `rate`, as one WAV file. */
export function wavRecording(chunks: readonly Float32Array[], rate: number): Blob {
  const joined = new Float32Array(chunks.reduce((total, chunk) => total + chunk.length, 0));
  let offset = 0;
  for (const chunk of chunks) {
    joined.set(chunk, offset);
    offset += chunk.length;
  }
  const samples = resample(joined, rate);
  const buffer = new ArrayBuffer(HEADER_BYTES + samples.length * 2);
  const view = new DataView(buffer);
  const text = (at: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(at + i, value.charCodeAt(i));
  };
  text(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // one channel
  view.setUint32(24, VOICE_RATE, true);
  view.setUint32(28, VOICE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(HEADER_BYTES + i * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
  });
  return new Blob([buffer], { type: "audio/wav" });
}
