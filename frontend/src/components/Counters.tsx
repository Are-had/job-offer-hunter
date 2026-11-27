// Counters.tsx - the header's live counters (websites, CVs, relevant, to check, applied).
import { useShared } from "../state";

export default function Counters() {
  const { scan } = useShared();
  const s = scan?.summary;
  if (!s) return null;
  const items: [number, string][] = [[s.sites, "websites"], [s.cvs, "CVs"], [s.relevant, "relevant offers"],
    [s.review, "to check"], [s.applied, "applied"]];
  return (
    <div className="stats">
      {items.map(([v, k]) => <div className="stat" key={k}><b>{v.toLocaleString()}</b><span>{k}</span></div>)}
    </div>
  );
}
