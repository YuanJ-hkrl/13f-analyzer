import { lazy, Suspense, useLayoutEffect, useRef, useState } from "react";
import { BrowserRouter, Routes, Route, NavLink, useLocation } from "react-router-dom";
import "./index.css";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const FundList = lazy(() => import("./pages/FundList"));
const FundDetail = lazy(() => import("./pages/FundDetail"));
const TradeCopyRankings = lazy(() => import("./pages/TradeCopyRankings"));
const TradeCopyFundDetail = lazy(() => import("./pages/TradeCopyFundDetail"));
const QuarterlyChanges = lazy(() => import("./pages/QuarterlyChanges"));
const Securities = lazy(() => import("./pages/Securities"));
const SecurityDetail = lazy(() => import("./pages/SecurityDetail"));
const StrategyBacktests = lazy(() => import("./pages/StrategyBacktests"));

const MAX_CACHED_PAGES = 12;

function PageRoutes() {
  const location = useLocation();
  const pageKey = `${location.pathname}${location.search}`;
  const [cachedPages, setCachedPages] = useState<string[]>([pageKey]);
  const scrollPositions = useRef(new Map<string, number>());
  const previousPage = useRef(pageKey);

  // Retain mounted route trees so navigating back restores component state and
  // does not repeat their mount-time API requests.
  if (!cachedPages.includes(pageKey)) {
    setCachedPages((pages) => [...pages, pageKey].slice(-MAX_CACHED_PAGES));
  }

  useLayoutEffect(() => {
    const previous = previousPage.current;
    if (previous !== pageKey) scrollPositions.current.set(previous, window.scrollY);
    window.scrollTo(0, scrollPositions.current.get(pageKey) ?? 0);
    previousPage.current = pageKey;
  }, [pageKey]);

  return <>{cachedPages.map((cachedKey) => {
    const active = cachedKey === pageKey;
    return <div key={cachedKey} hidden={!active} aria-hidden={!active}>
      <Suspense fallback={<div className="loading">Loading page...</div>}>
        <Routes location={cachedKey}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/funds" element={<FundList />} />
          <Route path="/funds/:id" element={<FundDetail />} />
          <Route path="/securities" element={<Securities />} />
          <Route path="/securities/:ticker" element={<SecurityDetail />} />
          <Route path="/trade-copy" element={<TradeCopyRankings />} />
          <Route path="/trade-copy/funds/:id" element={<TradeCopyFundDetail />} />
          <Route path="/quarterly-changes" element={<QuarterlyChanges />} />
          <Route path="/backtests" element={<StrategyBacktests />} />
        </Routes>
      </Suspense>
    </div>;
  })}</>;
}

function Layout() {
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-logo">
          13F<span>Analyzer</span>
        </div>
        <nav>
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/funds">Funds</NavLink>
          <NavLink to="/securities">Securities</NavLink>
          <NavLink to="/trade-copy">Trade Copy</NavLink>
          <NavLink to="/quarterly-changes">Quarterly Changes</NavLink>
          <NavLink to="/backtests">Backtests</NavLink>
        </nav>
      </aside>
      <main className="main-content">
        <PageRoutes />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}
