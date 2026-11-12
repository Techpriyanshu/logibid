import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  fetchLiveBids,
  getActiveBidJobId,
  pauseLiveBid,
  resumeLiveBid,
  stopLiveBid,
  type LiveBid,
} from '@/api/liveBids';

const POLL_MS = 2000;

export function useLiveBids(jobId?: string | null) {
  const resolvedJobId = jobId ?? getActiveBidJobId();

  return useQuery({
    queryKey: ['live-bids', resolvedJobId ?? 'all'],
    queryFn: () => fetchLiveBids(resolvedJobId),
    refetchInterval: POLL_MS,
    refetchIntervalInBackground: true,
  });
}

export function useLiveBidActions() {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['live-bids'] });
  };

  const pause = async (bid: LiveBid) => {
    await pauseLiveBid(bid.id);
    invalidate();
  };

  const resume = async (bid: LiveBid) => {
    await resumeLiveBid(bid.id);
    invalidate();
  };

  const stop = async (bid: LiveBid) => {
    await stopLiveBid(bid.id);
    invalidate();
  };

  return { pause, resume, stop };
}
