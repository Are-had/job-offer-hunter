// api.ts - the calls to the backend (FastAPI, /api) and the shapes of what it answers.

export type Dict<T = string> = Record<string, T>;

export interface Summary {
  sites: number; cvs: number; relevant: number; review: number; applied: number; running: boolean;
}

export interface Offer {
  uid: string; title: string; company: string; location: string; published: string; online_since: string;
  type: string; topics: string; relevance: number | null; match: number | null; link: string | null;
  status: string; applied: boolean; comment: string; not_checked: boolean;
}

export interface FillStatus {
  state: string; message: string; filled: string[]; steps: string[]; site: string;
  account: { email: string; state: string } | null; letter: string; letter_note: string;
}

export interface Letter { id: number; version: number; cv: string; tex: string; pdf: boolean }

export interface OfferDetail {
  uid: string; title: string; company: string; status: string; status_label: string; type: string;
  research_subject: boolean; language: string; topics: string[]; link: string | null; apply_page: string | null;
  published: string; online_since: string; date_source: string; date_text: string; location: string;
  location_evidence: string; relevance: number | null; reasoning: string; ai_model: string; first_reading: string;
  review_flags: string[]; reason: string; description: string;
  match: { cv: string; score: number; advice: string; missing: string; not_shown: string }[];
  best_cv: string; cvs: string[]; letter: Letter | null; mark: { state: string; note: string };
  can_fill: boolean; fill_why: string; fill: FillStatus | null;
}

export interface Mark { uid: string; state: string; title: string; company: string; note: string; date: string; link: string | null }

export interface Progress {
  running: boolean; task: string; sources_done: number; sources_total: number; jobs: number; date_x: number;
  loc_x: number; title_x: number; type_x: number; ai_done: number; ai_total: number; relevant: number;
  ai_msg: string; finished: string | null; started: string | null;
}

export interface Models {
  ai_used: boolean; by_keywords: boolean; first: { provider: string; model: string }; order: string[];
  hosted: string[]; keywords: string[];
}

export interface ScanState {
  progress: Progress; log: string[]; kept_offers: number; stats_due: boolean; models: Models; summary: Summary;
  unfinished: null | { started: string; why: string; done: number; pending: number; total: number; preset: string };
  live?: { total: number; rows: Offer[] };
}

export interface Source {
  id: number; website: string; file: string; url: string; read_by: string; status: string; offers: number;
  on_lists: number; since_last_scan: string; note: string;
}

export interface Coverage { file: string; total: number; read: number; partial: number; failed: number; waiting: number }

export interface Problem { problem: string; website: string; why: string; what_to_do: string; file: string; address: string }

export interface Cv { id: number; name: string; language: string; status: string }

export interface Meta {
  offer_types: Dict; job_types: string[]; presets: string[]; search_modes: Dict; providers: string[];
  provider_labels: Dict; paid_providers: string[]; type_labels: Dict; kind_labels: Dict; status_labels: Dict;
}

// the settings are free-form dictionaries saved as they are (config, profile, applicant)
export type Config = Dict<any>;
export interface Settings { config: Config; profile: Config; applicant: Config; models: Models }

export interface KeyState { saved: boolean; masked: string; label: string }

export interface QuotaBar { model?: string; share: number; text: string; state?: string }
export interface QuotaCard { slot: string; provider: string; nth: string; masked: string; key_bar: QuotaBar | null; models: QuotaBar[] }

export type Ranked = [string, number][];
export interface Snapshot {
  base: string; relevant: number; analysed: number; companies: number; avg_match: number | null;
  remote: Ranked; top_skills: Ranked; skill_gaps: Ranked; top_companies: Ranked; cities: Ranked; weeks: Ranked;
  contracts: Ranked; degree: Ranked; seniority: Ranked; languages: Ranked; websites: Ranked;
  best_titles: [string, string, number][]; salaries: [string, string, string][];
}
export interface Stats {
  current: Snapshot | null; previous: Snapshot | null; kept: number; due: boolean; period?: string; next?: string; labels: Dict;
}

export class ApiError extends Error {}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Dict)["Content-Type"] = "application/json";
  }
  const r = await fetch(`/api${path}`, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not JSON: the status says it */ }
    throw new ApiError(msg);
  }
  return r.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => call<T>("GET", path),
  post: <T>(path: string, body?: unknown) => call<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: unknown) => call<T>("PUT", path, body),
  del: <T>(path: string) => call<T>("DELETE", path),
  upload: <T>(path: string, files: FileList | File[], field = "files") => {
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append(field, f));
    return call<T>("POST", path, fd);
  },
};
