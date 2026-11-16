import axios from 'axios';

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL?.trim() || 'http://127.0.0.1:8001'
).replace(/\/+$/, '');

// Shared HTTP settings for requests to FastAPI.
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 8_000,
  headers: { Accept: 'application/json' },
  responseType: 'json',
  transitional: { silentJSONParsing: false, clarifyTimeoutError: true },
  adapter: 'fetch',
  fetchOptions: { cache: 'no-store' },
});
