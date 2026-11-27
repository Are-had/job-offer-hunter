// state.tsx - what every page shares: the settings (saved as you change them) and the scan's live state (one SSE stream).
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Config, type Meta, type ScanState, type Settings } from "./api";
import { useToast } from "./components/ui";

type Group = "config" | "profile" | "applicant";

interface Shared {
  meta: Meta | null;
  settings: Settings | null;
  /** Changes some fields of a group: shown at once, saved shortly after (typing is saved once it pauses). */
  save: (group: Group, patch: Config) => void;
  reloadSettings: () => Promise<void>;
  scan: ScanState | null;
  refreshScan: () => Promise<void>;
}

const Ctx = createContext<Shared>(null as unknown as Shared);
export const useShared = () => useContext(Ctx);

export function SharedProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [meta, setMeta] = useState<Meta | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [scan, setScan] = useState<ScanState | null>(null);
  const pending = useRef<Partial<Record<Group, Config>>>({});
  const timer = useRef<number | undefined>(undefined);

  const reloadSettings = useCallback(async () => setSettings(await api.get<Settings>("/settings")), []);
  const refreshScan = useCallback(async () => setScan(await api.get<ScanState>("/scan")), []);

  useEffect(() => {
    api.get<Meta>("/meta").then(setMeta).catch((e) => toast(String(e.message ?? e), "error"));
    reloadSettings().catch((e) => toast(String(e.message ?? e), "error"));
    refreshScan().catch(() => {});
  }, [reloadSettings, refreshScan, toast]);

  // the scan's progress, pushed by the server (every second while a search runs)
  useEffect(() => {
    const es = new EventSource("/api/scan/events");
    es.onmessage = (ev) => {
      const next = JSON.parse(ev.data) as ScanState;
      setScan((prev) => ({ ...next, live: next.live ?? prev?.live }));
    };
    return () => es.close();
  }, []);

  const flush = useCallback(async () => {
    const todo = pending.current;
    pending.current = {};
    for (const [group, patch] of Object.entries(todo) as [Group, Config][]) {
      try {
        const s = await api.put<Settings>(`/settings/${group}`, patch);
        setSettings((cur) => (cur ? { ...cur, models: s.models } : s));
      } catch (e) {
        toast(`Not saved: ${e instanceof Error ? e.message : e}`, "error");
        reloadSettings();
      }
    }
  }, [reloadSettings, toast]);

  const save = useCallback((group: Group, patch: Config) => {
    setSettings((cur) => (cur ? { ...cur, [group]: { ...cur[group], ...patch } } : cur));
    pending.current[group] = { ...(pending.current[group] ?? {}), ...patch };
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(flush, 450);
  }, [flush]);

  // a change still waiting is saved when the page is left
  useEffect(() => {
    const out = () => { if (Object.keys(pending.current).length) flush(); };
    window.addEventListener("beforeunload", out);
    return () => window.removeEventListener("beforeunload", out);
  }, [flush]);

  return <Ctx.Provider value={{ meta, settings, save, reloadSettings, scan, refreshScan }}>{children}</Ctx.Provider>;
}

/** The keywords typed one per line, or with commas or semicolons; each one once. */
export function splitKeywords(text: string): string[] {
  return [...new Set(text.split(/[\n,;]/).map((k) => k.trim()).filter(Boolean))];
}
