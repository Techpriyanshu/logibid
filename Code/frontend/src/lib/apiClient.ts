// Dev falls back to the local backend; production builds default to same-origin ('' => /api/... via reverse proxy).
// Set VITE_API_BASE_URL (non-secret URL only) to point a build at a different origin.
export const API_BASE: string =
  import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '');
