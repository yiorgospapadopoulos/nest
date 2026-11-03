import { ApiError, type Api } from "../../../api/client.ts";
import type { FileText } from "../../../api/types.ts";

export type FileApi = Pick<Api, "configurationFile" | "writeConfigurationFile">;

export interface EditorState {
  // The draft.
  text: string;
  loaded: boolean;
  saving: boolean;
  // The file as it is on disk now, when it changed after it was read and the draft has
  // edits of its own.
  onDisk: FileText | null;
  // Why the daemon refused the text, such as invalid TOML.
  error: string | null;
}

/**
 * One configuration file in the editor sheet, as NestKit's ConfigFileEditor (B97). Saving
 * names the version it read, so a change made on disk meanwhile is never overwritten
 * without the user choosing to: the sheet then shows "changed on disk" with Reload and
 * Keep mine. `state` is replaced on every change, for React's external stores.
 */
export class FileEditor {
  state: EditorState = { text: "", loaded: false, saving: false, onDisk: null, error: null };
  // The version the draft started from; null for a file not made yet.
  private version: string | null = null;
  private original = "";
  private listeners = new Set<() => void>();

  private readonly api: FileApi;
  readonly path: string;

  constructor(api: FileApi, path: string) {
    this.api = api;
    this.path = path;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private busy(): boolean {
    return this.state.saving;
  }

  get dirty(): boolean {
    return this.state.text !== this.original;
  }

  async load(): Promise<void> {
    const file = await this.api.configurationFile(this.path);
    this.adopt(file, { loaded: true });
  }

  setText(text: string): void {
    this.set({ text });
  }

  /** The file changed somewhere: an untouched draft follows it; edits keep and show the bar. */
  async checkDisk(): Promise<void> {
    if (!this.state.loaded || this.state.saving) return;
    const file = await this.api.configurationFile(this.path);
    // A save may have started while the file was read.
    if (file.version === this.version || this.busy()) return;
    if (file.text === this.state.text || !this.dirty) this.adopt(file);
    else this.set({ onDisk: file });
  }

  /** Takes the file on disk, dropping the draft's edits. */
  reload(): void {
    if (this.state.onDisk !== null) this.adopt(this.state.onDisk);
  }

  /** Keeps the draft; the next save replaces what is on disk now. */
  keepMine(): void {
    const onDisk = this.state.onDisk;
    if (onDisk === null) return;
    this.version = onDisk.version;
    this.set({ onDisk: null });
  }

  /**
   * True when saved; false when the file changed on disk first, which shows the bar, or
   * when the daemon refused the text, which shows its words. Other failures are thrown.
   */
  async save(): Promise<boolean> {
    const text = this.state.text;
    this.set({ saving: true, error: null });
    try {
      const saved = await this.api.writeConfigurationFile(this.path, text, this.version);
      this.version = saved.version;
      this.original = text;
      this.set({ onDisk: null });
      return true;
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
      if (error.status === 409) {
        this.set({ onDisk: await this.api.configurationFile(this.path) });
        return false;
      }
      if (error.status === 400 || error.status === 422) {
        this.set({ error: error.message });
        return false;
      }
      throw error;
    } finally {
      this.set({ saving: false });
    }
  }

  private adopt(file: FileText, extra: Partial<EditorState> = {}): void {
    this.version = file.version;
    this.original = file.text;
    this.set({ text: file.text, onDisk: null, error: null, ...extra });
  }

  private set(change: Partial<EditorState>): void {
    this.state = { ...this.state, ...change };
    for (const listener of this.listeners) listener();
  }
}
