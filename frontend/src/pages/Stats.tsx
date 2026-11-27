// Stats.tsx - the job market of your field, computed every 15 days from the offers the AI analysed.
import { useEffect, useState } from "react";
import { api, type Ranked, type Stats } from "../api";
import { Columns, HBar } from "../components/Charts";
import { Hero, useAction } from "../components/ui";

export default function StatsPage() {
  const { run, busy } = useAction();
  const [s, setS] = useState<Stats | null>(null);
  useEffect(() => { api.get<Stats>("/stats").then(setS); }, []);
  if (!s) return <span className="spinner" aria-label="Loading" />;
  const d = s.current, p = s.previous;
  const share = (rows: Ranked, key: string) => {
    const tot = rows.reduce((a, [, v]) => a + v, 0) || 1;
    return Math.round((100 * (new Map(rows).get(key) ?? 0)) / tot);
  };
  const delta = (a: number, b?: number) => (p && b !== undefined ? <em>{a - b >= 0 ? "+" : ""}{a - b} vs previous period</em> : null);
  const card = (title: string, body: React.ReactNode, note?: string) => (
    <div className="card"><h3>{title}</h3>{note && <p className="muted small">{note}</p>}{body}</div>
  );
  return (
    <>
      <Hero eyebrow="Market" title="Statistics" lead="The job market of your field: computed every 15 days from the offers the AI analysed." />
      <section className="card">
        <div className="row" style={{ alignItems: "center" }}>
          <p className="grow" style={{ margin: 0 }}>{d
            ? <><b>Period:</b> {s.period} · next computation on <b>{s.next}</b> · {s.kept.toLocaleString()} analysed offers kept in the history (6 months)</>
            : <>No statistics yet: they are computed from the offers the AI analyses (history: {s.kept.toLocaleString()} offers). Run a scan with AI analysis first.</>}</p>
          <button className="btn" disabled={!s.kept || busy} onClick={async () => { const r = await run(() => api.post<Stats>("/stats/compute")); if (r) setS(r); }}
            title="Statistics of the last 15 days, from the offers kept in the history">Compute now</button>
        </div>
        {s.due && d && <p className="muted small">15 days have passed: the next scan with AI analysis computes a new snapshot.</p>}
      </section>
      {d && (
        <>
          <div className="metrics">
            <div className="metric"><span>{d.base === "relevant" ? "Relevant offers" : "Analysed offers"}</span><b>{d.relevant || d.analysed}</b>{delta(d.relevant, p?.relevant)}</div>
            <div className="metric"><span>Companies hiring</span><b>{d.companies}</b>{delta(d.companies, p?.companies)}</div>
            <div className="metric"><span>Remote or hybrid</span><b>{share(d.remote, "remote") + share(d.remote, "hybrid")} %</b></div>
            <div className="metric"><span>Average CV match</span><b>{d.avg_match != null ? `${Math.round(d.avg_match)} / 100` : "—"}</b></div>
          </div>
          {d.base !== "relevant" && <div className="notice">No offer was judged relevant in this period: the figures cover every offer the AI analysed.</div>}
          <div className="grid2">
            {card("Most requested skills", <HBar rows={d.top_skills} label="skill" labels={s.labels} prev={p?.top_skills} />,
              "Number of offers asking for each skill, tool or method: what to put first on the CV.")}
            {card("Skills missing from the CV", <HBar rows={d.skill_gaps} label="requirement" labels={s.labels} prev={p?.skill_gaps} />,
              "Requirements of the offers that the CV does not show: what to learn or to make visible.")}
            {card("Companies hiring the most", <HBar rows={d.top_companies} label="company" labels={s.labels} prev={p?.top_companies} />)}
            {card("Cities", <HBar rows={d.cities} label="city" labels={s.labels} prev={p?.cities} />)}
          </div>
          {card("Offers per week", <Columns rows={d.weeks} label="Offers per week" />)}
          <div className="section">Profile of the offers</div>
          <div className="grid3">
            {card("Contract", <HBar rows={d.contracts} label="contract" labels={s.labels} />)}
            {card("Degree required", <HBar rows={d.degree} label="degree" labels={s.labels} />)}
            {card("Seniority", <HBar rows={d.seniority} label="seniority" labels={s.labels} />)}
          </div>
          <div className="grid2">
            {card("Languages required", <HBar rows={d.languages} label="language" labels={s.labels} />)}
            {card("Remote work", <HBar rows={d.remote} label="remote work" labels={s.labels} />)}
          </div>
          <div className="grid2">
            {card("Best CV matches", d.best_titles.length ? (
              <div className="table-wrap"><table><thead><tr><th>offer</th><th>company</th><th>CV match</th></tr></thead>
                <tbody>{d.best_titles.map(([t, c, m], i) => <tr key={i}><td>{t}</td><td>{c}</td><td className="num">{m}</td></tr>)}</tbody></table></div>
            ) : <p className="muted small">Upload a CV: the offers it matches best are listed here.</p>)}
            {card("Salaries stated", d.salaries.length ? (
              <div className="table-wrap"><table><thead><tr><th>offer</th><th>company</th><th>salary as written</th></tr></thead>
                <tbody>{d.salaries.map(([t, c, m], i) => <tr key={i}><td>{t}</td><td>{c}</td><td>{m}</td></tr>)}</tbody></table></div>
            ) : <p className="muted small">No offer of this period states a salary.</p>)}
          </div>
          <details><summary>Websites giving the most offers of your field</summary><HBar rows={d.websites} label="website" labels={s.labels} /></details>
        </>
      )}
    </>
  );
}
