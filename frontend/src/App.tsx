import { Navigate, Route, Routes } from "react-router-dom";
import { RepositoriesRoute } from "./routes/RepositoriesRoute";
import { RunRoute } from "./routes/RunRoute";
import { CompareRoute } from "./routes/CompareRoute";

export function App() {
  return (
    <div className="wrap">
      <header>
        <h1>ARCHON — Repository Intelligence</h1>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<RepositoriesRoute />} />
          <Route path="/runs/:id" element={<RunRoute />} />
          <Route path="/runs/:id/compare" element={<CompareRoute />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}
