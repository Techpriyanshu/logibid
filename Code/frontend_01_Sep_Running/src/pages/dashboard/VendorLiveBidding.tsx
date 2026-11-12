import { useMemo, useState } from 'react';
import { Activity, Trophy, ChevronDown, Pause, Play, X, Bell, Check, AlertTriangle, Square, RefreshCw, Monitor } from 'lucide-react';
import { useDataStore, type VehicleBid } from '@/store/dataStore';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { BidFilterBar } from '@/components/bidding/BidFilterBar';
import { useBidFilters } from '@/hooks/useBidFilters';
import { useLiveBids, useLiveBidActions } from '@/hooks/useLiveBids';
import { useFleetRequests, useFleetAdminActions } from '@/hooks/useFleetAdmin';
import { fleetRequestToActionRequest } from '@/utils/fleetAdminMappers';
import { getActiveBidJobId, setActiveBidJobId, debugLog, type LiveBid } from '@/api/liveBids';
import { DEPOT_MASTER_LIST } from '@/constants/depots';
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

function liveBidToFilterAdapter(bid: LiveBid): VehicleBid {
  const depot = DEPOT_MASTER_LIST.find(
    (d) => d.name.toUpperCase() === bid.depot.toUpperCase(),
  );
  return {
    id: bid.id,
    plant_id: 'tanda',
    plant_name: 'Tanda Cement Works',
    depot_id: depot?.id ?? '',
    depot_name: bid.depot,
    destination: bid.destination ?? undefined,
    tonnage: bid.quantity,
    status: bid.status === 'paused' ? 'Paused' : 'Live',
    rank: bid.current_rank,
    created_at: bid.updated_at,
    time_remaining: 0,
  };
}

export default function VendorLiveBidding() {
  const { currentUser } = useDataStore();
  const { data: requestsData } = useFleetRequests('Pending');
  const { resolveRequest } = useFleetAdminActions();

  const jobId = getActiveBidJobId();
  const { data, isLoading, isError, error, refetch } = useLiveBids(jobId);
  const { pause, resume, stop } = useLiveBidActions();
  const [restarting, setRestarting] = useState(false);
  const [showBrowserMap, setShowBrowserMap] = useState<Record<string, boolean>>({});

  const toggleShowBrowser = (bidId: string) =>
    setShowBrowserMap((prev) => ({ ...prev, [bidId]: !prev[bidId] }));

  const allApiBids = data?.items ?? [];
  // Restore jobId from DB rows when sessionStorage was cleared
  const effectiveJobId = jobId ?? allApiBids[0]?.job_id ?? null;
  if (effectiveJobId && !jobId) setActiveBidJobId(effectiveJobId);

  // Log to backend on every render
  debugLog('VendorLiveBidding:render', {
    jobId,
    effectiveJobId,
    isLoading,
    totalBids: allApiBids.length,
    bids: allApiBids.map((b) => ({ id: b.id.slice(0, 8), status: b.status, user_control: b.user_control, isTerminal: isTerminal(b), canPause: canPause(b), canResume: canResume(b), canStop: canStop(b) })),
  });
  const filterAdapterBids = useMemo(
    () => allApiBids.map(liveBidToFilterAdapter),
    [allApiBids],
  );

  const {
    pendingFilters,
    appliedFilters,
    setPendingDepot,
    setPendingDestination,
    applyFilters,
    clearFilters,
    filterBids,
    availableDestinations,
    hasActiveFilters,
    canApplyFilters,
    isSearching,
  } = useBidFilters(filterAdapterBids);

  const filteredIds = useMemo(
    () => new Set(filterBids(filterAdapterBids).map((b) => b.id)),
    [filterBids, filterAdapterBids],
  );

  const filteredApiBids = allApiBids.filter((b) => filteredIds.has(b.id));
  // include orphaned in live table so Restart button is visible
  const liveApiBids = filteredApiBids.filter((b) => !isTerminal(b) || b.status === 'won' || b.status === 'orphaned');
  const closedApiBids = filteredApiBids.filter(
    (b) => b.status === 'completed' || b.status === 'stopped',
  );
  const pendingRequests = useMemo(
    () => (requestsData?.items ?? []).map(fleetRequestToActionRequest),
    [requestsData?.items],
  );

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

  const handleRestart = async (restartJobId: string, bidId: string) => {
    // The restart endpoint expects the bid's 'id' field (leg_id), not 'job_id'
    // Use bidId (second parameter) which is the actual bid.id
    const actualBidId = bidId;
    const showBrowser = showBrowserMap[bidId] ?? false;
    setRestarting(true);
    debugLog('VendorLiveBidding:restart', { restartJobId, bidId, showBrowser });
    try {
      const url = `${API_BASE}/api/live-bids/${actualBidId}/restart?show_browser=${showBrowser}`;
      const res = await fetch(url, { method: 'POST' });
      const json = await res.json();
      if (!res.ok) throw new Error(json?.detail || `HTTP ${res.status}`);
      const newJobId = json.new_job_id as string | undefined;
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
          isLive && bid.status !== 'won' && bid.status !== 'paused' && 'bg-success/20 text-success',
        )}
      >
        {isLive && bid.status !== 'stopped' && bid.status !== 'completed' && (
          <span className={bid.status !== 'paused' ? 'animate-pulse' : ''}>●</span>
        )}
        {label}
      </span>
    );
  };

  const handleApproveRequest = async (requestId: string) => {
    try {
      await resolveRequest.mutateAsync({
        requestId,
        payload: {
          status: 'Approved',
          resolved_by: currentUser?.username ?? 'vendor',
        },
      });
      toast.success('Request approved and action executed');
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  const handleRejectRequest = async (requestId: string) => {
    try {
      await resolveRequest.mutateAsync({
        requestId,
        payload: {
          status: 'Rejected',
          resolved_by: currentUser?.username ?? 'vendor',
        },
      });
      toast.info('Request rejected');
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Header */}
      <div className="bg-card rounded-xl p-6 border border-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="relative p-3 bg-primary/10 rounded-lg">
              <Activity className="h-6 w-6 text-primary" />
              {liveApiBids.length > 0 && (
                <span className="absolute -top-1 -right-1 flex h-4 w-4">
                  <span className="animate-ping absolute h-full w-full rounded-full bg-success opacity-75"></span>
                  <span className="relative rounded-full h-4 w-4 bg-success"></span>
                </span>
              )}
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">Vendor Live Bidding</h1>
              <p className="text-muted-foreground text-sm">
                {isLoading
                  ? 'Loading live bids…'
                  : liveApiBids.length > 0
                    ? `${liveApiBids.length} active bid leg(s)`
                    : 'No active bid legs'}
                {jobId ? ` • Job ${jobId.slice(0, 8)}…` : ''}
                {' • Vendor Control'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {pendingRequests.length > 0 && (
              <div className="flex items-center gap-2 px-3 py-1.5 bg-warning/20 text-warning rounded-full animate-pulse">
                <Bell className="h-4 w-4" />
                <span className="font-medium">{pendingRequests.length} Pending Request(s)</span>
              </div>
            )}
            {liveApiBids.length > 0 && (
              <div className="flex items-center gap-2 text-success">
                <span className="animate-pulse">●</span>LIVE
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <BidFilterBar
        pendingFilters={pendingFilters}
        appliedFilters={appliedFilters}
        onDepotChange={setPendingDepot}
        onDestinationChange={setPendingDestination}
        onApplyFilters={applyFilters}
        onClearFilters={clearFilters}
        availableDestinations={availableDestinations}
        hasActiveFilters={hasActiveFilters}
        canApplyFilters={canApplyFilters}
        isSearching={isSearching}
      />

      {/* Pending Requests Section */}
      {pendingRequests.length > 0 && (
        <div className="bg-warning/5 rounded-xl border-2 border-warning/30 overflow-hidden">
          <div className="p-4 border-b border-warning/30 bg-warning/10 flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-warning" />
            <h2 className="font-semibold text-warning">Fleet Action Requests</h2>
            <Badge variant="outline" className="ml-auto border-warning text-warning">
              {pendingRequests.length} Pending
            </Badge>
          </div>
          <div className="p-4 space-y-3">
            {pendingRequests.map((request) => (
              <div 
                key={request.id} 
                className="flex items-center justify-between p-4 bg-card rounded-lg border border-border animate-pulse"
              >
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={cn(
                      "px-2 py-0.5 rounded text-xs font-medium",
                      request.requestType === 'PAUSE' 
                        ? "bg-warning/20 text-warning" 
                        : "bg-destructive/20 text-destructive"
                    )}>
                      {request.requestType} REQUEST
                    </span>
                    <span className="text-xs text-muted-foreground">
                      from {request.requestedBy}
                    </span>
                  </div>
                  <p className="font-medium">
                    Vehicle – {request.tonnage}T • {request.depotName}
                    {request.destination && ` → ${request.destination}`}
                  </p>
                  {request.remarks && (
                    <p className="text-sm text-muted-foreground mt-1">
                      Remarks: {request.remarks}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="text-destructive hover:bg-destructive/10 border-destructive/30"
                    onClick={() => handleRejectRequest(request.id)}
                  >
                    <X className="h-4 w-4 mr-1" />
                    Reject
                  </Button>
                  <Button
                    size="sm"
                    className="bg-success hover:bg-success/90 text-success-foreground"
                    onClick={() => handleApproveRequest(request.id)}
                  >
                    <Check className="h-4 w-4 mr-1" />
                    Approve
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {isError && (
        <div className="bg-destructive/10 border border-destructive/30 rounded-lg p-4 text-sm text-destructive">
          Failed to load live bids: {String((error as Error)?.message || error)}
        </div>
      )}

      {!jobId && !isLoading && allApiBids.length === 0 && (
        <div className="bg-muted/30 border border-border rounded-lg p-4 text-sm text-muted-foreground">
          Start bidding from the Control Panel to populate this dashboard. The active job id is stored in your session after start.
        </div>
      )}

      {/* Live Bid Legs Table */}
      {liveApiBids.length > 0 ? (
        <div className="bg-card rounded-xl border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30">
                <TableHead>Depot</TableHead>
                <TableHead>Destination</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead>Organization</TableHead>
                <TableHead className="text-center">Status</TableHead>
                <TableHead className="text-center">Rank</TableHead>
                <TableHead className="text-center">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {liveApiBids.map((bid) => (
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
                  <TableCell className="text-center">{renderStatusBadge(bid)}</TableCell>
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
                  <TableCell className="text-center">
                    <Popover>
                      <PopoverTrigger asChild>
                        <Button size="sm" variant="outline" className="gap-1">
                          Action <ChevronDown className="h-3 w-3" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-52 p-2 bg-popover border border-border" align="end">
                        <div className="space-y-1">
                          {(() => {
                            const cp = canPause(bid);
                            const cr = canResume(bid);
                            const cs = canStop(bid);
                            const isOrphaned = bid.status === 'orphaned';
                            const showBrowser = showBrowserMap[bid.id] ?? false;
                            debugLog('VendorLiveBidding:actions', { id: bid.id.slice(0,8), status: bid.status, user_control: bid.user_control, isOrphaned, canPause: cp, canResume: cr, canStop: cs });
                            return (
                              <>
                                {/* Per-bid Show Browser toggle */}
                                <button
                                  onClick={() => toggleShowBrowser(bid.id)}
                                  className={cn(
                                    'w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs font-medium border transition-colors mb-1',
                                    showBrowser
                                      ? 'bg-primary/10 border-primary text-primary'
                                      : 'bg-muted/30 border-border text-muted-foreground hover:text-foreground',
                                  )}
                                >
                                  <Monitor className="h-3.5 w-3.5" />
                                  {showBrowser ? 'Browser: Visible' : 'Browser: Headless'}
                                </button>
                                <div className="border-t border-border my-1" />
                                {isOrphaned && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleRestart(bid.job_id, bid.id)}
                                    disabled={restarting}
                                    className="w-full justify-start h-8 px-2 text-sm text-destructive hover:bg-destructive/10"
                                  >
                                    <RefreshCw className={cn('h-4 w-4 mr-2', restarting && 'animate-spin')} />
                                    {restarting ? 'Restarting…' : 'Restart Bid'}
                                  </Button>
                                )}
                                {cp && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handlePause(bid)}
                                    className="w-full justify-start h-8 px-2 text-sm text-warning hover:bg-warning/10"
                                  >
                                    <Pause className="h-4 w-4 mr-2" />
                                    Pause Bidding
                                  </Button>
                                )}
                                {cr && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleResume(bid)}
                                    className="w-full justify-start h-8 px-2 text-sm text-success hover:bg-success/10"
                                  >
                                    <Play className="h-4 w-4 mr-2" />
                                    Resume Bidding
                                  </Button>
                                )}
                                {cs && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => handleStop(bid)}
                                    className="w-full justify-start h-8 px-2 text-sm text-destructive hover:bg-destructive/10"
                                  >
                                    <Square className="h-4 w-4 mr-2" />
                                    Stop Bidding
                                  </Button>
                                )}
                                {!isOrphaned && !cp && !cr && !cs && (
                                  <p className="text-xs text-muted-foreground px-2 py-1">No actions available</p>
                                )}
                              </>
                            );
                          })()}
                        </div>
                      </PopoverContent>
                    </Popover>
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
            <h3 className="text-lg font-semibold mb-2">
              {hasActiveFilters ? 'No Live Bids Found' : 'No Live Bid Legs'}
            </h3>
            <p className="text-muted-foreground">
              {hasActiveFilters
                ? 'No records found for selected criteria. Try adjusting your filters.'
                : 'Start a new bid from the Control Panel. Each desired bid leg will appear here within seconds.'}
            </p>
          </div>
        )
      )}

      {/* Closed Bid Legs */}
      {closedApiBids.length > 0 && (
        <div className="bg-card rounded-xl border border-border overflow-hidden">
          <div className="p-4 border-b border-border bg-muted/30">
            <h2 className="font-semibold">Stopped / Completed Legs</h2>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Depot</TableHead>
                <TableHead>Destination</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead className="text-center">Final Status</TableHead>
                <TableHead className="text-center">Final Rank</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {closedApiBids.map((bid) => (
                <TableRow key={bid.id} className={cn(bid.current_rank === 1 && 'bg-success/5')}>
                  <TableCell className="font-medium">{bid.depot}</TableCell>
                  <TableCell>{bid.destination?.trim() ? bid.destination : '—'}</TableCell>
                  <TableCell>
                    <span className="px-2 py-1 bg-accent/50 text-accent-foreground rounded-md text-sm font-medium">
                      {bid.quantity}T
                    </span>
                  </TableCell>
                  <TableCell className="text-center">{formatStatus(bid.status)}</TableCell>
                  <TableCell className="text-center">
                    {bid.current_rank === 1 ? (
                      <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full bg-success/20 text-success font-bold">
                        <Trophy className="h-3 w-3" />1 - Won
                      </span>
                    ) : (
                      <span className="text-muted-foreground font-medium">{bid.current_rank ?? '—'}</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {allApiBids.length > 0 && (
        <p className="text-xs text-muted-foreground text-center">
          Polling every 2 seconds • {allApiBids.length} total leg(s) for this job
        </p>
      )}
    </div>
  );
}
