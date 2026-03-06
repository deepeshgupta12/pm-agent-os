// apps/web/src/layout/AppFrame.tsx
import { AppShell } from "@mantine/core";
import { Outlet, useLocation } from "react-router-dom";
import HeaderBar from "./HeaderBar";
import SideNav from "./SideNav";

function extractWorkspaceIdFromPath(pathname: string): string | null {
  // /workspaces/:workspaceId/...
  const m1 = pathname.match(/^\/workspaces\/([0-9a-fA-F-]{36})(\/|$)/);
  if (m1?.[1]) return m1[1];

  // /run-builder/:workspaceId
  const m2 = pathname.match(/^\/run-builder\/([0-9a-fA-F-]{36})(\/|$)/);
  if (m2?.[1]) return m2[1];

  return null;
}

export default function AppFrame() {
  const loc = useLocation();
  const workspaceId = extractWorkspaceIdFromPath(loc.pathname);

  return (
    <div className="app-shell-bg">
      <AppShell
        header={{ height: 56 }}
        navbar={{ width: 260, breakpoint: "sm" }}
        padding={0}
      >
        <AppShell.Header>
          <HeaderBar workspaceId={workspaceId} />
        </AppShell.Header>

        <AppShell.Navbar p={0}>
          <SideNav workspaceId={workspaceId} />
        </AppShell.Navbar>

        <AppShell.Main>
          <Outlet />
        </AppShell.Main>
      </AppShell>
    </div>
  );
}