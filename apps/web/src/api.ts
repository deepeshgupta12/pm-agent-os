const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

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
      const text = await r.text();
      return { ok: false, error: text || `HTTP ${r.status}`, status: r.status };
    }

    const data = (await r.json()) as T;
    return { ok: true, data };
  } catch (e: any) {
    return { ok: false, error: e?.message ?? "Network error", status: 0 };
  }
}