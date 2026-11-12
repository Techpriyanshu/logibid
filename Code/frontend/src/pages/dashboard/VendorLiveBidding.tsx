import { useMemo, useState } from 'react';
import {
  Activity,
  Trophy,
  ChevronDown,
  Pause,
  Play,
  X,
  Bell,
  Check,
  AlertTriangle,
  Square,
  RefreshCw,
  Monitor,
  Globe,
  Search,
  Clock,
  Layers,
  Filter,
} from 'lucide-react';
import { useDataStore, type VehicleBid } from '@/store/dataStore';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { BidFilterBar } from '@/components/bidding/BidFilterBar';
import { useBidFilters } from '@/hooks/useBidFilters';
import { useLiveBids, useAllLiveBids, useLiveBidActions } from '@/hooks/useLiveBids';
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

function formatUpdateTime(dateStr?: string | null): { date: string; time: string } {
  if (!dateStr) return { date: '—', time: '' };
  try {
    const date = new Date(dateStr);
    if (isNaN(date.getTime())) return { date: dateStr, time: '' };
    return {
      date: date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }),
      time: date.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }),
    };
  } catch {
    return { date: dateStr, time: '' };
  }
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

  // 1. Current user's active session job live bids
  const jobId = getActiveBidJobId();
  const { data, isLoading, isError, error, refetch } = useLiveBids(jobId);

  // 2. Global all live bids (Without job ID filter)
  const {
    data: allJobsData,
    isLoading: isAllJobsLoading,
    isError: isAllJobsError,
    error: allJobsError,
    refetch: refetchAllJobs,
  } = useAllLiveBids();

  const { pause, resume, stop } = useLiveBidActions();
  const [restarting, setRestarting] = useState(false);
  const [showBrowserMap, setShowBrowserMap] = useState<Record<string, boolean>>({});

  // Search & filter state for Global Live Bids section
  const [globalSearchQuery, setGlobalSearchQuery] = useState('');
  const [globalStatusFilter, setGlobalStatusFilter] = useState<'all' | 'active' | 'won' | 'closed'>('all');

  const toggleShowBrowser = (bidId: string) =>
    setShowBrowserMap((prev) => ({ ...prev, [bidId]: !prev[bidId] }));

  // --- Current Job Bids ---
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
    bids: allApiBids.map((b) => ({
      id: b.id.slice(0, 8),
      status: b.status,
      user_control: b.user_control,
      isTerminal: isTerminal(b),
      canPause: canPause(b),
      canResume: canResume(b),
      canStop: canStop(b),
    })),
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

  // --- Global (All Jobs & Users) Bids ---
  const allSystemBids = allJobsData?.items ?? [];

  const filteredGlobalBids = useMemo(() => {
    return allSystemBids.filter((bid) => {
      // 1. Status Filter
      if (globalStatusFilter === 'active') {
        if (isTerminal(bid) && bid.status !== 'won' && bid.status !== 'orphaned') return false;
      } else if (globalStatusFilter === 'won') {
        if (bid.status !== 'won') return false;
      } else if (globalStatusFilter === 'closed') {
        if (bid.status !== 'completed' && bid.status !== 'stopped') return false;
      }

      // 2. Search Query (Depot, Destination, Org, Job ID, Quantity, Status)
      if (globalSearchQuery.trim()) {
        const q = globalSearchQuery.trim().toLowerCase();
        const depotMatch = bid.depot.toLowerCase().includes(q);
        const destMatch = bid.destination?.toLowerCase().includes(q) ?? false;
        const orgMatch = bid.organization_name?.toLowerCase().includes(q) ?? false;
        const jobMatch = bid.job_id.toLowerCase().includes(q);
        const qtyMatch = String(bid.quantity).includes(q);
        const statusMatch = bid.status.toLowerCase().includes(q);
        return depotMatch || destMatch || orgMatch || jobMatch || qtyMatch || statusMatch;
      }
      return true;
    });
  }, [allSystemBids, globalStatusFilter, globalSearchQuery]);

  const globalActiveCount = useMemo(
    () => allSystemBids.filter((b) => !isTerminal(b) || b.status === 'won' || b.status === 'orphaned').length,
    [allSystemBids],
  );
  const globalWonCount = useMemo(
    () => allSystemBids.filter((b) => b.status === 'won').length,
    [allSystemBids],
  );
  const globalClosedCount = useMemo(
    () => allSystemBids.filter((b) => b.status === 'completed' || b.status === 'stopped').length,
    [allSystemBids],
  );

  const handlePause = async (bid: LiveBid) => {
    try {
      await pause(bid);
      toast.success(`Paused ${bid.depot} ${bid.quantity}T`);
      refetchAllJobs();
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  const handleResume = async (bid: LiveBid) => {
    try {
      await resume(bid);
      toast.success(`Resumed ${bid.depot} ${bid.quantity}T`);
      refetchAllJobs();
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  const handleStop = async (bid: LiveBid) => {
    try {
      await stop(bid);
      toast.success(`Stopped ${bid.depot} ${bid.quantity}T`);
      refetchAllJobs();
    } catch (e) {
      toast.error(String((e as Error).message || e));
    }
  };

  const handleRestart = async (restartJobId: string, bidId: string) => {
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
      refetchAllJobs();
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

  const renderActionMenu = (bid: LiveBid) => {
    const cp = canPause(bid);
    const cr = canResume(bid);
    const cs = canStop(bid);
    const isOrphaned = bid.status === 'orphaned';
    const showBrowser = showBrowserMap[bid.id] ?? false;

    return (
      <Popover>
        <PopoverTrigger asChild>
          <Button size="sm" variant="outline" className="gap-1 h-8 px-2.5">
            Action <ChevronDown className="h-3 w-3" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-52 p-2 bg-popover border border-border" align="end">
          <div className="space-y-1">
            {/* Per-bid Show Browser toggle */}
            <button
              type="button"
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
          </div>
        </PopoverContent>
      </Popover>
    );
  };

  return (
    <div className="space-y-8 animate-fade-in pb-12">
      {/* SECTION 1: Current Session Header & Bids */}
      <div className="space-y-6">
        {/* Header */}
        <div className="bg-card rounded-xl p-6 border border-border">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
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
                  {effectiveJobId ? ` • Current Job ${effectiveJobId.slice(0, 8)}…` : ' • No active job in session'}
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
                <div className="flex items-center gap-2 text-success font-medium">
                  <span className="animate-pulse">●</span>LIVE
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Filter Bar for Current Job */}
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
                      <span
                        className={cn(
                          'px-2 py-0.5 rounded text-xs font-medium',
                          request.requestType === 'PAUSE'
                            ? 'bg-warning/20 text-warning'
                            : 'bg-destructive/20 text-destructive',
                        )}
                      >
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
            Failed to load live bids for current job: {String((error as Error)?.message || error)}
          </div>
        )}

        {!jobId && !isLoading && allApiBids.length === 0 && (
          <div className="bg-muted/30 border border-border rounded-lg p-4 text-sm text-muted-foreground">
            No active job in this session. Start bidding from the Control Panel, or view all system bids in the section below.
          </div>
        )}

        {/* Current Job Live Bid Legs Table */}
        {liveApiBids.length > 0 ? (
          <div className="bg-card rounded-xl border border-border overflow-hidden">
            <div className="p-4 border-b border-border bg-muted/30 flex items-center justify-between">
              <div>
                <h2 className="font-semibold text-foreground flex items-center gap-2">
                  <Activity className="h-4 w-4 text-primary" />
                  Active Live Bid Legs (Current Session)
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Live bidding legs assigned to job {effectiveJobId ? `${effectiveJobId.slice(0, 8)}…` : 'in session'}
                </p>
              </div>
              <Badge variant="secondary" className="bg-primary/10 text-primary border-primary/20">
                {liveApiBids.length} Active Leg(s)
              </Badge>
            </div>
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
                      {renderActionMenu(bid)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : (
          !isLoading && (
            <div className="bg-card rounded-xl border border-border p-8 text-center">
              <Activity className="h-12 w-12 text-muted-foreground/30 mx-auto mb-3" />
              <h3 className="text-base font-semibold mb-1">
                {hasActiveFilters ? 'No Live Bids Found for Filter' : 'No Live Bids in Current Session'}
              </h3>
              <p className="text-sm text-muted-foreground max-w-md mx-auto">
                {hasActiveFilters
                  ? 'No records found for selected criteria in this session.'
                  : 'Start a new bid from the Control Panel, or check all global live bids below.'}
              </p>
            </div>
          )
        )}

        {/* Closed Bid Legs for Current Job */}
        {closedApiBids.length > 0 && (
          <div className="bg-card rounded-xl border border-border overflow-hidden">
            <div className="p-4 border-b border-border bg-muted/30 flex items-center justify-between">
              <h2 className="font-semibold text-foreground">Stopped / Completed Legs (Current Session)</h2>
              <Badge variant="outline" className="text-xs">
                {closedApiBids.length} Closed
              </Badge>
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
            Current session polling every 2s • {allApiBids.length} total leg(s) in job {effectiveJobId?.slice(0, 8)}…
          </p>
        )}
      </div>

      {/* ───────────────────────────────────────────────────────────── */}
      {/* SECTION 2: All Live Bids (Without Job ID Filter / Global View) */}
      {/* ───────────────────────────────────────────────────────────── */}
      <div className="space-y-4 pt-4 border-t border-border">
        {/* Section Card */}
        <div className="bg-card rounded-xl border border-primary/20 overflow-hidden shadow-sm">
          {/* Header */}
          <div className="p-4 border-b border-border bg-primary/5 flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-primary/10 text-primary rounded-lg">
                <Globe className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-bold text-foreground">All Live Bids</h2>
                  <Badge variant="outline" className="border-primary/40 text-primary bg-primary/5 text-xs font-semibold">
                    Global / Without Job ID
                  </Badge>
                  <span className="px-2 py-0.5 text-xs rounded-full bg-muted text-muted-foreground font-medium">
                    {filteredGlobalBids.length} of {allSystemBids.length}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Monitor all active, won, and completed bidding legs across all users and jobs
                </p>
              </div>
            </div>

            {/* Controls Bar: Filter tabs & Refresh */}
            <div className="flex flex-wrap items-center gap-2">
              {/* Status Tabs */}
              <div className="flex items-center gap-1 bg-background/90 p-1 rounded-lg border border-border">
                <button
                  type="button"
                  onClick={() => setGlobalStatusFilter('all')}
                  className={cn(
                    'px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                    globalStatusFilter === 'all'
                      ? 'bg-primary text-primary-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                  )}
                >
                  All ({allSystemBids.length})
                </button>
                <button
                  type="button"
                  onClick={() => setGlobalStatusFilter('active')}
                  className={cn(
                    'px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                    globalStatusFilter === 'active'
                      ? 'bg-success text-success-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                  )}
                >
                  Active ({globalActiveCount})
                </button>
                <button
                  type="button"
                  onClick={() => setGlobalStatusFilter('won')}
                  className={cn(
                    'px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                    globalStatusFilter === 'won'
                      ? 'bg-warning text-warning-foreground shadow-sm'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                  )}
                >
                  Won ({globalWonCount})
                </button>
                <button
                  type="button"
                  onClick={() => setGlobalStatusFilter('closed')}
                  className={cn(
                    'px-2.5 py-1 text-xs font-medium rounded-md transition-colors',
                    globalStatusFilter === 'closed'
                      ? 'bg-muted-foreground text-background shadow-sm'
                      : 'text-muted-foreground hover:text-foreground hover:bg-muted',
                  )}
                >
                  Closed ({globalClosedCount})
                </button>
              </div>

              {/* Refresh Button */}
              <Button
                size="sm"
                variant="outline"
                onClick={() => refetchAllJobs()}
                className="h-8 gap-1.5 px-2.5 text-xs"
              >
                <RefreshCw className={cn('h-3.5 w-3.5', isAllJobsLoading && 'animate-spin')} />
                Refresh
              </Button>
            </div>
          </div>

          {/* Search & Quick Bar */}
          <div className="p-3 bg-muted/20 border-b border-border flex items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search depot, destination, organization, or job ID…"
                value={globalSearchQuery}
                onChange={(e) => setGlobalSearchQuery(e.target.value)}
                className="h-8 pl-8 text-xs bg-background"
              />
            </div>
            {globalSearchQuery && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setGlobalSearchQuery('')}
                className="h-8 text-xs px-2 text-muted-foreground hover:text-foreground"
              >
                Clear Search
              </Button>
            )}
          </div>

          {/* Error Message */}
          {isAllJobsError && (
            <div className="p-4 bg-destructive/10 text-destructive text-sm border-b border-destructive/20">
              Failed to load global live bids: {String((allJobsError as Error)?.message || allJobsError)}
            </div>
          )}

          {/* Global Bids Table */}
          {isAllJobsLoading && allSystemBids.length === 0 ? (
            <div className="p-12 text-center">
              <RefreshCw className="h-8 w-8 text-muted-foreground animate-spin mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">Loading all live bids across jobs…</p>
            </div>
          ) : filteredGlobalBids.length > 0 ? (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30">
                    <TableHead className="w-[120px]">Job ID</TableHead>
                    <TableHead>Depot</TableHead>
                    <TableHead>Destination</TableHead>
                    <TableHead>Quantity</TableHead>
                    <TableHead>Organization</TableHead>
                    <TableHead className="text-center">Status</TableHead>
                    <TableHead className="text-center">Rank</TableHead>
                    <TableHead className="text-center">Updated</TableHead>
                    <TableHead className="text-center">Action</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredGlobalBids.map((bid) => {
                    const { date, time } = formatUpdateTime(bid.updated_at);
                    const isCurrentJob = effectiveJobId && bid.job_id === effectiveJobId;

                    return (
                      <TableRow
                        key={bid.id}
                        className={cn(
                          'hover:bg-muted/20 transition-colors',
                          isCurrentJob && 'bg-primary/[0.03]',
                          bid.status === 'won' && 'bg-warning/5',
                        )}
                      >
                        {/* Job ID Column */}
                        <TableCell className="font-mono text-xs">
                          <div className="flex items-center gap-1.5">
                            <span
                              title={bid.job_id}
                              className={cn(
                                'px-2 py-0.5 rounded font-medium text-[11px] truncate max-w-[100px]',
                                isCurrentJob
                                  ? 'bg-primary/20 text-primary font-semibold border border-primary/30'
                                  : 'bg-muted text-muted-foreground',
                              )}
                            >
                              {bid.job_id.slice(0, 8)}
                            </span>
                            {isCurrentJob && (
                              <span className="h-1.5 w-1.5 rounded-full bg-primary" title="Your current session job" />
                            )}
                          </div>
                        </TableCell>

                        {/* Depot Column */}
                        <TableCell className="font-semibold text-foreground">
                          {bid.depot}
                        </TableCell>

                        {/* Destination Column */}
                        <TableCell>
                          {bid.destination?.trim() ? (
                            <span className="font-medium">{bid.destination}</span>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>

                        {/* Quantity / Tonnage Column */}
                        <TableCell>
                          <span className="px-2 py-0.5 bg-accent/60 text-accent-foreground rounded-md text-xs font-semibold">
                            {bid.quantity}T
                          </span>
                        </TableCell>

                        {/* Organization Column */}
                        <TableCell className="text-xs text-muted-foreground">
                          {bid.organization_name?.trim() ? bid.organization_name : '—'}
                        </TableCell>

                        {/* Status Column */}
                        <TableCell className="text-center">
                          {renderStatusBadge(bid)}
                        </TableCell>

                        {/* Rank Column */}
                        <TableCell className="text-center">
                          {bid.current_rank != null ? (
                            bid.current_rank === 1 ? (
                              <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-warning/20 text-warning font-bold text-xs">
                                <Trophy className="h-3 w-3" />1
                              </span>
                            ) : (
                              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-muted text-muted-foreground font-medium text-xs">
                                Rank {bid.current_rank}
                              </span>
                            )
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </TableCell>

                        {/* Updated Time Column */}
                        <TableCell className="text-center font-mono text-xs">
                          <div className="flex flex-col items-center">
                            <span className="text-[11px] text-muted-foreground">{date}</span>
                            <span className="text-xs font-medium text-foreground">{time}</span>
                          </div>
                        </TableCell>

                        {/* Action Column */}
                        <TableCell className="text-center">
                          {renderActionMenu(bid)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="p-12 text-center">
              <Layers className="h-10 w-10 text-muted-foreground/30 mx-auto mb-2" />
              <h3 className="text-sm font-semibold text-foreground mb-1">
                {globalSearchQuery || globalStatusFilter !== 'all'
                  ? 'No Bids Match Global Filter'
                  : 'No Live Bids in System'}
              </h3>
              <p className="text-xs text-muted-foreground max-w-sm mx-auto">
                {globalSearchQuery || globalStatusFilter !== 'all'
                  ? 'Try clearing the search query or status filter to view all system bids.'
                  : 'When any user starts a bidding session, live bids will appear here automatically.'}
              </p>
            </div>
          )}

          {/* Footer note */}
          <div className="p-3 bg-muted/30 border-t border-border flex items-center justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-success animate-pulse" />
              Global monitor polling continuously (2s)
            </span>
            <span>
              Total records: {allSystemBids.length}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
