import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import FundList from "./pages/FundList";
import FundDetail from "./pages/FundDetail";
import TradeCopyRankings from "./pages/TradeCopyRankings";
import TradeCopyFundDetail from "./pages/TradeCopyFundDetail";
import QuarterlyChanges from "./pages/QuarterlyChanges";
import Securities from "./pages/Securities";
import SecurityDetail from "./pages/SecurityDetail";
import "./index.css";

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
        </nav>
      </aside>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/funds" element={<FundList />} />
          <Route path="/funds/:id" element={<FundDetail />} />
          <Route path="/securities" element={<Securities />} />
          <Route path="/securities/:ticker" element={<SecurityDetail />} />
          <Route path="/trade-copy" element={<TradeCopyRankings />} />
          <Route path="/trade-copy/funds/:id" element={<TradeCopyFundDetail />} />
          <Route path="/quarterly-changes" element={<QuarterlyChanges />} />
        </Routes>
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
