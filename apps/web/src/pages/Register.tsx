import { useState } from "react";
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
      <h2>Register</h2>
      <form onSubmit={onRegister}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label>
            Email
            <input
              style={{ width: "100%", padding: 8 }}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              required
            />
          </label>
          <label>
            Password (8–72 chars)
            <input
              style={{ width: "100%", padding: 8 }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              required
              minLength={8}
              maxLength={72}
            />
          </label>
          <button type="submit">Register</button>
        </div>
      </form>
      {msg && <p style={{ marginTop: 12 }}>{msg}</p>}
    </div>
  );
}