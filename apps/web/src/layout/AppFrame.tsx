// apps/web/src/layout/AppFrame.tsx
import { AppShell } from "@mantine/core";
import { Outlet, useLocation } from "react-router-dom";
import HeaderBar from "./HeaderBar";
import SideNav from "./SideNav";

const LAST_WS_KEY = "pmos:lastWorkspaceId";

function extractWorkspaceIdFromPath(pathname: string): string | null {
  const m1 = pathname.match(/^\/workspaces\/([0-9a-fA-F-]{36})(\/|$)/);
  if (m1?.[1]) return m1[1];

  const m2 = pathname.match(/^\/run-builder\/([0-9a-fA-F-]{36})(\/|$)/);
  if (m2?.[1]) return m2[1];

  return null;
}

function readLastWorkspaceId(): string | null {
  try {
    const v = window.localStorage.getItem(LAST_WS_KEY);
    if (!v) return null;
    return /^[0-9a-fA-F-]{36}$/.test(v) ? v : null;
  } catch {
    return null;
  }
}

function writeLastWorkspaceId(wid: string) {
  try {
    window.localStorage.setItem(LAST_WS_KEY, wid);
  } catch {
    // ignore
  }
}

export default function AppFrame() {
  const loc = useLocation();
  const routeWorkspaceId = extractWorkspaceIdFromPath(loc.pathname);

  const activeWorkspaceId = routeWorkspaceId || readLastWorkspaceId();

  if (routeWorkspaceId) {
    writeLastWorkspaceId(routeWorkspaceId);
  }

  return (
    <div className="app-shell-bg">
      <AppShell header={{ height: 56 }} navbar={{ width: 260, breakpoint: "sm" }} padding={0}>
        <AppShell.Header>
          <HeaderBar workspaceId={activeWorkspaceId} routeWorkspaceId={routeWorkspaceId} />
        </AppShell.Header>

        <AppShell.Navbar p={0}>
          <SideNav workspaceId={activeWorkspaceId} />
        </AppShell.Navbar>

        <AppShell.Main>
          <div className="page-wrap">
            <Outlet />
          </div>
        </AppShell.Main>
      </AppShell>
    </div>
  );
}