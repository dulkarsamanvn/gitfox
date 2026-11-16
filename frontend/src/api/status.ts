export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL?.trim() || 'http://127.0.0.1:8001'
).replace(/\/+$/, '');

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
  const timeout = AbortSignal.timeout(8_000);

  try {
    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
      signal: AbortSignal.any([signal, timeout]),
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });

    if (!response.ok) {
      return {
        state: 'unhealthy',
        detail: endpoint === '/ready' && response.status === 503
          ? 'The API is responding, but PostgreSQL is not ready. Check the database and try again.'
          : `The API returned HTTP ${response.status}. Try checking again.`,
      };
    }

    const data: unknown = await response.json();
    if (!validResponse(data, endpoint)) {
      return {
        state: 'unhealthy',
        detail: 'The API returned an unexpected response. Check the backend and try again.',
      };
    }

    return {
      state: 'healthy',
      detail: endpoint === '/health'
        ? 'FastAPI is accepting requests.'
        : 'PostgreSQL is connected and responding.',
    };
  } catch (error) {
    return {
      state: 'unhealthy',
      detail: timeout.aborted
        ? 'The check timed out. Check the backend and try again.'
        : error instanceof SyntaxError
          ? 'The API returned an unexpected response. Check the backend and try again.'
          : 'Could not complete the check. Make sure FastAPI is running and allows this frontend origin.',
    };
  }
}
