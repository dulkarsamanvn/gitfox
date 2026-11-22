import axios from 'axios';
import { apiClient } from './client';

export const providerLabels = { openai: 'OpenAI', anthropic: 'Anthropic Claude', gemini: 'Google Gemini' } as const;
export type Provider = keyof typeof providerLabels;
export type ProviderProfile = { id: Provider; label: string; model: string; key_configured: boolean };
export type LlmConfiguration = { active_provider: Provider; providers: ProviderProfile[] };
export type LlmDraft = { provider: Provider; model: string; api_key?: string };
export type ConnectionResult = { status: 'ok'; provider: Provider; model: string; resolved_model: string; latency_ms: number };

const messages: Record<string, string> = {
  invalid_request: 'Check the provider, model ID, and API key.',
  request_too_large: 'The settings request is too large.',
  llm_local_only: 'LLM settings can only be managed from this computer through an allowed local address.',
  llm_key_missing: 'Enter an API key for this provider.',
  llm_auth_failed: 'The provider rejected this API key. Check it and try again.',
  llm_access_denied: 'This key does not have access to the selected model.',
  llm_model_not_found: 'The model was not found or is not available to this key.',
  llm_request_rejected: 'The provider rejected the settings. Check the model ID and API key.',
  llm_rate_limited: 'The provider rate limit was reached. Try again later.',
  llm_test_busy: 'A connection test is already running. Try again shortly.',
  llm_timeout: 'The provider connection test timed out. Try again.',
  llm_unavailable: 'Could not reach the provider. Try again later.',
  llm_invalid_response: 'The provider returned an unexpected model response.',
  llm_config_unavailable: 'The backend could not load or save the local LLM settings.',
};

class LlmClientError extends Error {}
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function provider(value: unknown): value is Provider {
  return typeof value === 'string' && Object.hasOwn(providerLabels, value);
}
function configuration(value: unknown): value is LlmConfiguration {
  if (!record(value) || !provider(value.active_provider) || !Array.isArray(value.providers) || value.providers.length !== 3 || 'api_key' in value) return false;
  const ids = new Set<Provider>();
  for (const profile of value.providers) {
    if (!record(profile) || !provider(profile.id) || ids.has(profile.id)
      || typeof profile.label !== 'string' || typeof profile.model !== 'string' || profile.model.length > 200
      || typeof profile.key_configured !== 'boolean' || 'api_key' in profile) return false;
    ids.add(profile.id);
  }
  return ids.size === 3;
}
function safeError(error: unknown): never {
  if (error instanceof LlmClientError) throw error;
  if (axios.isAxiosError(error)) {
    if (error.code === 'ETIMEDOUT' || error.code === 'ECONNABORTED') throw new LlmClientError('The settings request timed out. Try again.');
    const data: unknown = error.response?.data;
    if (record(data) && record(data.detail) && typeof data.detail.code === 'string' && Object.hasOwn(messages, data.detail.code)) {
      throw new LlmClientError(messages[data.detail.code]);
    }
  }
  // Never retain Axios errors: their request configuration can contain an API key.
  throw new LlmClientError('Could not complete the settings request. Check the backend and try again.');
}

export async function loadLlmConfiguration(signal: AbortSignal): Promise<LlmConfiguration> {
  try {
    const response = await apiClient.get<unknown>('/api/v1/llm/configuration', { signal });
    if (!configuration(response.data)) throw new LlmClientError('The server returned invalid LLM settings.');
    return response.data;
  } catch (error) { return safeError(error); }
}

export async function saveLlmConfiguration(draft: LlmDraft, signal: AbortSignal): Promise<LlmConfiguration> {
  try {
    const response = await apiClient.post<unknown>('/api/v1/llm/configuration', draft, { signal });
    if (!configuration(response.data)) throw new LlmClientError('The server returned invalid LLM settings.');
    return response.data;
  } catch (error) { return safeError(error); }
}

export async function checkLlmConnection(draft: LlmDraft, signal: AbortSignal): Promise<ConnectionResult> {
  try {
    const response = await apiClient.post<unknown>('/api/v1/llm/test-connection', draft, { signal, timeout: 20_000 });
    const data = response.data;
    if (!record(data) || data.status !== 'ok' || data.provider !== draft.provider
      || data.model !== draft.model.trim().replace(/^models\//, '')
      || typeof data.resolved_model !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(data.resolved_model)
      || (draft.api_key && data.resolved_model.includes(draft.api_key))
      || typeof data.latency_ms !== 'number' || !Number.isSafeInteger(data.latency_ms) || data.latency_ms < 0) {
      throw new LlmClientError('The server returned an invalid connection result.');
    }
    return data as ConnectionResult;
  } catch (error) { return safeError(error); }
}
