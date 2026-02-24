const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

let refreshInFlight: Promise<boolean> | null = null;

function redirectToLogin() {
  const path = window.location.pathname;
  if (!path.startsWith("/login") && !path.startsWith("/register")) {
    window.location.href = "/login";
  }
}

async function tryRefresh(): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    return r.ok;
  } catch {
    return false;
  }
}

async function refreshOnce(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const ok = await tryRefresh();
      return ok;
    })().finally(() => {
      refreshInFlight = null;
    }) as Promise<boolean>;
  }
  return refreshInFlight;
}

export async function apiFetch<T>(
  path: string,
  opts?: RequestInit
): Promise<{ ok: true; data: T } | { ok: false; error: string; status: number }> {
  const doFetch = async (): Promise<Response> =>
    fetch(`${API_BASE}${path}`, {
      ...opts,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(opts?.headers ?? {}),
      },
    });

  try {
    let r = await doFetch();

    // If unauthorized, attempt refresh once then retry request once
    if (r.status === 401) {
      const refreshed = await refreshOnce();
      if (refreshed) {
        r = await doFetch();
      }
    }

    if (!r.ok) {
      if (r.status === 401) redirectToLogin();
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