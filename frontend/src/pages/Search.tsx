// Search.tsx - the three steps: career websites, what you look for (CV or keywords), the analysis; then the live search.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Config, type Coverage, type Cv, type Offer, type Problem, type Source } from "../api";
import Counters from "../components/Counters";
import { Bar, Chips, Drop, Hero, Pills, Seg, Step, Toggle, useAction, useToast } from "../components/ui";
import { splitKeywords, useShared } from "../state";

export default function SearchPage() {
  const { scan } = useShared();
  const running = !!scan?.summary.running;
  return (
    <>
      <Hero eyebrow="Search · 3 steps" title="Find research & engineering offers in France"
        lead="Load the career websites, say what you look for, then let the app read every offer, date it, place it and rank it.">
        <Counters />
      </Hero>
      <Websites running={running} />
      <LookingFor running={running} />
      <Analysis running={running} />
    </>
  );
}

// ------------------------------------------------------------------ step 1
function Websites({ running }: { running: boolean }) {
  const { scan, refreshScan } = useShared();
  const toast = useToast();
  const { run, busy } = useAction();
  const [sources, setSources] = useState<{ sources: Source[]; changed: Source[] } | null>(null);
  const [pasted, setPasted] = useState("");
  const load = useCallback(() => api.get<{ sources: Source[]; changed: Source[] }>("/sources").then(setSources), []);
  useEffect(() => { load(); }, [load, scan?.progress.finished]);

  const upload = async (files: File[]) => {
    const r = await run(() => api.upload<{ loaded: number; skipped: string[] }>("/sources/files", files));
    if (r) {
      await Promise.all([load(), refreshScan()]);
      if (r.skipped.length) toast(`Over 2 MB, skipped: ${r.skipped.join(", ")}`, "error");
    }
  };
  const usePasted = async () => {
    if (await run(() => api.post("/sources/urls", { text: pasted }), "Websites loaded")) {
      setPasted("");
      await Promise.all([load(), refreshScan()]);
    }
  };
  const n = sources?.sources.length ?? 0;
  return (
    <section className="card" aria-labelledby="s1">
      <div id="s1"><Step n={1} title="Career websites" done={n > 0} /></div>
      <Drop accept=".html,.htm" label={busy ? "Loading…" : "Drop the HTML file(s) with the career pages here, or click to choose them — read, never executed"}
        onFiles={upload} disabled={running || busy} />
      <details>
        <summary>…or paste URLs</summary>
        <textarea placeholder="One URL per line" value={pasted} onChange={(e) => setPasted(e.target.value)} disabled={running} />
        <div style={{ marginTop: 8 }}>
          <button className="btn" disabled={running || !pasted.trim() || busy} onClick={usePasted}>Use these URLs</button>
        </div>
      </details>
      {n > 0 && (
        <>
          <p className="muted small"><b className="muted">{n} websites</b> ready. Loading another file replaces them. Search words,
            page numbers and tracking codes from a past search are removed from company URLs, so every website is read whole and
            filtered the same way; country filters and job-board searches are kept.</p>
          {sources!.changed.length > 0 && (
            <div className="notice warn"><b>{sources!.changed.length} website(s) changed since the previous scan</b>:{" "}
              {sources!.changed.slice(0, 5).map((x) => `${x.website}: ${x.since_last_scan}`).join("; ")}{sources!.changed.length > 5 ? " …" : ""}</div>
          )}
          <details>
            <summary>Websites and how each one was read</summary>
            <div className="table-wrap" style={{ maxHeight: 420 }}>
              <table>
                <thead><tr><th>website</th><th>file</th><th>read by</th><th>status</th><th>offers</th><th>since last scan</th><th>note</th><th>url</th></tr></thead>
                <tbody>
                  {sources!.sources.map((x) => (
                    <tr key={x.id}><td>{x.website}</td><td className="muted">{x.file}</td><td>{x.read_by || "—"}</td><td>{x.status}</td>
                      <td className="num">{x.offers}</td><td className="muted">{x.since_last_scan}</td><td className="muted small">{x.note}</td>
                      <td><a href={x.url} target="_blank" rel="noopener noreferrer">open</a></td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}

// ------------------------------------------------------------------ step 2
function LookingFor({ running }: { running: boolean }) {
  const { settings, meta, save, refreshScan, scan } = useShared();
  const { run } = useAction();
  const toast = useToast();
  const [cvs, setCvs] = useState<Cv[]>([]);
  const [words, setWords] = useState<string | null>(null);
  const loadCvs = useCallback(() => api.get<Cv[]>("/cvs").then(setCvs), []);
  useEffect(() => { loadCvs(); }, [loadCvs]);
  if (!settings || !meta) return <section className="card"><Step n={2} title="What you look for" done={false} /></section>;
  const p = settings.profile, c = settings.config;
  const mode: string = p.search_mode === "keywords" ? "keywords" : "cv";
  const kw: string[] = p.my_keywords ?? [];
  const text = words ?? kw.join("\n");
  const done = mode === "keywords" ? kw.length > 0 : cvs.length > 0;

  const addCvs = async (files: File[]) => {
    const r = await run(() => api.upload<{ errors: string[]; cvs: Cv[] }>("/cvs", files));
    if (r) {
      setCvs(r.cvs);
      r.errors.forEach((e) => toast(e, "error"));
      refreshScan();
    }
  };
  const removeCv = async (id: number) => {
    if (await run(() => api.del(`/cvs/${id}`))) { loadCvs(); refreshScan(); }
  };
  const cvBlock = (label: string) => (
    <>
      <Drop accept=".pdf" label={label} onFiles={addCvs} disabled={running} />
      <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
        {cvs.map((x) => (
          <div key={x.id} className="row" style={{ alignItems: "center" }}>
            <div className="grow"><Chips items={[[x.name, "navy"], [x.language], [x.status === "needs_ocr" && "needs OCR (scanned PDF)", "red"]]} /></div>
            <button className="btn small danger" disabled={running} onClick={() => removeCv(x.id)}>Remove</button>
          </div>
        ))}
      </div>
    </>
  );
  const hosted = scan?.models.hosted ?? settings.models.hosted;
  return (
    <section className="card" aria-labelledby="s2">
      <div id="s2"><Step n={2} title="What you look for" done={done} /></div>
      <Seg label="Search" options={["cv", "keywords"]} value={mode} disabled={running} format={(o) => meta.search_modes[o]}
        onChange={(v) => save("profile", { search_mode: v })} />
      <p className="muted small">By my CV: offers are chosen with the research profile of Settings, then compared with your CV
        (CV match). By keywords: only offers whose title (then whose work, when the AI analysis is on) matches one of your keywords;
        no CV comparison.</p>
      {mode === "keywords" ? (
        <>
          <label className="field">Your keywords — one per line, or separated by commas (English or French)
            <textarea value={text} disabled={running} placeholder={"data scientist\ncomputer vision\ningénieur traitement du signal"}
              onChange={(e) => { setWords(e.target.value); save("profile", { my_keywords: splitKeywords(e.target.value) }); }}
              onBlur={() => setWords(null)} />
          </label>
          {kw.length > 0 ? (
            <div style={{ marginTop: 8 }}>
              <Chips items={kw.map((k) => [k, "blue"] as [string, string])} />
              <p className="muted small">A keyword also finds its translation (<i>computer vision</i> matches <i>vision par
                ordinateur</i>). Offers are not compared with a CV in this mode.</p>
            </div>
          ) : <p className="muted small">Add at least one keyword to start a search.</p>}
          <details><summary>Your CV (optional here: only for cover letters and applications)</summary>
            {cvBlock("PDF CV(s) — not used to rank the offers in a search by keywords")}
          </details>
        </>
      ) : cvBlock("Drop your PDF CV(s) here — compared with every relevant offer")}
      {hosted.length > 0 ? (
        <Toggle checked={hosted.every((h) => (c.cv_consent_providers ?? []).includes(h))}
          onChange={(v) => save("config", { cv_consent_providers: v ? hosted : [] })}
          label={`Allow sending my CV text to these hosted providers: ${hosted.join(", ")}`}
          help="Free plans may keep or use what they receive: check each provider's terms." />
      ) : !c.auto_models && meta.paid_providers.includes(c.model?.provider) ? (
        <Toggle checked={!!c.send_cv_remote_ok} onChange={(v) => save("config", { send_cv_remote_ok: v })}
          label={`Allow sending my CV text to ${c.model.provider} (hosted model)`} />
      ) : null}
      <Details applicant={settings.applicant} onSave={(patch) => save("applicant", patch)} />
    </section>
  );
}

const CIV = ["", "M.", "Mme"];
const AUTH: Record<string, string> = { "": "Not said (left to me)", yes: "Yes, I can work in France", visa: "No, I need a visa sponsorship" };
const AVAIL: Record<string, string> = { "": "Not said (left to me)", immediately: "Immediately", "1 month": "Within 1 month", "3 months": "Within 3 months" };
const LEVEL: Record<string, string> = { "": "Not said (left to me)", B2: "Professional (B2)", C1: "Fluent (C1)", C2: "Bilingual (C2)" };

function Details({ applicant: ap, onSave }: { applicant: Config; onSave: (p: Config) => void }) {
  const [show, setShow] = useState(false);
  const [accounts, setAccounts] = useState<{ website: string; email: string; password: string; state: string; since: string }[]>([]);
  useEffect(() => { api.get<typeof accounts>(`/accounts?show=${show}`).then(setAccounts).catch(() => {}); }, [show]);
  const set = (k: string) => (e: { target: { value: string } }) => {
    const patch: Config = { [k]: e.target.value };
    if (k === "first_name" || k === "last_name") {
      const f = k === "first_name" ? e.target.value : ap.first_name ?? "", l = k === "last_name" ? e.target.value : ap.last_name ?? "";
      patch.name = `${f} ${l}`.trim();
    }
    onSave(patch);
  };
  const inp = (k: string, label: string, ph = "", type = "text") => (
    <label className="field grow">{label}<input type={type} value={ap[k] ?? ""} placeholder={ph} onChange={set(k)} /></label>
  );
  const sel = (k: string, label: string, opts: Record<string, string>) => (
    <label className="field grow">{label}
      <select value={ap[k] ?? ""} onChange={set(k)}>{Object.entries(opts).map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select>
    </label>
  );
  return (
    <details>
      <summary>Your details (cover letters and application forms)</summary>
      <p className="muted small">Used to write your cover letters and to fill application forms ('Open and fill the application' on
        an offer). Kept only on this computer. No password is ever asked or stored: you sign in on each website yourself, once, in
        the application window.</p>
      <div className="row">
        <label className="field" style={{ width: 110 }}>Civility
          <select value={ap.civility ?? ""} onChange={set("civility")}>{CIV.map((x) => <option key={x} value={x}>{x || "—"}</option>)}</select>
        </label>
        {inp("first_name", "First name")}{inp("last_name", "Last name")}
      </div>
      <div className="row" style={{ marginTop: 10 }}>{inp("email", "Email", "", "email")}{inp("phone", "Phone")}</div>
      <label className="field" style={{ marginTop: 10 }}>Address (as on your letters)
        <textarea value={ap.address ?? ""} onChange={set("address")} style={{ minHeight: 60 }} /></label>
      <div className="row" style={{ marginTop: 10 }}>
        {inp("postal_code", "Postal code", "Empty: taken from the address")}{inp("city", "City", "Empty: taken from the address")}{inp("country", "Country")}
      </div>
      <div className="row" style={{ marginTop: 10 }}>{inp("linkedin", "LinkedIn URL")}{inp("website", "Website / GitHub")}</div>
      <div className="section">Education</div>
      <div className="row">{inp("degree", "Highest degree", "Master / Bac+5")}{inp("school", "School / university")}</div>
      <div className="row" style={{ marginTop: 10 }}>{inp("field_of_study", "Field of study")}{inp("grad_year", "Graduation year")}</div>
      <div className="section">Right to work and other questions</div>
      <div className="row">{sel("work_authorization", "Right to work in France", AUTH)}{inp("nationality", "Nationality")}</div>
      <div className="row" style={{ marginTop: 10 }}>{inp("how_heard", "How did you hear about the offer?")}</div>
      <div className="row" style={{ marginTop: 10 }}>
        {inp("salary_expectation", "Salary expectation (gross / year, €)", "38000")}{sel("availability", "Available to start", AVAIL)}{sel("english_level", "English level", LEVEL)}
      </div>
      <div className="row" style={{ marginTop: 10 }}>{inp("current_position", "Current or last position (job title)", "Machine Learning Engineer")}</div>
      <div className="section">Accounts on the websites</div>
      <p className="muted small">When a website asks you to sign in, the app signs in with the account it created there, or creates
        one: this email, and a strong password made for that website alone, kept only on this computer. Captchas and the codes sent by
        email stay yours.</p>
      {inp("account_email", "Email for website accounts", ap.email || "", "email")}
      <Toggle checked={!!ap.accept_terms} onChange={(v) => onSave({ accept_terms: v })}
        label="Let the app accept each website's terms of use (account forms) and tick the required consent box of application forms"
        help="Off: the app leaves every terms or consent box to you. A newsletter, job-alert or partner-offers box is never ticked, and no form is ever sent." />
      {accounts.length > 0 && (
        <>
          <Toggle checked={show} onChange={setShow} label="Show the passwords" />
          <div className="table-wrap"><table>
            <thead><tr><th>website</th><th>email</th><th>password</th><th>state</th><th>since</th></tr></thead>
            <tbody>{accounts.map((a) => <tr key={a.website}><td>{a.website}</td><td>{a.email}</td><td>{a.password}</td><td>{a.state}</td><td className="muted">{a.since}</td></tr>)}</tbody>
          </table></div>
        </>
      )}
    </details>
  );
}

// ------------------------------------------------------------------ step 3
function Analysis({ running }: { running: boolean }) {
  const { settings, meta, save, scan, refreshScan } = useShared();
  const { run, busy } = useAction();
  if (!settings || !meta || !scan) return <section className="card"><Step n={3} title="Analysis" done={false} /></section>;
  const c = settings.config, p = settings.profile, m = scan.models;
  const types: string[] = p.offer_types?.length ? p.offer_types : meta.job_types;
  const preset = meta.presets.includes(c.date_preset) ? c.date_preset : "Last 30 days";
  const sites = scan.summary.sites;
  const noWords = m.by_keywords && !m.keywords.length;
  const left = scan.unfinished;
  const act = async (path: string, ok?: string) => { if (await run(() => api.post(path), ok)) refreshScan(); };

  let models = "No AI call in this search. ";
  if (m.ai_used) models = c.auto_models
    ? `AI models: starts with ${m.first.provider} / ${m.first.model} and switches when a limit is reached — see Settings. `
    : `AI model ${c.model?.provider} / ${c.model?.model} — change it in Settings. `;
  const cvNote = m.by_keywords ? "Search by keywords: offers are ranked by your keywords, not compared with a CV."
    : scan.summary.cvs ? "" : "No CV yet: offers are ranked, but not compared with a CV.";

  return (
    <section className="card" aria-labelledby="s3">
      <div id="s3"><Step n={3} title="Analysis" done={!!scan.progress.finished && !running} /></div>
      <Pills label="I am looking for" options={Object.keys(meta.offer_types)} value={types} format={(o) => meta.offer_types[o]}
        onChange={(v) => save("profile", { offer_types: v.length ? v : types })} />
      <p className="muted small">Pick each type you want. An offer that does not state its contract is kept: its type shows as 'not stated'.</p>
      <div style={{ marginTop: 14 }}>
        <Seg label="Published within" options={meta.presets} value={preset} onChange={(v) => save("config", { date_preset: v })} />
      </div>
      <Toggle checked={!!c.respect_robots} disabled={running} onChange={(v) => save("config", { respect_robots: v })} label="Respect robots.txt"
        help="Off (default): no robots.txt rule is applied, only its list of sitemaps is used to find every offer. On: the app reads only the pages each website's robots.txt allows. Either way it reads one page per second per website and never gets around an anti-bot page, a login or a captcha." />
      <Toggle checked={c.hellowork_keywords ?? true} disabled={running} onChange={(v) => save("config", { hellowork_keywords: v })}
        label="Also search Hellowork with my keywords" help="Reads Hellowork's open page of each keyword (its 20 newest offers in France)." />
      {m.by_keywords && (
        <Toggle checked={!!c.ai_analysis_keywords} disabled={running} onChange={(v) => save("config", { ai_analysis_keywords: v })}
          label="Analyse each offer with AI"
          help="Off (default for a search by keywords): no AI call for the offers. Every offer whose title has one of your keywords, published in the date range and in France, is listed as it is ('not checked by AI'). On: the AI reads each offer (date, place, contract, relevance): one AI call per offer." />
      )}
      <Toggle checked={c.ai_readers ?? true} disabled={running} onChange={(v) => save("config", { ai_readers: v })}
        label="Use AI to read the websites the app cannot read alone"
        help="On (default): a website whose offers the app cannot read by itself is read by the AI page reader or the AI browser — a few AI calls per such website. Off: those websites are read without AI and may give fewer offers." />
      <p className="muted small">{models}{cvNote}</p>
      <Toggle checked={!!c.stats_with_scan} disabled={running} onChange={(v) => save("config", { stats_with_scan: v })}
        label="Update the statistics at the end of this scan"
        help={`Computes the Statistics page from the offers analysed in the last 15 days as soon as this scan's AI analysis ends. Unticked, every 15 days${scan.stats_due ? " (due now)" : ""}.`} />
      <div className="row" style={{ alignItems: "center", margin: "8px 0 14px" }}>
        <p className="muted small grow" style={{ margin: 0 }}>{scan.kept_offers
          ? <><b className="muted">{scan.kept_offers.toLocaleString()}</b> offers read in the last 24 h are kept: the next scan does not open their pages again, and the AI does not analyse them again (same search profile and CVs).</>
          : "No offer kept from the last 24 h: the next scan reads and analyses every offer."}</p>
        <button className="btn small" disabled={running || !scan.kept_offers || busy}
          onClick={() => confirm("Delete the kept offers and the current results?") && act("/recent-offers", "Kept offers deleted")}
          title="The websites, settings, CVs and statistics stay">Delete them</button>
      </div>
      {left && (
        <div className="card" style={{ background: "var(--surface-2)" }}>
          <b>The last scan did not finish</b> — {left.why || "stopped"}.
          <p className="muted small">Started {new Date(left.started + "Z").toLocaleString()}, range “{left.preset}”: {left.done} of {left.total} websites
            read{left.pending ? `, ${left.pending} offers waiting for the AI analysis` : ""}. <b>Resume</b> reads only the websites not read yet and
            analyses only the offers not analysed yet. <b>Start again</b> reads every website from the first one.</p>
          <div className="row">
            <button className="btn primary" disabled={busy} onClick={() => act("/scan/resume")}>▶ Resume</button>
            <button className="btn" disabled={busy} onClick={() => act("/scan/restart")}>↻ Start again</button>
          </div>
        </div>
      )}
      <div className="row">
        {!left && <button className="btn primary" disabled={running || !sites || noWords || busy} onClick={() => act("/scan/start")}>▶ Start</button>}
        <button className="btn" disabled={!running} onClick={() => act("/scan/stop", "Stopping after the current pages…")}>■ Stop</button>
        {!sites && <span className="muted small">Load the career websites first (step 1).</span>}
        {noWords && <span className="muted small">Add at least one keyword (step 2).</span>}
      </div>
      <Monitor />
    </section>
  );
}

// ------------------------------------------------------------------ the live search
const COVERAGE: [keyof Coverage, string, string][] = [["read", "read", "k-read"], ["partial", "partly read", "k-partial"],
  ["failed", "blocked or failed", "k-failed"], ["waiting", "not searched yet", "k-waiting"]];

function Monitor() {
  const { scan } = useShared();
  const [cov, setCov] = useState<Coverage[]>([]);
  const [probs, setProbs] = useState<{ rows: Problem[]; order: string[]; counts: Record<string, number> } | null>(null);
  const d = scan?.progress;
  const running = !!d?.running;
  useEffect(() => {
    const get = () => {
      api.get<{ files: Coverage[] }>("/coverage").then((r) => setCov(r.files)).catch(() => {});
      api.get<{ rows: Problem[]; order: string[]; counts: Record<string, number> }>("/problems").then(setProbs).catch(() => {});
    };
    get();
    if (!running) return;
    const t = window.setInterval(get, 4000);
    return () => window.clearInterval(t);
  }, [running, d?.finished]);
  if (!d || !(d.running || d.finished)) return null;
  const live = scan!.live;
  return (
    <div style={{ marginTop: 18 }}>
      {running && (
        <div className="status-line" role="status">
          <span className="spinner" aria-hidden />
          <span>Searching… {d.task} — websites {d.sources_done} / {d.sources_total}, {d.jobs} offers in the date range so far</span>
        </div>
      )}
      <Bar share={d.sources_done / (d.sources_total || 1)} label={`${d.task.charAt(0).toUpperCase()}${d.task.slice(1)} — websites ${d.sources_done} / ${d.sources_total}`} />
      {cov.map((r) => {
        const tot = r.total || 1, done = r.total - r.waiting;
        const head = !r.waiting ? `All ${r.total} websites searched` : `${done} / ${r.total} websites searched${running ? "" : ` — ${r.waiting} not reached`}`;
        return (
          <div className="cov" key={r.file}>
            <div className="cov-head"><b>{r.file}</b><span className="muted">{head}</span></div>
            <div className="cov-bar" role="img" aria-label={`${r.file}: ${head}`}>
              {COVERAGE.filter(([k]) => r[k]).map(([k, lab, cls]) => <span key={k} className={cls} style={{ width: `${(100 * (r[k] as number)) / tot}%` }} title={`${r[k]} ${lab}`} />)}
            </div>
            <div className="cov-legend">{COVERAGE.filter(([k]) => r[k]).map(([k, lab, cls]) =>
              <span key={k}><i className={cls} />{r[k] as number} {k !== "waiting" || running ? lab : "not reached"}</span>)}</div>
          </div>
        );
      })}
      {probs && probs.rows.length > 0 && (
        <details open={!running}>
          <summary>{probs.rows.length} website{probs.rows.length > 1 ? "s" : ""} did not work{running ? " so far" : ""}: {probs.order.map((k) => `${probs.counts[k]} ${k.toLowerCase()}`).join(", ")}</summary>
          {probs.order.map((k) => (
            <div key={k} style={{ marginBottom: 12 }}>
              <b>{k}</b> <span className="muted">{probs.counts[k]}</span>
              <ul style={{ margin: "6px 0", paddingLeft: 18 }}>
                {probs.rows.filter((r) => r.problem === k).map((r) => (
                  <li key={r.address} style={{ marginBottom: 6 }}>
                    <a href={r.address} target="_blank" rel="noopener noreferrer">{r.website}</a>{r.file && <span className="faint small"> · {r.file}</span>}
                    <div className="muted small">{r.why}</div><div className="small">→ {r.what_to_do}</div>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {!running && <a className="btn small" href="/api/problems.csv">Download this list (CSV)</a>}
        </details>
      )}
      {d.ai_total > 0 && (
        <Bar share={d.ai_done / d.ai_total}
          label={`AI reading offers ${d.ai_done} / ${d.ai_total}${running && d.task === "crawling" ? " — more arrive as the websites are read" : ""}`} />
      )}
      <div className="metrics">
        <div className="metric"><span>Offers in the date range</span><b>{d.jobs}</b></div>
        <div className="metric"><span>Too old (hidden)</span><b>{d.date_x}</b></div>
        <div className="metric"><span>Not France / not wanted</span><b>{d.loc_x + d.title_x}</b></div>
        <div className="metric"><span>Relevant</span><b>{d.relevant}</b></div>
      </div>
      {d.ai_msg && <div className="notice warn">{d.ai_msg}</div>}
      {d.type_x > 0 && !running && (
        <div className="notice warn">{d.type_x} {d.type_x === 1 ? "offer was" : "offers were"} set aside only because of their type
          (internship, PhD, apprenticeship...). If you want them too, select these types in 'I am looking for' and analyse again.</div>
      )}
      {!running && d.finished && <p><Link className="btn primary" to="/results">See the results →</Link></p>}
      {live && live.rows.length > 0 && <LiveOffers total={live.total} rows={live.rows} />}
      <details><summary>Activity log</summary><pre className="log">{scan!.log.join("\n") || "—"}</pre></details>
    </div>
  );
}

function LiveOffers({ total, rows }: { total: number; rows: Offer[] }) {
  return (
    <div style={{ margin: "14px 0" }}>
      <b>Offers found so far</b> — <span className="muted">{total.toLocaleString()}{total > rows.length ? ` (the ${rows.length} newest shown)` : ""}</span>
      <div className="table-wrap" style={{ maxHeight: 380, marginTop: 8 }}>
        <table>
          <thead><tr><th>title</th><th>company</th><th>location</th><th>published</th><th>link</th></tr></thead>
          <tbody>{rows.map((o) => (
            <tr key={o.uid}><td className="title">{o.title}</td><td>{o.company}</td><td className="muted">{o.location}</td>
              <td className="muted">{o.published || "not stated"}</td>
              <td>{o.link ? <a href={o.link} target="_blank" rel="noopener noreferrer">{o.link}</a> : "—"}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
