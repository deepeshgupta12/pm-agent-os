// apps/web/src/pages/Register.tsx
import { useState } from "react";
import { Button, Group, PasswordInput, Text, TextInput } from "@mantine/core";
import { apiFetch } from "../apiClient";
import GlassCard from "../components/Glass/GlassCard";
import GlassPage from "../components/Glass/GlassPage";

type UserOut = { id: string; email: string };

export default function Register() {
  const [email, setEmail] = useState("test@example.com");
  const [password, setPassword] = useState("Password123");
  const [msg, setMsg] = useState<string | null>(null);

  async function onRegister(e: React.FormEvent) {
    e.preventDefault();
    setMsg(null);

    const res = await apiFetch<UserOut>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      setMsg(`Register failed: ${res.status} ${res.error}`);
      return;
    }

    setMsg(`Registered: ${res.data.email}. Now sign in.`);
  }

  return (
    <GlassPage
      title="Create account"
      subtitle="Set up your account to access PM Agent OS."
      right={
        <Group>
          <Button variant="light" component="a" href="/login">
            Sign in
          </Button>
          <Button variant="light" component="a" href="/workspaces">
            Workspaces
          </Button>
        </Group>
      }
    >
      <div style={{ maxWidth: 560 }}>
        <GlassCard>
          <form onSubmit={onRegister}>
            <Group grow>
              <TextInput
                label="Email"
                value={email}
                onChange={(e) => setEmail(e.currentTarget.value)}
                type="email"
                required
              />
              <PasswordInput
                label="Password (8–72 chars)"
                value={password}
                onChange={(e) => setPassword(e.currentTarget.value)}
                required
                minLength={8}
                maxLength={72}
              />
            </Group>

            <Group mt="md">
              <Button type="submit">Create account</Button>
            </Group>

            {msg ? (
              <Text mt="sm" c={msg.startsWith("Register failed") ? "red" : undefined}>
                {msg}
              </Text>
            ) : null}
          </form>
        </GlassCard>
      </div>
    </GlassPage>
  );
}