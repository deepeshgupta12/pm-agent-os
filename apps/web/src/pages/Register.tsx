// apps/web/src/pages/Register.tsx
import { useState } from "react";
import { Card, Stack, Text, TextInput, Button, Title } from "@mantine/core";
import { apiFetch } from "../api";

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

    setMsg(`Registered: ${res.data.email}. Now login.`);
  }

  return (
    <div style={{ maxWidth: 520, margin: "24px auto" }}>
      <Title order={2}>Register</Title>
      <Card withBorder mt="md">
        <form onSubmit={onRegister}>
          <Stack gap="sm">
            <TextInput
              label="Email"
              value={email}
              onChange={(e) => setEmail(e.currentTarget.value)}
              type="email"
              required
            />
            <TextInput
              label="Password (8–72 chars)"
              value={password}
              onChange={(e) => setPassword(e.currentTarget.value)}
              type="password"
              required
              minLength={8}
              maxLength={72}
            />
            <Button type="submit">Register</Button>
            {msg ? <Text>{msg}</Text> : null}
          </Stack>
        </form>
      </Card>
    </div>
  );
}