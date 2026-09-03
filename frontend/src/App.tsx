import { Link, Navigate, Route, Routes } from "react-router-dom";
import { RepositoriesRoute } from "./routes/RepositoriesRoute";
import { RunRoute } from "./routes/RunRoute";
import { CompareRoute } from "./routes/CompareRoute";
import { OpsRoute } from "./routes/OpsRoute";

export function App() {
  return (
    <div className="wrap">
      <header>
        <h1>ARCHON — Repository Intelligence</h1>
        <nav aria-label="primary">
          <Link to="/">Repositories</Link>
          {" · "}
          <Link to="/ops">Operations</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<RepositoriesRoute />} />
          <Route path="/runs/:id" element={<RunRoute />} />
          <Route path="/runs/:id/compare" element={<CompareRoute />} />
          <Route path="/ops" element={<OpsRoute />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
