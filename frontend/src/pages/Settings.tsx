// Settings.tsx - the AI model (automatic switching, keys, models) and the search profile. Every change is saved at once.
import { useEffect, useState } from "react";
import { api, type KeyState } from "../api";
import { Hero, Seg, Toggle, useAction, useToast } from "../components/ui";
import { useShared } from "../state";

export default function SettingsPage() {
  const [tab, setTab] = useState<"ai" | "profile">("ai");
  return (
    <>
      <Hero eyebrow="Preferences" title="Settings" lead="The AI model and your search profile. Every change is saved automatically." />
      <div style={{ marginBottom: 16 }}>
        <Seg options={["ai", "profile"]} value={tab} onChange={setTab} format={(t) => (t === "ai" ? "AI model" : "Search profile")} />
      </div>
      {tab === "ai" ? <AiModel /> : <Profile />}
    </>
  );
}

function AiModel() {
  const { settings, meta, save } = useShared();
  const { run, busy } = useAction();
  const toast = useToast();
  const [keys, setKeys] = useState<Record<string, KeyState>>({});
  const [prov, setProv] = useState<string>("");
  const [key, setKey] = useState("");
  const [models, setModels] = useState<Record<string, { models: string[]; tested: string[] }>>({});
  useEffect(() => { api.get<Record<string, KeyState>>("/keys").then(setKeys); }, []);
  useEffect(() => { if (settings && !prov) setProv(settings.config.model?.provider ?? "gemini"); }, [settings, prov]);
  if (!settings || !meta || !prov) return <span className="spinner" aria-label="Loading" />;
  const c = settings.config;
  const list = models[prov];
  const loadModels = async () => {
    const r = await run(() => api.get<{ ok: boolean; models: string[]; message: string; tested: string[] }>(`/models/${prov}`));
    if (!r) return;
    if (!r.ok) return toast(r.message, "error");
    setModels((m) => ({ ...m, [prov]: { models: r.models, tested: r.tested } }));
    if (!(c.model?.provider === prov && r.models.includes(c.model?.model))) save("config", { model: { provider: prov, model: r.models[0] } });
  };
  return (
    <section className="card">
      <Toggle checked={!!c.auto_models} onChange={(v) => save("config", { auto_models: v })} label="Switch models automatically"
        help="Starts with the most capable model. When a limit is reached, the next one takes over." />
      {c.auto_models && <p className="muted small">Order of use: {settings.models.order.map((x, i) => `${i + 1}. ${x}`).join(" → ")}</p>}
      <div className="row" style={{ marginTop: 12 }}>
        <label className="field" style={{ width: 240 }}>Provider
          <select value={prov} onChange={(e) => { setProv(e.target.value); setKey(""); }}>
            {meta.providers.map((p) => <option key={p} value={p}>{meta.provider_labels[p] ?? p}{keys[p]?.saved ? "  ✓ key" : ""}</option>)}
          </select></label>
        {prov !== "ollama" && (
          <>
            <label className="field grow">API key for {meta.provider_labels[prov] ?? prov}
              <input type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off"
                placeholder={keys[prov]?.saved ? `key saved (${keys[prov].masked})` : "paste your key"} /></label>
            <button className="btn primary" disabled={!key.trim() || busy}
              onClick={async () => { const r = await run(() => api.put<Record<string, KeyState>>(`/keys/${prov}`, { key }), `Key saved for ${prov}`); if (r) { setKeys(r); setKey(""); } }}>
              Save key</button>
          </>
        )}
      </div>
      <p className="muted small">Keys are kept in api_keys.txt on this computer, never in the database.</p>
      <button className="btn" disabled={busy} onClick={loadModels}>↻ Load the models</button>
      {list && (
        <label className="field" style={{ marginTop: 12, maxWidth: 520 }}>Model
          <select value={c.model?.provider === prov ? c.model.model : list.models[0]}
            onChange={(e) => save("config", { model: { provider: prov, model: e.target.value } })}>
            {list.models.map((m) => <option key={m} value={m}>{m}{list.tested.includes(m) ? "  (tested)" : ""}</option>)}
          </select>
          <span className="small">Tested: checked on this app's tasks (offer analysis, publication date, lab pages, browser).</span>
        </label>
      )}
      <p className="muted small" style={{ marginTop: 12 }}>In use: <b>{c.model?.provider} / {c.model?.model}</b></p>
    </section>
  );
}

function Profile() {
  const { settings, save } = useShared();
  const [kw, setKw] = useState<string | null>(null);
  const [ex, setEx] = useState<string | null>(null);
  if (!settings) return <span className="spinner" aria-label="Loading" />;
  const p = settings.profile, c = settings.config;
  const lines = (t: string) => t.split("\n").map((x) => x.trim()).filter(Boolean);
  return (
    <section className="card">
      <label className="field">My research interests (every offer is compared with this, in a search by CV)
        <textarea value={p.description ?? ""} onChange={(e) => save("profile", { description: e.target.value })} style={{ minHeight: 110 }} /></label>
      <div className="grid2" style={{ marginTop: 14 }}>
        <div>
          <label className="field">Wanted topics / titles — English or French, one per line
            <textarea style={{ minHeight: 280 }} value={kw ?? (p.keywords ?? []).join("\n")}
              onChange={(e) => { setKw(e.target.value); save("profile", { keywords: lines(e.target.value) }); }} onBlur={() => setKw(null)} /></label>
          <p className="muted small">A topic also finds its translation: <i>computer vision</i> matches <i>vision par ordinateur</i>.</p>
        </div>
        <div>
          <label className="field">Words that exclude an offer
            <textarea style={{ minHeight: 200 }} value={ex ?? (p.exclude_titles ?? []).join("\n")}
              onChange={(e) => { setEx(e.target.value); save("profile", { exclude_titles: lines(e.target.value) }); }} onBlur={() => setEx(null)} /></label>
          <label className="field" style={{ marginTop: 14 }}>Minimum relevance: <b>{c.min_relevance}</b>
            <input type="range" min={0} max={100} value={c.min_relevance ?? 60} onChange={(e) => save("config", { min_relevance: Number(e.target.value) })} /></label>
        </div>
      </div>
    </section>
  );
}
