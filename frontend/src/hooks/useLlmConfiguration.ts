import { useEffect, useRef } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { API_BASE_URL } from '../api/client';
import { checkLlmConnection, loadLlmConfiguration, saveLlmConfiguration } from '../api/llm';
import type { LlmDraft } from '../api/llm';

export function useLlmConfiguration() {
  const key = ['llm-configuration', API_BASE_URL];
  const queryClient = useQueryClient();
  const operation = useRef<{ action: 'save' | 'test'; draft: LlmDraft; controller: AbortController } | null>(null);
  const query = useQuery({ queryKey: key, queryFn: ({ signal }) => loadLlmConfiguration(signal),
    retry: false, gcTime: 0, networkMode: 'always', refetchOnWindowFocus: false, refetchOnReconnect: false });
  const mutation = useMutation({
    mutationFn: async () => {
      const current = operation.current;
      if (!current) throw new Error('Choose a configuration first.');
      if (current.action === 'save') return { kind: 'save' as const, configuration: await saveLlmConfiguration(current.draft, current.controller.signal) };
      return { kind: 'test' as const, result: await checkLlmConnection(current.draft, current.controller.signal) };
    },
    retry: false, gcTime: 0, networkMode: 'always',
    onSuccess: result => { if (result.kind === 'save') queryClient.setQueryData(key, result.configuration); },
    onSettled: () => { operation.current = null; },
  });
  useEffect(() => () => {
    operation.current?.controller.abort();
    operation.current = null;
  }, []);

  function run(action: 'save' | 'test', draft: LlmDraft) {
    if (operation.current) return;
    operation.current = { action, draft, controller: new AbortController() };
    mutation.mutate(); // Secret-bearing drafts are never stored as mutation variables.
  }
  return { configuration: query.data, loading: query.isPending, loadError: query.error?.message,
    reload: query.refetch, pending: mutation.isPending, action: operation.current?.action,
    error: mutation.error?.message, result: mutation.data, run, clearResult: mutation.reset };
}
