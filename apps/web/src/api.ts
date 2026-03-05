// apps/web/src/api.ts
// Commit 6: single source of truth for apiFetch.
// Any imports from "../api" will use the refresh/redirect behavior in apiClient.ts.
export { apiFetch } from "./apiClient";