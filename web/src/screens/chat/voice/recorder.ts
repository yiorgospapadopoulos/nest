// The microphone, heard through Web Audio (B154), which the installed iPhone app and the
// Linux app's WebKitGTK both have, unlike one shared MediaRecorder format.
/* eslint-disable @typescript-eslint/no-deprecated -- ScriptProcessorNode: AudioWorklet
   needs a module the Linux app's script-src 'self' only allows as a built file, and the
   older node works in every engine Nest runs on. */
import { wavRecording } from "./wav.ts";

export interface Recording {
  /** Stops and gives what was heard as a WAV file. */
  stop: () => Blob;
  /** Stops and drops it. */
  cancel: () => void;
}

const CHUNK = 4096;

/** Whether this page can record: a secure page with a microphone and Web Audio. */
export function canRecord(): boolean {
  return (
    window.isSecureContext &&
    // Missing on an insecure page, and in a WebKitGTK with media streams off.
    "mediaDevices" in navigator &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    typeof AudioContext === "function"
  );
}

/**
 * Starts recording. Called from the tap itself: iOS lets an AudioContext run only when it
 * is made in a user's gesture. Rejects with the browser's error when the microphone cannot
 * be used.
 */
export function startRecording(): Promise<Recording> {
  const context = new AudioContext();
  // Not waited on: an iPhone may keep it interrupted around the microphone prompt, and the
  // samples start once it runs.
  void context.resume();
  return navigator.mediaDevices
    .getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    .then(
      (stream) => {
        const release = () => {
          for (const track of stream.getTracks()) track.stop();
          void context.close();
        };
        try {
          return listen(context, stream, release);
        } catch (error) {
          release();
          throw error;
        }
      },
      (error: unknown) => {
        void context.close();
        throw error;
      },
    );
}

function listen(context: AudioContext, stream: MediaStream, release: () => void): Recording {
  const source = context.createMediaStreamSource(stream);
  const processor = context.createScriptProcessor(CHUNK, 1, 1);
  const chunks: Float32Array[] = [];
  processor.onaudioprocess = (event) => {
    chunks.push(event.inputBuffer.getChannelData(0).slice());
  };
  source.connect(processor);
  // Some engines only process a node that leads somewhere; its output is silence.
  processor.connect(context.destination);
  const end = () => {
    processor.onaudioprocess = null;
    source.disconnect();
    processor.disconnect();
    release();
  };
  return {
    stop: () => {
      end();
      return wavRecording(chunks, context.sampleRate);
    },
    cancel: end,
  };
}
