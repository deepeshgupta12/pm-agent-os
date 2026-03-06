// apps/web/src/pages/Login.tsx
import { useMemo, useState } from "react";
import { Badge, Button, Divider, Group, List, PasswordInput, Text, TextInput } from "@mantine/core";
import { apiFetch } from "../apiClient";
import GlassCard from "../components/Glass/GlassCard";
import GlassPage from "../components/Glass/GlassPage";

type UserOut = { id: string; email: string };

export default function Login() {
  const [email, setEmail] = useState("test@example.com");
  const [password, setPassword] = useState("Password123");
  const [msg, setMsg] = useState<string | null>(null);

  const next = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get("next") || "/workspaces";
  }, []);

  async function onLogin(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);

    const res = await apiFetch<UserOut>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      setMsg(`Login failed: ${res.status} ${res.error}`);
      return;
    }

    window.location.href = next;
  }

  return (
    <GlassPage
      title="Sign in"
      subtitle="Use your account to access workspaces and runs."
      right={
        <Group>
          <Button variant="light" component="a" href="/register">
            Create account
          </Button>
          <Button variant="light" component="a" href="/workspaces">
            Workspaces
          </Button>
        </Group>
      }
    >
      <div className="auth-wrap">
        <div className="auth-grid">
          <GlassCard>
            <form onSubmit={onLogin}>
              <Group grow>
                <TextInput
                  label="Email"
                  value={email}
                  onChange={(e) => setEmail(e.currentTarget.value)}
                  type="email"
                  required
                />
                <PasswordInput
                  label="Password"
                  value={password}
                  onChange={(e) => setPassword(e.currentTarget.value)}
                  required
                  minLength={8}
                  maxLength={72}
                />
              </Group>

              <Group mt="md">
                <Button type="submit">Sign in</Button>
              </Group>

              {msg ? (
                <Text mt="sm" c={msg.startsWith("Login failed") ? "red" : undefined}>
                  {msg}
                </Text>
              ) : (
                <Text mt="sm" c="dimmed">
                  Tip: if you hit 401, refresh will auto-run once and retry.
                </Text>
              )}
            </form>
          </GlassCard>

          <GlassCard>
            <Group justify="space-between" align="flex-start">
              <Text fw={700}>What you get</Text>
              <Badge variant="light">Enterprise</Badge>
            </Group>

            <Text mt="xs" size="sm" c="dimmed">
              Calm workspace console for runs, approvals, and governance—designed for teams.
            </Text>

            <Divider my="md" />

            <List spacing="xs" size="sm">
              <List.Item>Workspace-scoped access control (admin / member / viewer)</List.Item>
              <List.Item>Approval workflows and audit log</List.Item>
              <List.Item>RAG console with evidence + regeneration loop</List.Item>
              <List.Item>Policy center for internal-only and allowlists</List.Item>
            </List>

            <Divider my="md" />

            <Text size="sm" c="dimmed">
              If your workspace is internal-only, connectors are blocked by policy.
            </Text>
          </GlassCard>
        </div>
      </div>
    </GlassPage>
  );
}