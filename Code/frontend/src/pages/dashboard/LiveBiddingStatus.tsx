import { Activity, Trophy, AlertCircle, Pause, Square, Play, RefreshCw, Monitor } from 'lucide-react';
import { useDataStore } from '@/store/dataStore';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { toast } from 'sonner';
import { useLiveBids, useLiveBidActions } from '@/hooks/useLiveBids';
import { getActiveBidJobId, setActiveBidJobId, debugLog, type LiveBid } from '@/api/liveBids';
import { useState } from 'react';
import { API_BASE } from '@/lib/apiClient';

const STATUS_LABELS: Record<string, string> = {
  monitoring: 'Monitoring',
  bid_appeared: 'Bid Appeared',
  planning: 'Planning',
  ready: 'Ready',
  executing: 'Executing',
  waiting_rank: 'Waiting Rank',
  completed: 'Completed',
  won: 'Won',
  paused: 'Paused',
  stopped: 'Stopped',
  orphaned: 'Orphaned',
};

function formatStatus(status: string): string {
  return STATUS_LABELS[status] ?? status.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function formatWonTime(iso: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function isTerminal(bid: LiveBid): boolean {
  return bid.status === 'won' || bid.status === 'completed' || bid.status === 'stopped' || bid.status === 'orphaned';
}

function canPause(bid: LiveBid): boolean {
  return bid.user_control === 'active' && bid.status !== 'won' && bid.status !== 'completed' && bid.status !== 'stopped';
}

function canResume(bid: LiveBid): boolean {
  return bid.user_control === 'paused' && !isTerminal(bid);
}

function canStop(bid: LiveBid): boolean {
  return bid.user_control !== 'stopped' && bid.status !== 'won';
}

export default function LiveBiddingStatus() {
  const { currentUser } = useDataStore();
  const jobId = getActiveBidJobId();
  const { data, isLoading, isError, error, refetch } = useLiveBids(jobId);
  const { pause, resume, stop } = useLiveBidActions();
  const [restarting, setRestarting] = useState(false);
  const [showBrowserMap, setShowBrowserMap] = useState<Record<string, boolean>>({});
  const toggleShowBrowser = (bidId: string) =>
    setShowBrowserMap((prev) => ({ ...prev, [bidId]: !prev[bidId] }));

  const isFleetUser = currentUser?.role === 'fleet';
  const bids = data?.items ?? [];
  const orphanedBids = bids.filter((b) => b.status === 'orphaned');
  const activeBids = bids.filter((b) => !isTerminal(b) && b.status !== 'orphaned');
  const terminalBids = bids.filter((b) => b.status === 'completed' || b.status === 'stopped');
  // Restore jobId from DB rows when sessionStorage was cleared (e.g. page refresh)
  const effectiveJobId = jobId ?? orphanedBids[0]?.job_id ?? activeBids[0]?.job_id ?? null;
  if (effectiveJobId && !jobId) setActiveBidJobId(effectiveJobId);

  console.log('[LiveBiddingStatus] jobId from sessionStorage:', jobId);
  console.log('[LiveBiddingStatus] effectiveJobId:', effectiveJobId);
  console.log('[LiveBiddingStatus] isLoading:', isLoading, 'isError:', isError, 'error:', error);
  console.log('[LiveBiddingStatus] raw data:', data);
  console.log('[LiveBiddingStatus] bids:', bids.map((b) => ({ id: b.id, status: b.status, user_control: b.user_control, isTerminal: isTerminal(b), canPause: canPause(b), canResume: canResume(b), canStop: canStop(b) })));

  const debugRows = bids.map((b) => ({
    id: b.id.slice(0, 8),
    status: b.status,
    user_control: b.user_control,
    isTerminal: isTerminal(b),
    canPause: canPause(b),
    canResume: canResume(b),
    canStop: canStop(b),
  }));

  // Fire once per render to backend log
  debugLog('LiveBiddingStatus:render', {
    jobId,
    effectiveJobId,
    isLoading,
    isError,
    totalBids: bids.length,
    orphaned: orphanedBids.length,
    active: activeBids.length,
    bids: debugRows,
  });

  const handleRestart = async (overrideJobId?: string, bidId?: string) => {
    // Use bidId (the leg_id) if provided, otherwise try to get from overrideJobId or orphaned bid
    // The restart endpoint expects the bid's 'id' field, not 'job_id'
    const restartJobId = bidId ?? overrideJobId ?? orphanedBids[0]?.id ?? orphanedBids[0]?.job_id;
    if (!restartJobId) return;
    const showBrowser = bidId ? (showBrowserMap[bidId] ?? false) : false;
    setRestarting(true);
    try {
      const res = await fetch(`${API_BASE}/api/live-bids/${restartJobId}/restart?show_browser=${showBrowser}`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
      const newJobId = data.new_job_id as string | undefined;
      if (newJobId) {
        setActiveBidJobId(newJobId);
        toast.success(`Bid restarted — new job ${newJobId.slice(0, 8)}… (${showBrowser ? 'visible' : 'headless'})`);
      }
      refetch();
    } catch (e) {
      toast.error(`Restart failed: ${(e as Error).message}`);
    } finally {
      setRestarting(false);
    }
  };

  const handlePause = async (bid: LiveBid) => {
    try {
      await pause(bid);
      toast.success(`Paused ${bid.depot} ${bid.quantity}T`);
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  const handleResume = async (bid: LiveBid) => {
    try {
      await resume(bid);
      toast.success(`Resumed ${bid.depot} ${bid.quantity}T`);
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  const handleStop = async (bid: LiveBid) => {
    try {
      await stop(bid);
      toast.success(`Stopped ${bid.depot} ${bid.quantity}T`);
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  const renderStatusBadge = (bid: LiveBid) => {
    const label = formatStatus(bid.status);
    const isLive = !isTerminal(bid) || bid.status === 'won';
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium',
          bid.status === 'won' && 'bg-warning/20 text-warning',
          bid.status === 'paused' && 'bg-warning/20 text-warning',
          bid.status === 'stopped' && 'bg-muted text-muted-foreground',
          bid.status === 'completed' && 'bg-muted text-muted-foreground',
          bid.status === 'orphaned' && 'bg-destructive/20 text-destructive',
          isLive && bid.status !== 'won' && bid.status !== 'paused' && 'bg-success/20 text-success',
        )}
      >
        {isLive && bid.status !== 'stopped' && bid.status !== 'completed' && (
          <span className={bid.status !== 'paused' ? 'animate-pulse' : ''}>●</span>
        )}
        {label}
        {bid.current_rank != null && bid.status === 'waiting_rank' && (
          <span className="ml-1">(Rank {bid.current_rank})</span>
        )}
      </span>
    );
  };

  return (
    <div className="space-y-6 animate-fade-in">
      <div className="bg-card rounded-xl p-6 border border-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="relative p-3 bg-primary/10 rounded-lg">
              <Activity className="h-6 w-6 text-primary" />
              {activeBids.length > 0 && (
                <span className="absolute -top-1 -right-1 flex h-4 w-4">
                  <span className="animate-ping absolute h-full w-full rounded-full bg-success opacity-75" />
                  <span className="relative rounded-full h-4 w-4 bg-success" />
                </span>
              )}
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">Live E-Bidding Status</h1>
              <p className="text-muted-foreground text-sm">
                {isLoading
                  ? 'Loading live bids…'
                  : activeBids.length > 0
                    ? `${activeBids.length} active bid leg(s)`
                    : 'No active bid legs'}
                {jobId ? ` • Job ${effectiveJobId!.slice(0, 8)}…` : ''}
                {isFleetUser && ' • Fleet View'}
              </p>
            </div>
          </div>
          {activeBids.length > 0 && (
            <div className="flex items-center gap-2 text-success">
              <span className="animate-pulse">●</span>LIVE
            </div>
          )}
        </div>
      </div>

      {isFleetUser && (
        <div className="bg-warning/10 border border-warning/30 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-warning flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-medium text-warning">Fleet User Access</p>
            <p className="text-sm text-muted-foreground mt-1">
              Live automation status is read-only for fleet users. Pause and stop actions require vendor access.
            </p>
          </div>
        </div>
      )}

      {isError && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-4 text-sm text-destructive">
          Failed to load live bids: {String((error as Error)?.message || error)}
        </div>
      )}

      {orphanedBids.length > 0 && !isFleetUser && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-4 flex items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 text-destructive flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-medium text-destructive">Backend restarted — worker stopped</p>
              <p className="text-sm text-muted-foreground mt-1">
                {orphanedBids.length} bid leg(s) were orphaned when the backend restarted. Click Restart to resume automation.
              </p>
            </div>
          </div>
          <Button
            size="sm"
            variant="destructive"
            className="gap-2 flex-shrink-0"
            onClick={() => handleRestart(orphanedBids[0]?.job_id, orphanedBids[0]?.id)}
            disabled={restarting}
          >
            <RefreshCw className={cn('h-4 w-4', restarting && 'animate-spin')} />
            {restarting ? 'Restarting…' : 'Restart Bid'}
          </Button>
        </div>
      )}

      {!jobId && !isLoading && bids.length === 0 && (
        <div className="bg-muted/30 border border-border rounded-lg p-4 text-sm text-muted-foreground">
          Start bidding from the Control Panel to populate this dashboard. The active job id is stored in your session after start.
        </div>
      )}

      {bids.length > 0 ? (
        <div className="bg-card rounded-xl border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30">
                <TableHead>Depot</TableHead>
                <TableHead>Destination</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead>Organization</TableHead>
                <TableHead className="text-center">Rank</TableHead>
                <TableHead className="text-center">Status</TableHead>
                <TableHead className="text-center">Winning Time</TableHead>
                <TableHead className="text-center">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {bids.map((bid) => (
                <TableRow
                  key={bid.id}
                  className={cn(
                    'hover:bg-muted/20',
                    bid.current_rank === 1 && bid.status === 'won' && 'bg-warning/5',
                  )}
                >
                  <TableCell className="font-medium">{bid.depot}</TableCell>
                  <TableCell>{bid.destination?.trim() ? bid.destination : '—'}</TableCell>
                  <TableCell>
                    <span className="px-2 py-1 bg-accent/50 text-accent-foreground rounded-md text-sm font-medium">
                      {bid.quantity}T
                    </span>
                  </TableCell>
                  <TableCell>{bid.organization_name?.trim() ? bid.organization_name : '—'}</TableCell>
                  <TableCell className="text-center">
                    {bid.current_rank != null ? (
                      bid.current_rank === 1 ? (
                        <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-warning/20 text-warning font-bold">
                          <Trophy className="h-3 w-3" />1
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-3 py-1 rounded-full bg-muted text-muted-foreground font-medium">
                          {bid.current_rank}
                        </span>
                      )
                    ) : (
                      '—'
                    )}
                  </TableCell>
                  <TableCell className="text-center">{renderStatusBadge(bid)}</TableCell>
                  <TableCell className="text-center text-sm">
                    {bid.current_rank === 1 ? formatWonTime(bid.won_timestamp) : '—'}
                  </TableCell>
                  <TableCell className="text-center">
                    <div className="flex items-center justify-center gap-1">
                      {(() => {
                        const isOrphaned = bid.status === 'orphaned';
                        const cp = canPause(bid);
                        const cr = canResume(bid);
                        const cs = canStop(bid);
                        debugLog('LiveBiddingStatus:actions', { id: bid.id.slice(0,8), status: bid.status, user_control: bid.user_control, isFleetUser, isOrphaned, canPause: cp, canResume: cr, canStop: cs });
                        if (isOrphaned) return (
                          <div className="flex flex-col gap-1">
                            <button
                              onClick={() => toggleShowBrowser(bid.id)}
                              className={cn(
                                'flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium border transition-colors w-full',
                                (showBrowserMap[bid.id] ?? false)
                                  ? 'bg-primary/10 border-primary text-primary'
                                  : 'bg-muted/30 border-border text-muted-foreground hover:text-foreground',
                              )}
                            >
                              <Monitor className="h-3 w-3" />
                              {(showBrowserMap[bid.id] ?? false) ? 'Visible' : 'Headless'}
                            </button>
                            <div className="flex items-center justify-center gap-1 flex-wrap">
                              {cp && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="gap-1 h-8 text-warning border-warning/30 hover:bg-warning/10"
                                  onClick={() => handlePause(bid)}
                                >
                                  <Pause className="h-3.5 w-3.5" />
                                  Pause
                                </Button>
                              )}
                              {cs && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="gap-1 h-8 text-destructive border-destructive/30 hover:bg-destructive/10"
                                  onClick={() => handleStop(bid)}
                                >
                                  <Square className="h-3.5 w-3.5" />
                                  Stop
                                </Button>
                              )}
                              <Button
                                size="sm"
                                variant="destructive"
                                className="gap-1 h-8"
                                onClick={() => handleRestart(bid.job_id, bid.id)}
                                disabled={restarting}
                              >
                                <RefreshCw className={cn('h-3.5 w-3.5', restarting && 'animate-spin')} />
                                {restarting ? 'Restarting…' : 'Restart'}
                              </Button>
                            </div>
                          </div>
                        );
                        if (isFleetUser) return <span className="text-xs text-muted-foreground">View only</span>;
                        return (
                          <>
                            {cp && (
                              <Button size="sm" variant="outline" className="gap-1 h-8" onClick={() => handlePause(bid)}>
                                <Pause className="h-3.5 w-3.5" />Pause
                              </Button>
                            )}
                            {cr && (
                              <Button size="sm" variant="outline" className="gap-1 h-8" onClick={() => handleResume(bid)}>
                                <Play className="h-3.5 w-3.5" />Resume
                              </Button>
                            )}
                            {cs && (
                              <Button size="sm" variant="outline" className="gap-1 h-8 text-destructive border-destructive/30 hover:bg-destructive/10" onClick={() => handleStop(bid)}>
                                <Square className="h-3.5 w-3.5" />Stop
                              </Button>
                            )}
                            {!cp && !cr && !cs && (
                              <span className="text-xs text-muted-foreground">No actions</span>
                            )}
                          </>
                        );
                      })()}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        !isLoading && (
          <div className="bg-card rounded-xl border border-border p-12 text-center">
            <Activity className="h-16 w-16 text-muted-foreground/30 mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">No Live Bids</h3>
            <p className="text-muted-foreground">
              Start a new bid from the Control Panel. Each desired bid leg will appear here within seconds.
            </p>
          </div>
        )
      )}

      {terminalBids.length > 0 && (
        <p className="text-xs text-muted-foreground text-center">
          Polling every 2 seconds • {bids.length} total leg(s) for this job
        </p>
      )}
    </div>
  );
}
