// Charts.tsx - the statistics' charts, in plain HTML: one series, one colour (validated on the dark card surface),
// thin bars with 4px rounded data-ends, the value written at the bar's end, a hover tooltip, and a hidden table for
// screen readers. A single series needs no legend: the card's title names it.
import { useState } from "react";
import type { Ranked } from "../api";

export function HBar({ rows, label, labels, prev }: { rows: Ranked; label: string; labels: Record<string, string>; prev?: Ranked | null }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!rows?.length) return <p className="muted small">No data in this period yet.</p>;
  const max = Math.max(...rows.map(([, v]) => v), 1);
  const before = new Map(prev ?? []);
  const name = (k: string) => labels[k] ?? k;
  return (
    <>
      <div className="hbar" aria-hidden>
        {rows.map(([k, v], i) => (
          <div key={k} style={{ display: "contents" }}>
            <div className="lab" title={name(k)}>{name(k)}</div>
            <div className="barcell" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <div className="bar" style={{ width: `${(100 * v) / max}%` }} />
              <span className="val">{v}</span>
              {hover === i && (
                <div className="tip" style={{ left: `${Math.min(80, (50 * v) / max + 10)}%` }}>
                  <b>{name(k)}</b> · {v} offers{prev ? ` · previous period ${before.get(k) ?? 0}` : ""}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <table className="sr-only">
        <caption>{label}</caption>
        <thead><tr><th>{label}</th><th>offers</th>{prev && <th>previous period</th>}</tr></thead>
        <tbody>{rows.map(([k, v]) => <tr key={k}><td>{name(k)}</td><td>{v}</td>{prev && <td>{before.get(k) ?? 0}</td>}</tr>)}</tbody>
      </table>
    </>
  );
}

export function Columns({ rows, label }: { rows: Ranked; label: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!rows?.length) return <p className="muted small">No data in this period yet.</p>;
  const max = Math.max(...rows.map(([, v]) => v), 1);
  return (
    <>
      <div className="cols" aria-hidden>
        {rows.map(([k, v], i) => (
          <div key={k} className="col" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            {hover === i && <div className="tip" style={{ top: `${100 - (100 * v) / max}%` }}><b>{k}</b> · {v} offers</div>}
            <div className="bar" style={{ height: `${(100 * v) / max}%` }} />
          </div>
        ))}
      </div>
      <div className="cols-x" aria-hidden>{rows.map(([k]) => <span key={k} title={k}>{k}</span>)}</div>
      <table className="sr-only">
        <caption>{label}</caption>
        <thead><tr><th>week</th><th>offers</th></tr></thead>
        <tbody>{rows.map(([k, v]) => <tr key={k}><td>{k}</td><td>{v}</td></tr>)}</tbody>
      </table>
    </>
  );
}
