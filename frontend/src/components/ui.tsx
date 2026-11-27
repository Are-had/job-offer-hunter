// ui.tsx - the small pieces every page uses: steps, pills, toggles, progress bars, chips, toasts, file drop.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

export function Step({ n, title, done }: { n: number; title: string; done: boolean }) {
  return (
    <div className="step">
      <span className={`stepnum${done ? " done" : ""}`} aria-label={done ? "done" : undefined}>{done ? "✓" : n}</span>
      {title}
    </div>
  );
}

export function Hero({ eyebrow, title, lead, children }: { eyebrow: string; title: string; lead?: string; children?: ReactNode }) {
  return (
    <header className="hero">
      <div className="eyebrow">{eyebrow}</div>
      <h1>{title}</h1>
      {lead && <p className="lead">{lead}</p>}
      {children}
    </header>
  );
}

export function Pills<T extends string>({ options, value, onChange, label, multi = true, disabled, format }: {
  options: T[]; value: T[]; onChange: (v: T[]) => void; label?: string; multi?: boolean; disabled?: boolean;
  format?: (o: T) => string;
}) {
  const toggle = (o: T) => {
    if (!multi) return onChange([o]);
    onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o]);
  };
  return (
    <div role="group" aria-label={label}>
      {label && <div className="muted small" style={{ marginBottom: 6 }}>{label}</div>}
      <div className="pills">
        {options.map((o) => (
          <button key={o} type="button" className={`pill${value.includes(o) ? " on" : ""}`} aria-pressed={value.includes(o)}
            disabled={disabled} onClick={() => toggle(o)}>{format ? format(o) : o}</button>
        ))}
      </div>
    </div>
  );
}

export function Seg<T extends string>({ options, value, onChange, format, disabled, label }: {
  options: T[]; value: T; onChange: (v: T) => void; format?: (o: T) => string; disabled?: boolean; label?: string;
}) {
  return (
    <div>
      {label && <div className="muted small" style={{ marginBottom: 6 }}>{label}</div>}
      <div className="seg" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button key={o} type="button" role="radio" aria-checked={o === value} className={o === value ? "on" : ""}
            disabled={disabled} onClick={() => onChange(o)}>{format ? format(o) : o}</button>
        ))}
      </div>
    </div>
  );
}

export function Toggle({ checked, onChange, label, help, disabled }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; help?: string; disabled?: boolean;
}) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="t">{label}{help && <small>{help}</small>}</span>
    </label>
  );
}

export function Bar({ share, label, right, kind }: { share: number; label: ReactNode; right?: ReactNode; kind?: string }) {
  const pct = Math.max(0, Math.min(1, share)) * 100;
  return (
    <div className="progress">
      <div className="label"><span>{label}</span>{right !== undefined && <span>{right}</span>}</div>
      <div className="track" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <div className={`fill ${kind ?? ""}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Chips({ items }: { items: [string | false | null | undefined, string?][] }) {
  return (
    <div className="chips">
      {items.filter(([t]) => t).map(([t, cls], i) => <span key={i} className={`chip ${cls ?? ""}`}>{t}</span>)}
    </div>
  );
}

export function Score({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span className="faint">—</span>;
  return (
    <div className="score" title={`${Math.round(value)} / 100`}>
      <div className="track"><div className="fill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></div>
      <b>{Math.round(value)}</b>
    </div>
  );
}

export function Drop({ accept, multiple = true, label, onFiles, disabled }: {
  accept: string; multiple?: boolean; label: string; onFiles: (f: File[]) => void; disabled?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div className={`drop${over ? " over" : ""}`} role="button" tabIndex={0} aria-disabled={disabled}
      onClick={() => !disabled && ref.current?.click()}
      onKeyDown={(e) => { if (!disabled && (e.key === "Enter" || e.key === " ")) ref.current?.click(); }}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled && e.dataTransfer.files.length) onFiles(Array.from(e.dataTransfer.files)); }}>
      {label}
      <input ref={ref} type="file" accept={accept} multiple={multiple} hidden disabled={disabled}
        onChange={(e) => { if (e.target.files?.length) onFiles(Array.from(e.target.files)); e.target.value = ""; }} />
    </div>
  );
}

// ---------- toasts
type Toast = { id: number; text: string; kind: "ok" | "error" | "" };
const ToastCtx = createContext<(text: string, kind?: Toast["kind"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: Toast["kind"] = "") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 8000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

/** Runs an action, shows its error as a toast; returns its result (undefined on error). */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(async <T,>(fn: () => Promise<T>, ok?: string): Promise<T | undefined> => {
    setBusy(true);
    try {
      const r = await fn();
      if (ok) toast(ok, "ok");
      return r;
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [toast]);
  return { run, busy };
}
