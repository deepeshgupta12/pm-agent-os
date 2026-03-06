// apps/web/src/App.tsx
import { Navigate, Route, Routes } from "react-router-dom";

import AppFrame from "./layout/AppFrame";

// Pages
import WorkspacesPage from "./pages/WorkspacesPage";
import WorkspaceDetailPage from "./pages/WorkspaceDetailPage";
import WorkspaceOverviewPage from "./pages/WorkspaceOverviewPage";
import RunDetailPage from "./pages/RunDetailPage";
import ArtifactDetailPage from "./pages/ArtifactDetailPage";
import PipelinesPage from "./pages/PipelinesPage";
import PipelineRunDetailPage from "./pages/PipelineRunDetailPage";
import RunBuilderPage from "./pages/RunBuilderPage";
import DocsPage from "./pages/DocsPage";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Me from "./pages/Me";
import ActionCenterPage from "./pages/ActionCenterPage";
import SchedulesPage from "./pages/SchedulesPage";
import GovernancePage from "./pages/GovernancePage";
import AgentBuilderPage from "./pages/AgentBuilderPage";
import PolicyCenterPage from "./pages/PolicyCenterPage";

export default function App() {
  return (
    <Routes>
      {/* Auth (no shell) */}
      <Route path="/register" element={<Register />} />
      <Route path="/login" element={<Login />} />
      <Route path="/me" element={<Me />} />

      {/* App shell */}
      <Route element={<AppFrame />}>
        <Route path="/" element={<Navigate to="/workspaces" replace />} />

        <Route path="/workspaces" element={<WorkspacesPage />} />

        {/* Commit 11: workspace overview is default landing */}
        <Route path="/workspaces/:workspaceId" element={<WorkspaceOverviewPage />} />

        {/* Keep old page reachable */}
        <Route path="/workspaces/:workspaceId/_legacy" element={<WorkspaceDetailPage />} />

        <Route path="/workspaces/:workspaceId/actions" element={<ActionCenterPage />} />
        <Route path="/workspaces/:workspaceId/schedules" element={<SchedulesPage />} />
        <Route path="/workspaces/:workspaceId/policy" element={<PolicyCenterPage />} />
        <Route path="/workspaces/:workspaceId/governance" element={<GovernancePage />} />
        <Route path="/workspaces/:workspaceId/agent-builder" element={<AgentBuilderPage />} />

        <Route path="/run-builder/:workspaceId" element={<RunBuilderPage />} />
        <Route path="/workspaces/:workspaceId/docs" element={<DocsPage />} />

        <Route path="/workspaces/:workspaceId/pipelines" element={<PipelinesPage />} />
        <Route path="/pipelines/runs/:pipelineRunId" element={<PipelineRunDetailPage />} />

        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route path="/artifacts/:artifactId" element={<ArtifactDetailPage />} />

        <Route path="*" element={<Navigate to="/workspaces" replace />} />
      </Route>
    </Routes>
  );
}