import { useEffect, useRef } from 'react';
import { useMutation } from '@tanstack/react-query';
import { fetchPrPreview } from '../api/pullRequests';

export function usePrPreview() {
  const active = useRef<AbortController | null>(null);
  const mutation = useMutation({
    mutationFn: ({ url, signal }: { url: string; signal: AbortSignal }) => fetchPrPreview(url, signal),
    retry: false,
    networkMode: 'always',
    gcTime: 0,
  });

  useEffect(() => () => active.current?.abort(), []);

  function reset() {
    active.current?.abort();
    active.current = null;
    mutation.reset();
  }

  function submit(url: string) {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    mutation.mutate({ url, signal: controller.signal }, {
      onSettled: () => {
        if (active.current === controller) active.current = null;
      },
    });
  }

  return {
    data: mutation.data,
    error: mutation.error?.message,
    pending: mutation.isPending,
    submit,
    reset,
  };
}
