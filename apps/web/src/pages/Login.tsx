import { useState } from "react";
import { apiFetch } from "../api";

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
      <h2>Login</h2>
      <form onSubmit={onLogin}>
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
            Password
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
          <button type="submit">Login</button>
        </div>
      </form>
      {msg && <p style={{ marginTop: 12 }}>{msg}</p>}
    </div>
  );
}