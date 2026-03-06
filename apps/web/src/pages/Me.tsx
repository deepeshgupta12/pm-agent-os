// apps/web/src/pages/Me.tsx
import { useEffect, useState } from "react";
import { Button, Group, Text } from "@mantine/core";
import { apiFetch } from "../apiClient";
import GlassCard from "../components/Glass/GlassCard";
import GlassPage from "../components/Glass/GlassPage";

type UserOut = { id: string; email: string };

export default function Me() {
  const [user, setUser] = useState<UserOut | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function loadMe() {
    setMsg(null);
    const res = await apiFetch<UserOut>("/auth/me", { method: "GET" });
    if (!res.ok) {
      setUser(null);
      setMsg(`Not signed in: ${res.status} ${res.error}`);
      return;
    }
    setUser(res.data);
    setMsg(null);
  }

  async function logout() {
    setMsg(null);
    const res = await apiFetch<{ ok: boolean }>("/auth/logout", { method: "POST" });
    if (!res.ok) {
      setMsg(`Logout failed: ${res.status} ${res.error}`);
      return;
    }
    setUser(null);
    setMsg("Signed out.");
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadMe();
  }, []);

  return (
    <GlassPage
      title="Account"
      subtitle="Session and identity."
      right={
        <Group>
          <Button variant="light" component="a" href="/workspaces">
            Workspaces
          </Button>
          <Button variant="light" onClick={loadMe}>
            Refresh
          </Button>
        </Group>
      }
    >
      <div style={{ maxWidth: 720 }}>
        <GlassCard>
          <Group>
            <Button variant="light" onClick={loadMe}>
              Refresh
            </Button>
            <Button color="red" variant="light" onClick={logout}>
              Sign out
            </Button>
          </Group>

          {user ? (
            <pre style={{ marginTop: 12, marginBottom: 0, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(user, null, 2)}
            </pre>
          ) : (
            <Text mt="sm" c={msg?.startsWith("Logout failed") ? "red" : "dimmed"}>
              {msg ?? "Loading…"}
            </Text>
          )}
        </GlassCard>
      </div>
    </GlassPage>
  );
}