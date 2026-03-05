// apps/web/src/pages/Me.tsx
import { useEffect, useState } from "react";
import { Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { apiFetch } from "../api";

type UserOut = { id: string; email: string };

export default function Me() {
  const [user, setUser] = useState<UserOut | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  async function loadMe() {
    setMsg(null);
    const res = await apiFetch<UserOut>("/auth/me", { method: "GET" });
    if (!res.ok) {
      setUser(null);
      setMsg(`Not logged in: ${res.status} ${res.error}`);
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
    setMsg("Logged out.");
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadMe();
  }, []);

  return (
    <div style={{ maxWidth: 720, margin: "24px auto" }}>
      <Title order={2}>Me</Title>

      <Card withBorder mt="md">
        <Stack gap="sm">
          <Group>
            <Button variant="light" onClick={loadMe}>
              Refresh
            </Button>
            <Button color="red" variant="light" onClick={logout}>
              Logout
            </Button>
          </Group>

          {user ? (
            <pre style={{ margin: 0 }}>{JSON.stringify(user, null, 2)}</pre>
          ) : (
            <Text>{msg ?? "Loading..."}</Text>
          )}
        </Stack>
      </Card>
    </div>
  );
}