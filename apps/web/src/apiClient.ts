const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

function redirectToLoginIfNeeded(status: number) {
  if (status === 401) {
    // Avoid infinite loops on login/register pages
    const path = window.location.pathname;
    if (!path.startsWith("/login") && !path.startsWith("/register")) {
      window.location.href = "/login";
    }
  }
}

export async function apiFetch<T>(
  path: string,
  opts?: RequestInit
): Promise<{ ok: true; data: T } | { ok: false; error: string; status: number }> {
  try {
    const r = await fetch(`${API_BASE}${path}`, {
      ...opts,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(opts?.headers ?? {}),
      },
    });

    if (!r.ok) {
      redirectToLoginIfNeeded(r.status);
      const text = await r.text();
      return { ok: false, error: text || `HTTP ${r.status}`, status: r.status };
    }

    const contentType = r.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      return { ok: true, data: {} as T };
    }

    const data = (await r.json()) as T;
    return { ok: true, data };
  } catch (e: any) {
    return { ok: false, error: e?.message ?? "Network error", status: 0 };
  }
}