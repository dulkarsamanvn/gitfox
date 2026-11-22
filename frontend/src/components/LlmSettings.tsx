import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { providerLabels } from '../api/llm';
import type { Provider } from '../api/llm';
import { useLlmConfiguration } from '../hooks/useLlmConfiguration';

const modelDocs: Record<Provider, string> = {
  openai: 'https://developers.openai.com/api/docs/models',
  anthropic: 'https://platform.claude.com/docs/en/api/models/list',
  gemini: 'https://ai.google.dev/gemini-api/docs/models',
};

function SettingsPanel() {
  const api = useLlmConfiguration();
  const [provider, setProvider] = useState<Provider>('openai');
  const [model, setModel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);
  useEffect(() => {
    if (api.configuration) {
      setProvider(api.configuration.active_provider);
      setModel(api.configuration.providers.find(item => item.id === api.configuration?.active_provider)?.model || '');
      setApiKey('');
    }
  }, [api.configuration]);
  useEffect(() => {
    if (api.result?.kind === 'save') setApiKey('');
  }, [api.result]);
  const profile = api.configuration?.providers.find(item => item.id === provider);
  function changed() { setInputError(null); api.clearResult(); }
  function submit(action: 'save' | 'test') {
    if (api.pending) return;
    if (!model.trim()) { setInputError('Enter a model ID.'); return; }
    if (action === 'test' && !apiKey.trim() && !profile?.key_configured) { setInputError('Enter an API key for this provider.'); return; }
    setInputError(null);
    api.run(action, { provider, model: model.trim(), ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}) });
  }
  function save(event: FormEvent<HTMLFormElement>) { event.preventDefault(); submit('save'); }
  if (api.loading) return <p className="llm-loading" role="status">Loading LLM settings…</p>;
  if (api.loadError || !api.configuration) return <div className="llm-body"><p className="preview-error" role="alert">{api.loadError || 'Settings are unavailable.'}</p><button className="preview-cancel" onClick={() => void api.reload()}>Retry settings</button></div>;
  const active = api.configuration.providers.find(item => item.id === api.configuration?.active_provider);
  return (
    <div className="llm-body">
      <p className="llm-active">Active selection: <strong>{providerLabels[api.configuration.active_provider]}</strong>{active?.model ? ` / ${active.model}` : ' / no model selected'}</p>
      <form onSubmit={save} noValidate>
        <fieldset className="llm-fields" disabled={api.pending}>
          <div className="llm-field">
            <label htmlFor="llm-provider">LLM provider</label>
            <select id="llm-provider" value={provider} onChange={event => {
              const next = event.target.value as Provider;
              setProvider(next); setModel(api.configuration?.providers.find(item => item.id === next)?.model || ''); setApiKey(''); changed();
            }}>{Object.entries(providerLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
          </div>
          <div className="llm-field">
            <label htmlFor="llm-model">Model ID</label>
            <input id="llm-model" value={model} maxLength={200} autoComplete="off" spellCheck={false} placeholder="Enter a model ID" onChange={event => { setModel(event.target.value); changed(); }} />
            <a className="llm-help-link" href={modelDocs[provider]} target="_blank" rel="noreferrer">Find model IDs</a>
          </div>
          <div className="llm-field llm-field--wide">
            <label htmlFor="llm-api-key">API key</label>
            <input id="llm-api-key" type="password" value={apiKey} maxLength={2048} autoComplete="off" spellCheck={false} placeholder={profile?.key_configured ? 'Leave blank to keep the configured key' : 'Enter your provider API key'} onChange={event => { setApiKey(event.target.value); changed(); }} aria-describedby="llm-key-hint" />
            <p id="llm-key-hint">{profile?.key_configured ? 'A key is already configured for this provider.' : 'No key is configured for this provider yet.'} Saved keys stay on this computer’s backend.</p>
          </div>
          <div className="llm-actions llm-field--wide">
            <button className="llm-save" type="submit">{api.pending && api.action === 'save' ? 'Saving…' : 'Save configuration'}</button>
            <button className="llm-test" type="button" onClick={() => submit('test')}>{api.pending && api.action === 'test' ? 'Testing connection…' : 'Test connection'}</button>
          </div>
        </fieldset>
        <p className="llm-test-hint">Test connection checks credentials and model availability. It does not generate text. Save configuration keeps your selection for future reviews.</p>
      </form>
      {(inputError || api.error) && <p className="preview-error" role="alert">{inputError || api.error}</p>}
      {api.pending && <p className="llm-message" role="status">{api.action === 'test' ? 'Checking provider access…' : 'Saving configuration…'}</p>}
      {api.result?.kind === 'save' && !api.pending && <p className="llm-success" role="status">Configuration saved. Your API key is hidden.</p>}
      {api.result?.kind === 'test' && !api.pending && <div className="llm-success" role="status"><strong>Connection verified</strong><p>Model: {api.result.result.resolved_model} · {api.result.result.latency_ms} ms</p><p>Credentials accepted and model accessible. Text generation was not tested.</p></div>}
    </div>
  );
}

export function LlmSettings() {
  const [open, setOpen] = useState(false);
  return <details className="llm-settings" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary><span>LLM configuration</span><span className="llm-summary-hint">Choose a provider and test access</span></summary>
    {open && <SettingsPanel />}
  </details>;
}
