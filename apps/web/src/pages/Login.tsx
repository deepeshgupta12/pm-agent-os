// apps/web/src/pages/Login.tsx
import { useState } from "react";
import { Card, Stack, Text, TextInput, Button, Title } from "@mantine/core";
import { apiFetch } from "../apiClient";

type UserOut = { id: string; email: string };

export default function Login() {
  const [email, setEmail] = useState("test@example.com");
  const [password, setPassword] = useState("Password123");
  const [msg, setMsg] = useState<string | null>(null);

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

    setMsg(`Logged in as ${res.data.email}`);
  }

  return (
    <div style={{ maxWidth: 520, margin: "24px auto" }}>
      <Title order={2}>Login</Title>
      <Card withBorder mt="md">
        <form onSubmit={onLogin}>
          <Stack gap="sm">
            <TextInput
              label="Email"
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              type="email"
              required
            />
            <TextInput
              label="Password"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              type="password"
              required
              minLength={8}
              maxLength={72}
            />
            <Button type="submit">Login</Button>
            {msg ? <Text>{msg}</Text> : null}
          </Stack>
        </form>
      </Card>
    </div>
  );
}