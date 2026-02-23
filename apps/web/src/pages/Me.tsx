import { useEffect, useState } from "react";
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
    <div style={{ maxWidth: 520, margin: "24px auto" }}>
      <h2>Me</h2>

      <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
        <button onClick={loadMe}>Refresh</button>
        <button onClick={logout}>Logout</button>
      </div>

      {user ? (
        <pre>{JSON.stringify(user, null, 2)}</pre>
      ) : (
        <p>{msg ?? "Loading..."}</p>
      )}
    </div>
  );
}