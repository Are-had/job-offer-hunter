import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import "./styles.css";
import { ToastProvider } from "./components/ui";
import { SharedProvider, useShared } from "./state";
import SearchPage from "./pages/Search";
import ResultsPage from "./pages/Results";
import StatsPage from "./pages/Stats";
import QuotaPage from "./pages/Quota";
import SettingsPage from "./pages/Settings";

function TopBar() {
  const { scan } = useShared();
  const running = scan?.progress.running;
  return (
    <div className="topbar">
      <img src="/brand/logo.svg" alt="Job Offer Hunter" />
      <nav aria-label="Pages">
        <NavLink to="/" end>Search</NavLink>
        <NavLink to="/results">Results</NavLink>
        <NavLink to="/statistics">Statistics</NavLink>
        <NavLink to="/quota">AI quota</NavLink>
        <NavLink to="/settings">Settings</NavLink>
      </nav>
      <span className={`state state-chip${running ? " live" : ""}`}>
        {running ? <span className="spinner" aria-hidden /> : <span className="dot" />}
        {running ? "Search running" : "Idle"}
      </span>
    </div>
  );
}

function Shell() {
  const wide = useLocation().pathname.startsWith("/results");
  return (
    <>
      <TopBar />
      <main className={wide ? "wide" : ""}>
        <Routes>
          <Route path="/" element={<SearchPage />} />
          <Route path="/results" element={<ResultsPage />} />
          <Route path="/statistics" element={<StatsPage />} />
          <Route path="/quota" element={<QuotaPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <SharedProvider>
        <BrowserRouter>
          <Shell />
        </BrowserRouter>
      </SharedProvider>
    </ToastProvider>
  </StrictMode>,
);
