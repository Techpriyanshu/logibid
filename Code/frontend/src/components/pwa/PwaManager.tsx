import { useEffect, useState } from 'react';
import { useRegisterSW } from 'virtual:pwa-register/react';
import { Download, RefreshCw, Share, WifiOff, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { startBackendStatusMonitor, useBackendStatus } from '@/store/backendStatus';

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

const INSTALL_DISMISSED_KEY = 'logibid.pwa.installDismissed';

function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function isIosSafari(): boolean {
  const ua = navigator.userAgent;
  const isIos = /iPad|iPhone|iPod/.test(ua) || (ua.includes('Mac') && navigator.maxTouchPoints > 1);
  return isIos && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
}

export function PwaManager() {
  const reachable = useBackendStatus((s) => s.reachable);
  const [installEvent, setInstallEvent] = useState<BeforeInstallPromptEvent | null>(null);
  const [showIosHelp, setShowIosHelp] = useState(false);
  const [dismissed, setDismissed] = useState(() => localStorage.getItem(INSTALL_DISMISSED_KEY) === '1');

  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_url, registration) {
      // Look for a new release hourly and whenever the app is reopened.
      if (!registration) return;
      setInterval(() => void registration.update(), 60 * 60 * 1000);
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') void registration.update();
      });
    },
  });

  useEffect(() => {
    startBackendStatusMonitor();
  }, []);

  useEffect(() => {
    if (isStandalone()) return;
    const onPrompt = (e: Event) => {
      e.preventDefault();
      setInstallEvent(e as BeforeInstallPromptEvent);
    };
    const onInstalled = () => setInstallEvent(null);
    window.addEventListener('beforeinstallprompt', onPrompt);
    window.addEventListener('appinstalled', onInstalled);
    if (isIosSafari()) setShowIosHelp(true);
    return () => {
      window.removeEventListener('beforeinstallprompt', onPrompt);
      window.removeEventListener('appinstalled', onInstalled);
    };
  }, []);

  const dismissInstall = () => {
    localStorage.setItem(INSTALL_DISMISSED_KEY, '1');
    setDismissed(true);
  };

  const install = async () => {
    if (!installEvent) return;
    await installEvent.prompt();
    await installEvent.userChoice;
    setInstallEvent(null);
  };

  const showInstall = !dismissed && !isStandalone() && (installEvent !== null || showIosHelp);

  return (
    <>
      {!reachable && (
        <div
          role="alert"
          className="fixed top-0 inset-x-0 z-[100] flex items-center justify-center gap-2 bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground"
        >
          <WifiOff className="h-4 w-4 shrink-0" />
          Connection to the server lost. Data on screen may be out of date and bidding actions are disabled.
        </div>
      )}

      {needRefresh && (
        <div className="fixed bottom-4 inset-x-4 z-[100] mx-auto flex max-w-md items-center gap-3 rounded-lg border border-border bg-card p-4 shadow-lg">
          <RefreshCw className="h-5 w-5 shrink-0 text-primary" />
          <p className="flex-1 text-sm text-foreground">A new version of LogiBid is available.</p>
          <Button size="sm" onClick={() => void updateServiceWorker(true)}>
            Update
          </Button>
          <button aria-label="Later" onClick={() => setNeedRefresh(false)} className="p-1 text-muted-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {showInstall && !needRefresh && (
        <div className="fixed bottom-4 inset-x-4 z-[90] mx-auto flex max-w-md items-start gap-3 rounded-lg border border-border bg-card p-4 shadow-lg">
          {installEvent ? (
            <Download className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          ) : (
            <Share className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
          )}
          <div className="flex-1 text-sm text-foreground">
            <p className="font-medium">Install LogiBid</p>
            {installEvent ? (
              <p className="text-muted-foreground">Add LogiBid to your home screen for quick access.</p>
            ) : (
              <p className="text-muted-foreground">
                Tap the Share button in Safari, then choose &quot;Add to Home Screen&quot;.
              </p>
            )}
          </div>
          {installEvent && (
            <Button size="sm" onClick={() => void install()}>
              Install
            </Button>
          )}
          <button aria-label="Dismiss" onClick={dismissInstall} className="p-1 text-muted-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}
    </>
  );
}
