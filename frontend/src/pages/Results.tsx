// Results.tsx - every offer found, with its link and why it was kept; mark it (applied / removed / comment), open its card,
// write its cover letter, fill its application. Your applications are kept between searches.
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type FillStatus, type Mark, type Offer, type OfferDetail } from "../api";
import Counters from "../components/Counters";
import { Chips, Hero, Pills, Score, Seg, useAction, useToast } from "../components/ui";
import { useShared } from "../state";

const VIEWS: Record<string, (o: Offer) => boolean> = {
  Relevant: (o) => o.status === "relevant", "To check": (o) => o.status === "review",
  "Not analysed": (o) => o.status === "candidate" || o.status === "new", Excluded: (o) => o.status === "excluded",
  Applied: (o) => o.applied, All: () => true,
};
type SortKey = "match" | "relevance" | "published" | "title" | "company";

export default function ResultsPage() {
  const { scan, meta } = useShared();
  const [offers, setOffers] = useState<Offer[] | null>(null);
  const [view, setView] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "match", desc: true });
  const [sel, setSel] = useState<string | null>(null);
  const [autofill, setAutofill] = useState<string | null>(null);
  const running = !!scan?.progress.running;

  const load = useCallback(() => api.get<Offer[]>("/offers").then(setOffers), []);
  useEffect(() => { load(); }, [load, scan?.progress.finished]);

  const counts = useMemo(() => Object.fromEntries(Object.entries(VIEWS).map(([k, f]) => [k, (offers ?? []).filter(f).length])), [offers]);
  const current = view ?? (["Relevant", "To check", "Not analysed"].find((k) => counts[k]) || "All");
  const present = useMemo(() => {
    const order = meta ? [...Object.values(meta.type_labels), "not stated"] : [];
    const rank = (x: string) => (order.indexOf(x) < 0 ? 99 : order.indexOf(x));
    return [...new Set((offers ?? []).map((o) => o.type))].sort((a, b) => rank(a) - rank(b));
  }, [offers, meta]);

  const rows = useMemo(() => {
    let v = (offers ?? []).filter(VIEWS[current]);
    if (kinds.length) v = v.filter((o) => kinds.includes(o.type));
    if (q.trim()) {
      const w = q.trim().toLowerCase();
      v = v.filter((o) => `${o.title} ${o.company} ${o.topics} ${o.type} ${o.comment}`.toLowerCase().includes(w));
    }
    const val = (o: Offer): number | string => {
      if (sort.key === "match") return o.match ?? -1;  // then relevance, then date
      if (sort.key === "relevance") return o.relevance ?? -1;
      return (o[sort.key] ?? "").toString().toLowerCase();
    };
    return [...v].sort((a, b) => {
      let r = val(a) < val(b) ? -1 : val(a) > val(b) ? 1 : 0;
      if (!r && sort.key === "match") r = (a.relevance ?? -1) - (b.relevance ?? -1) || a.published.localeCompare(b.published);
      return sort.desc ? -r : r;
    });
  }, [offers, current, kinds, q, sort]);

  const exportCsv = () => {
    const cols: (keyof Offer)[] = ["applied", "title", "company", "location", "published", "online_since", "type", "topics", "relevance", "match", "link", "comment"];
    const esc = (x: unknown) => `"${String(x ?? "").replace(/"/g, '""')}"`;
    const csv = [cols.join(","), ...rows.map((o) => cols.map((k) => esc(o[k])).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "offers.csv";
    a.click();
  };
  const head = (key: SortKey, label: string) => (
    <th className="sortable" aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : key !== "title" && key !== "company" }))}>
      {label}{sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}</th>
  );

  return (
    <>
      <Hero eyebrow="Offers" title="Results" lead="Every offer found, with its exact link, its publication date and why it was kept.">
        <Counters />
      </Hero>
      {running && (
        <div className="status-line" role="status"><span className="spinner" aria-hidden />
          <span style={{ flex: 1 }}>Search in progress — new offers keep arriving</span>
          <button className="btn small" onClick={load}>↻ Refresh</button></div>
      )}
      {offers && offers.length === 0 ? (
        <div className="card empty"><b>No offers yet</b>Follow the three steps on the Search page.</div>
      ) : (
        <section className="card">
          <div className="row" style={{ alignItems: "flex-end" }}>
            <div className="grow"><Seg label="Show" options={Object.keys(VIEWS)} value={current} onChange={(v) => { setView(v); setSel(null); }}
              format={(k) => `${k} (${counts[k] ?? 0})`} /></div>
            <label className="field" style={{ width: 320 }}>Filter
              <input type="text" value={q} onChange={(e) => setQ(e.target.value)} placeholder="title, company, topic, comment…" /></label>
          </div>
          {present.length > 1 && <div style={{ margin: "12px 0" }}>
            <Pills label="Contract" options={present} value={kinds} onChange={setKinds}
              format={(x) => `${x} (${(offers ?? []).filter(VIEWS[current]).filter((o) => o.type === x).length})`} /></div>}
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead><tr>
                <th title="You applied">applied</th>{head("title", "title")}{head("company", "company")}<th>location</th>
                {head("published", "published")}<th>online since</th><th>contract</th><th>topics</th>
                {head("relevance", "relevance")}{head("match", "CV match")}<th>offer link</th><th>apply</th><th>my comment</th>
              </tr></thead>
              <tbody>
                {rows.map((o) => (
                  <tr key={o.uid} className={`clickable${sel === o.uid ? " sel" : ""}`} onClick={() => setSel(o.uid)}
                    tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSel(o.uid)} aria-selected={sel === o.uid}>
                    <td>{o.applied ? "✓" : ""}</td>
                    <td className="title">{o.title}{o.not_checked && <div className="faint small">not checked by AI</div>}</td>
                    <td>{o.company}</td><td className="muted">{o.location}</td>
                    <td className="muted">{o.published || "not stated"}</td><td className="muted small">{o.online_since}</td>
                    <td>{o.type}</td><td className="muted small">{o.topics}</td>
                    <td><Score value={o.relevance} /></td><td><Score value={o.match} /></td>
                    <td className="small">{o.link ? <a href={o.link} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>{o.link}</a> : "—"}</td>
                    <td><button className="btn small" onClick={(e) => { e.stopPropagation(); setSel(o.uid); setAutofill(o.uid); }}>fill</button></td>
                    <td className="muted small">{o.comment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
            <button className="btn small" onClick={exportCsv}>⭳ Export CSV</button>
            <span className="muted small">{rows.length} offers shown. Click a row to open the offer, mark it as applied, remove it or comment it.</span>
          </div>
        </section>
      )}
      {sel && <OfferCard key={sel} uid={sel} autofill={autofill === sel} onChanged={load}
        onRemoved={() => { setSel(null); load(); }} onAutofilled={() => setAutofill(null)} />}
      <MyMarks onChanged={load} />
    </>
  );
}

// ------------------------------------------------------------------ the chosen offer
function OfferCard({ uid, autofill, onChanged, onRemoved, onAutofilled }: {
  uid: string; autofill: boolean; onChanged: () => void; onRemoved: () => void; onAutofilled: () => void;
}) {
  const toast = useToast();
  const { run, busy } = useAction();
  const [o, setO] = useState<OfferDetail | null>(null);
  const [note, setNote] = useState("");
  const load = useCallback(() => api.get<OfferDetail>(`/offers/${uid}`).then((d) => { setO(d); setNote(d.mark.note); }), [uid]);
  useEffect(() => { load().catch((e) => toast(e.message, "error")); }, [load, toast]);

  const mark = async (state: string | null, n?: string) => {
    const r = await run(() => api.post(`/offers/${uid}/mark`, { state, note: n ?? note }));
    if (!r) return;
    if (state === "dismissed") { toast(`Removed: ${o?.title.slice(0, 60)}`, "ok"); onRemoved(); return; }
    await load();
    onChanged();
  };
  const fill = useCallback(async () => {
    const r = await run(() => api.post<FillStatus>(`/offers/${uid}/fill`));
    if (r) setO((cur) => (cur ? { ...cur, fill: r } : cur));
  }, [run, uid]);
  useEffect(() => { if (autofill && o) { onAutofilled(); if (o.can_fill) fill(); else toast(o.fill_why || "This offer cannot be opened here.", "error"); } },
    [autofill, o, fill, onAutofilled, toast]);

  if (!o) return <section className="card"><span className="spinner" aria-label="Loading" /></section>;
  const applied = o.mark.state === "applied";
  return (
    <>
      <section className="card" aria-label="What you did with this offer">
        <div className="actions">
          <button className={`btn${applied ? "" : " primary"}`} disabled={busy} onClick={() => mark(applied ? "" : "applied")}
            title={applied ? "Click to undo" : undefined}>{applied ? "✓ Applied" : "➤ I applied"}</button>
          <button className="btn danger" disabled={busy} onClick={() => mark("dismissed")}
            title="Takes the offer out of the results; the next searches do not add it again">🗑 Remove: not for me</button>
          <label className="field grow">My comment
            <input type="text" value={note} placeholder="sent on 27/11 · call back in 2 weeks · asks for 3 years of experience…"
              onChange={(e) => setNote(e.target.value)} onBlur={() => note.trim() !== o.mark.note && mark(null, note)}
              onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} /></label>
        </div>
      </section>
      <section className="card">
        <h2>{o.title}</h2>
        <Chips items={[[o.company, "navy"], [o.status_label, { relevant: "green", review: "yellow", excluded: "red" }[o.status] ?? ""],
          [o.type, "blue"], [!o.type && "contract not stated"], [!o.published && "no publication date", "yellow"],
          [o.research_subject && "research subject", "blue"], [o.language], ...o.topics.map((t) => [t] as [string])]} />
        <div className="actions" style={{ marginTop: 14 }}>
          {o.link && <a className="btn primary" href={o.link} target="_blank" rel="noopener noreferrer">↗ Open the offer</a>}
          {o.apply_page && <a className="btn" href={o.apply_page} target="_blank" rel="noopener noreferrer">➤ Apply page</a>}
          <button className="btn" disabled={!o.can_fill || busy} onClick={fill}
            title={o.fill_why || "Opens the application in a browser window of the app on this computer, signs in (or creates your account) when the website asks, and fills in your details and a short message for this offer. You attach your CV and letter and submit yourself."}>
            ✎ Open and fill the application</button>
        </div>
        {o.fill && <Fill uid={uid} status={o.fill} onStatus={(f) => setO((cur) => (cur ? { ...cur, fill: f } : cur))} />}
        <div className="grid2" style={{ marginTop: 16 }}>
          <div>
            <div className="kv"><b>Published</b>{o.published || `not stated by the website${o.online_since ? ` — online since at least ${o.online_since}: published that day or before` : ""}`}</div>
            {(o.date_source || o.date_text) && <div className="muted small">{o.date_source || "—"}{o.date_text && ` · “${o.date_text}”`}</div>}
          </div>
          <div>
            <div className="kv"><b>Location</b>{o.location || "unknown"}</div>
            <div className="muted small">{o.location_evidence}</div>
          </div>
        </div>
        {o.relevance !== null && (
          <p><b>Relevance {Math.round(o.relevance)}/100</b> · {o.reasoning}
            {o.ai_model && <><br /><span className="muted small">Read by {o.ai_model}{o.first_reading && ` · first read by ${o.first_reading}, then by a better model`}</span></>}</p>
        )}
        {o.status === "review" && (
          <div className="notice warn">To check{o.review_flags.length ? `: ${o.review_flags.join(" · ")}` : "."}
            <div style={{ marginTop: 8 }}><button className="btn small" disabled={busy}
              onClick={async () => { if (await run(() => api.post(`/offers/${uid}/keep`))) { load(); onChanged(); } }}>Keep this offer</button></div></div>
        )}
        {o.status === "excluded" && <p className="muted small">Excluded: {o.reason}</p>}
        <details><summary>Description</summary><div className="desc">{o.description || "(none)"}</div></details>
      </section>
      {o.cvs.length > 0 && <LetterCard o={o} reload={load} />}
    </>
  );
}

function Fill({ uid, status, onStatus }: { uid: string; status: FillStatus; onStatus: (f: FillStatus) => void }) {
  const { run, busy } = useAction();
  const [code, setCode] = useState(""), [pw, setPw] = useState(""), [link, setLink] = useState("");
  useEffect(() => {  // follows the window: its state changes as the app fills the form
    const t = window.setInterval(() => api.get<FillStatus | null>(`/offers/${uid}/fill`).then((f) => f && onStatus(f)).catch(() => {}), 2000);
    return () => window.clearInterval(t);
  }, [uid, onStatus]);
  const go = async (body: object) => { const r = await run(() => api.post<FillStatus>(`/offers/${uid}/fill/continue`, body)); if (r) onStatus(r); };
  const cls = { filled: "ok", error: "error", nothing: "", by_email: "" }[status.state] ?? "warn";
  return (
    <div style={{ marginTop: 12 }}>
      <div className={`notice ${cls}`}>{status.message}{status.filled.length > 0 && ` Filled: ${status.filled.join(", ")}.`}</div>
      <button className="btn small" disabled={busy} onClick={() => go({})}
        title="After you acted in the window: signed in, solved a captcha, ticked a box, opened the next step">▶ Continue</button>
      {status.state === "needs_code" && (
        <div className="row" style={{ marginTop: 8 }}>
          <input type="text" className="grow" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Code received by email" />
          <button className="btn" disabled={!code.trim() || busy} onClick={() => go({ code })}>Send the code</button>
        </div>
      )}
      {(status.state === "needs_link" || status.state === "wrong_password") && status.site && (
        <>
          <div className="row" style={{ marginTop: 8 }}>
            <input type="password" className="grow" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password from the website's email (if it sent one)" />
            <button className="btn" disabled={!pw.trim() || busy} onClick={() => go({ password: pw })}>Use this password</button>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <input type="text" className="grow" value={link} onChange={(e) => setLink(e.target.value)} placeholder="…or paste the link from the website's email" />
            <button className="btn" disabled={!link.trim() || busy} onClick={() => go({ link })}>Open it in the window</button>
          </div>
        </>
      )}
      {status.account && <p className="muted small">Account on {status.site}: {status.account.email} · {status.account.state} (password: Search, step 2)</p>}
      {status.steps.length > 0 && <p className="muted small">Steps: {status.steps.join(" → ")}</p>}
      {status.letter_note && (
        <details><summary>{status.letter ? `Cover letter pasted in the form: ${status.letter_note}` : `Cover letter: ${status.letter_note}`}</summary>
          {status.letter && <pre className="log">{status.letter}</pre>}</details>
      )}
    </div>
  );
}

function LetterCard({ o, reload }: { o: OfferDetail; reload: () => Promise<void> }) {
  const { run, busy } = useAction();
  const [cv, setCv] = useState(o.cvs.includes(o.best_cv) ? o.best_cv : o.cvs[0]);
  const [tex, setTex] = useState(o.letter?.tex ?? "");
  useEffect(() => setTex(o.letter?.tex ?? ""), [o.letter?.id, o.letter?.tex]);
  return (
    <section className="card">
      <div className="section" style={{ marginTop: 0 }}>CV match & cover letter</div>
      {o.match.length > 0 && (
        <div className="table-wrap" style={{ marginBottom: 12 }}><table>
          <thead><tr><th>cv</th><th>score</th><th>advice</th><th>missing</th><th>not shown in CV</th></tr></thead>
          <tbody>{o.match.map((m) => <tr key={m.cv}><td>{m.cv}</td><td><Score value={m.score} /></td><td>{m.advice}</td>
            <td className="muted small">{m.missing}</td><td className="muted small">{m.not_shown}</td></tr>)}</tbody>
        </table></div>
      )}
      <div className="row">
        {o.match.length === 0 && <button className="btn" disabled={busy}
          onClick={async () => { if (await run(() => api.post(`/offers/${o.uid}/match`))) reload(); }}>⇄ Compare with my CV</button>}
        <button className="btn" disabled={busy}
          onClick={async () => { if (await run(() => api.post(`/offers/${o.uid}/letter`, { cv }), "Letter written")) reload(); }}>
          {busy ? "Working…" : "✎ Write cover letter"}</button>
        <label className="field grow" style={{ maxWidth: 360 }}>CV for the letter
          <select value={cv} onChange={(e) => setCv(e.target.value)}>{o.cvs.map((x) => <option key={x}>{x}</option>)}</select></label>
      </div>
      {o.letter && (
        <div style={{ marginTop: 12 }}>
          <label className="field">Letter v{o.letter.version} (LaTeX, editable)
            <textarea className="code" style={{ minHeight: 260 }} value={tex} onChange={(e) => setTex(e.target.value)} /></label>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn" disabled={busy || tex === o.letter.tex}
              onClick={async () => { if (await run(() => api.put(`/offers/${o.uid}/letter`, { tex, cv }), "Saved as a new version")) reload(); }}>💾 Save as new version</button>
            <a className="btn" href={`/api/offers/${o.uid}/letter.tex`}>⭳ Download .tex</a>
            {o.letter.pdf && <a className="btn" href={`/api/offers/${o.uid}/letter.pdf`}>⭳ Download PDF</a>}
          </div>
        </div>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ your applications, kept between searches
const MARK_LABEL: Record<string, string> = { applied: "applied", dismissed: "removed (not for me)", "": "comment only" };

function MyMarks({ onChanged }: { onChanged: () => void }) {
  const { run } = useAction();
  const [marks, setMarks] = useState<Mark[]>([]);
  const [open, setOpen] = useState(false);
  const load = useCallback(() => api.get<Mark[]>("/marks").then(setMarks), []);
  useEffect(() => { load(); }, [load, open]);
  if (!marks.length) return null;
  const applied = marks.filter((m) => m.state === "applied").length, removed = marks.filter((m) => m.state === "dismissed").length;
  const edit = async (uid: string, body: object) => { if (await run(() => api.put(`/marks/${uid}`, body))) { load(); onChanged(); } };
  const exportCsv = () => {
    const esc = (x: unknown) => `"${String(x ?? "").replace(/"/g, '""')}"`;
    const csv = ["status,title,company,comment,date,link", ...marks.map((m) =>
      [MARK_LABEL[m.state] ?? m.state, m.title, m.company, m.note, m.date, m.link].map(esc).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "my_applications.csv";
    a.click();
  };
  return (
    <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>Your applications and removed offers — {applied} applied, {removed} removed</summary>
      <p className="muted small">Kept between searches. Applied or removed, an offer is not added again by the next searches. Change the
        status or the comment here; forget a row so that the searches can show the offer again.</p>
      <div className="table-wrap"><table>
        <thead><tr><th>status</th><th>title</th><th>company</th><th>my comment</th><th>date</th><th>link</th><th></th></tr></thead>
        <tbody>{marks.map((m) => (
          <tr key={m.uid}>
            <td><select value={m.state} onChange={(e) => edit(m.uid, { state: e.target.value })}>
              {Object.entries(MARK_LABEL).map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></td>
            <td className="title">{m.title}</td><td>{m.company}</td>
            <td><input type="text" defaultValue={m.note} onBlur={(e) => e.target.value.trim() !== m.note && edit(m.uid, { note: e.target.value })} /></td>
            <td className="muted small">{m.date}</td>
            <td>{m.link ? <a href={m.link} target="_blank" rel="noopener noreferrer">open</a> : "—"}</td>
            <td><button className="btn small danger" title="Forget: the searches can show the offer again"
              onClick={async () => { if (await run(() => api.del(`/marks/${m.uid}`))) { load(); onChanged(); } }}>Forget</button></td>
          </tr>
        ))}</tbody>
      </table></div>
      <button className="btn small" style={{ marginTop: 10 }} onClick={exportCsv}>⭳ Export my applications (CSV)</button>
    </details>
  );
}
