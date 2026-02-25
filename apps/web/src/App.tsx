import { AppShell, Group, Anchor, Text } from "@mantine/core";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import WorkspacesPage from "./pages/WorkspacesPage";
import WorkspaceDetailPage from "./pages/WorkspaceDetailPage";
import RunDetailPage from "./pages/RunDetailPage";
import ArtifactDetailPage from "./pages/ArtifactDetailPage";
import PipelinesPage from "./pages/PipelinesPage";
import PipelineRunDetailPage from "./pages/PipelineRunDetailPage";
import RunBuilderPage from "./pages/RunBuilderPage";
import DocsPage from "./pages/DocsPage";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Me from "./pages/Me";

function TopNav() {
  const loc = useLocation();
  return (
    <Group justify="space-between" px="md" py="sm">
      <Group gap="md">
        <Text fw={700}>PM Agent OS</Text>
        <Anchor component={Link} to="/workspaces">
          Workspaces
        </Anchor>
      </Group>
      <Group gap="md">
        <Anchor component={Link} to="/register">
          Register
        </Anchor>
        <Anchor component={Link} to="/login">
          Login
        </Anchor>
        <Anchor component={Link} to="/me">
          Me
        </Anchor>
        <Text size="xs" c="dimmed">
          {loc.pathname}
        </Text>
      </Group>
    </Group>
  );
}

export default function App() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <TopNav />
      </AppShell.Header>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<WorkspacesPage />} />

          {/* Auth */}
          <Route path="/register" element={<Register />} />
          <Route path="/login" element={<Login />} />
          <Route path="/me" element={<Me />} />

          {/* Platform */}
          <Route path="/workspaces" element={<WorkspacesPage />} />
          <Route path="/workspaces/:workspaceId" element={<WorkspaceDetailPage />} />

          {/* Run Builder (V0 close) */}
          <Route path="/run-builder/:workspaceId" element={<RunBuilderPage />} />

          {/* Docs (V0 close) */}
          <Route path="/workspaces/:workspaceId/docs" element={<DocsPage />} />

          {/* Pipelines */}
          <Route path="/workspaces/:workspaceId/pipelines" element={<PipelinesPage />} />
          <Route path="/pipelines/runs/:pipelineRunId" element={<PipelineRunDetailPage />} />

          {/* Runs/Artifacts */}
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/artifacts/:artifactId" element={<ArtifactDetailPage />} />

          {/* fallback */}
          <Route path="*" element={<WorkspacesPage />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  );
}