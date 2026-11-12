import { create } from 'zustand';
import { API_BASE } from '@/lib/apiClient';

const POLL_MS = 10_000;
const TIMEOUT_MS = 8_000;
const FAILURES_BEFORE_LOST = 2;
let failures = 0;

interface BackendStatusState {
  reachable: boolean;
  lastCheckedAt: number | null;
  check: () => Promise<void>;
}

// Any HTTP response (even 4xx/5xx) proves the server is reachable; only network failure/timeout counts as lost.
export const useBackendStatus = create<BackendStatusState>((set) => ({
  reachable: true,
  lastCheckedAt: null,
  check: async () => {
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      set({ reachable: false, lastCheckedAt: Date.now() });
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      await fetch(`${API_BASE}/api/health`, { cache: 'no-store', signal: controller.signal });
      failures = 0;
      set({ reachable: true, lastCheckedAt: Date.now() });
    } catch {
      // Require consecutive failures so one slow response under load doesn't flash a false alarm.
      failures += 1;
      if (failures >= FAILURES_BEFORE_LOST) set({ reachable: false, lastCheckedAt: Date.now() });
    } finally {
      clearTimeout(timer);
    }
  },
}));

let started = false;

export function startBackendStatusMonitor(): void {
  if (started) return;
  started = true;
  const { check } = useBackendStatus.getState();
  void check();
  setInterval(() => void check(), POLL_MS);
  window.addEventListener('online', () => void check());
  window.addEventListener('offline', () => void check());
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void check();
  });
}
