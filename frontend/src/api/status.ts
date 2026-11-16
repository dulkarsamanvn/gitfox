import axios from 'axios';
import { apiClient } from './client';

export type HealthEndpoint = '/health' | '/ready';

export type ServiceStatus = {
  state: 'checking' | 'healthy' | 'unhealthy';
  detail: string;
};

function validResponse(data: unknown, endpoint: HealthEndpoint): boolean {
  if (typeof data !== 'object' || data === null || !('status' in data)) {
    return false;
  }

  return data.status === 'ok' && (
    endpoint === '/health' || ('database' in data && data.database === 'ok')
  );
}

export async function checkService(
  endpoint: HealthEndpoint,
  signal: AbortSignal,
): Promise<ServiceStatus> {
  try {
    const response = await apiClient.get<unknown>(endpoint, { signal });

    // TypeScript checks our code; this check validates real data received at runtime.
    if (!validResponse(response.data, endpoint)) {
      throw new Error('The API returned an unexpected response. Check the backend and try again.');
    }

    return {
      state: 'healthy',
      detail: endpoint === '/health'
        ? 'FastAPI is accepting requests.'
        : 'PostgreSQL is connected and responding.',
    };
  } catch (error) {
    // Let TanStack Query cancel requests when a component unmounts.
    if (axios.isCancel(error)) throw error;

    if (axios.isAxiosError(error)) {
      if (error.code === 'ETIMEDOUT' || error.code === 'ECONNABORTED') {
        throw new Error('The check timed out. Check the backend and try again.');
      }
      if (error.response && (error.response.status < 200 || error.response.status >= 300)) {
        throw new Error(endpoint === '/ready' && error.response.status === 503
          ? 'The API is responding, but PostgreSQL is not ready. Check the database and try again.'
          : `The API returned HTTP ${error.response.status}. Try checking again.`);
      }
      if (error.code === 'ERR_BAD_RESPONSE') {
        throw new Error('The API returned an unexpected response. Check the backend and try again.');
      }
      throw new Error('Could not complete the check. Make sure FastAPI is running and allows this frontend origin.');
    }
    throw error;
  }
}
