// apps/web/src/apiClient.ts
const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

let refreshInFlight: Promise<boolean> | null = null;

function redirectToLogin() {
  const path = window.location.pathname + window.location.search;
  if (!window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/register")) {
    const next = encodeURIComponent(path);
    window.location.href = `/login?next=${next}`;
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

async function parseErrorResponse(r: Response): Promise<string> {
  try {
    const contentType = r.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
      const j: any = await r.json();
      if (j && typeof j === "object") {
        if (typeof j.detail === "string") return j.detail;
        if (j.detail != null) return JSON.stringify(j.detail);
        return JSON.stringify(j);
      }
    }

    const text = await r.text();
    if (text && text.trim()) return text.trim();
  } catch {
    // ignore
  }
  return `HTTP ${r.status}`;
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

    if (r.status === 401) {
      const refreshed = await refreshOnce();
      if (refreshed) {
        r = await doFetch();
      }
    }

    if (!r.ok) {
      if (r.status === 401) redirectToLogin();
      const msg = await parseErrorResponse(r);
      return { ok: false, error: msg, status: r.status };
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