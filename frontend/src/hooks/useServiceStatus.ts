import { useQuery } from '@tanstack/react-query';
import { API_BASE_URL } from '../api/client';
import { checkService } from '../api/status';
import type { HealthEndpoint, ServiceStatus } from '../api/status';

export function useServiceStatus(endpoint: HealthEndpoint) {
  const query = useQuery({
    queryKey: ['service-status', API_BASE_URL, endpoint],
    queryFn: ({ signal }) => checkService(endpoint, signal),
    retry: false,
    staleTime: Infinity,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    // A local API may be reachable even when the browser reports no internet.
    networkMode: 'always',
  });

  let status: ServiceStatus;
  if (query.isFetching || query.isPending) {
    status = {
      state: 'checking',
      detail: endpoint === '/health'
        ? 'Waiting for the API to respond…'
        : 'Checking the database connection…',
    };
  } else if (query.isError) {
    status = { state: 'unhealthy', detail: query.error.message };
  } else {
    status = query.data;
  }

  return {
    status,
    checkedAt: Math.max(query.dataUpdatedAt, query.errorUpdatedAt),
    refetch: query.refetch,
  };
}
