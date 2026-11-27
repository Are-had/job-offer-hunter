// Quota.tsx - what each of your API keys has left: as the provider reports it, or as the app counts its calls.
import { useEffect, useState } from "react";
import { api, type QuotaBar, type QuotaCard } from "../api";
import { Bar, Hero } from "../components/ui";

type Quota = { cards: QuotaCard[]; jobspipe: (QuotaBar & { masked: string }) | null };

export default function QuotaPage() {
  const [q, setQ] = useState<Quota | null>(null);
  useEffect(() => {
    const get = () => api.get<Quota>("/quota").then(setQ).catch(() => {});
    get();
    const t = window.setInterval(get, 15000);
    return () => window.clearInterval(t);
  }, []);
  return (
    <>
      <Hero eyebrow="Settings" title="AI quota" lead="What each API key has left: as the provider reports it, or as the app counts its calls." />
      <p className="muted small">Gemini quotas reset around 09:00 (midnight Pacific time); Groq frees requests gradually over the day;
        Cohere's trial limit is monthly; NVIDIA limits requests per minute. Models are used in this order, best first.</p>
      {!q ? <span className="spinner" aria-label="Loading" /> : q.cards.length === 0 && !q.jobspipe ? (
        <div className="card empty"><b>No API key yet</b>Add one in Settings → AI model.</div>
      ) : null}
      {q?.cards.map((c) => (
        <section className="card" key={c.slot}>
          <h3>{c.provider}{c.nth && <span className="muted"> — {c.nth}</span>} <code className="muted small">{c.masked}</code></h3>
          {c.key_bar && <Bar share={c.key_bar.share} label={`Key — ${c.key_bar.text}`} />}
          {c.models.map((m) => <Bar key={m.model} share={m.share} kind={m.state} label={<><b>{m.model}</b> — {m.text}</>} />)}
        </section>
      ))}
      {q?.jobspipe && (
        <section className="card">
          <h3>JobsPipe <span className="muted">(job data, not AI)</span> <code className="muted small">{q.jobspipe.masked}</code></h3>
          <Bar share={q.jobspipe.share} label={q.jobspipe.text} />
        </section>
      )}
    </>
  );
}
