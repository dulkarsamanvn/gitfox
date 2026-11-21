import { useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { normalizePrUrl, skipReasons } from '../api/pullRequests';
import type { PrPreview as PreviewData } from '../api/pullRequests';
import { usePrPreview } from '../hooks/usePrPreview';

function PreviewResults({ data }: { data: PreviewData }) {
  const { metadata: pr, selection } = data;
  const state = pr.merged ? 'Merged' : pr.state === 'open' ? 'Open' : 'Closed';
  return (
    <section className="preview-results" aria-labelledby="preview-result-title">
      <div className="preview-result-heading">
        <div>
          <p className="preview-repository">{pr.owner}/{pr.repository} <span>#{pr.pr_number}</span></p>
          <h2 id="preview-result-title">{pr.title}</h2>
          <p className="preview-author">{pr.author ? `Opened by ${pr.author}` : 'Author unavailable'}</p>
        </div>
        <div className="preview-result-links">
          <span className={`pr-state pr-state--${state.toLowerCase()}`}>{state}</span>
          <a href={pr.pr_url} target="_blank" rel="noreferrer">View on GitHub</a>
        </div>
      </div>

      <dl className="preview-totals">
        <div><dt>Changed files</dt><dd>{selection.files_seen}</dd></div>
        <div><dt>Selected for review</dt><dd>{selection.files_selected}</dd></div>
        <div><dt>Skipped files</dt><dd>{selection.files_skipped}</dd></div>
        <div><dt>Patch characters</dt><dd>{selection.patch_chars.toLocaleString()}</dd></div>
      </dl>

      <details className="commit-details">
        <summary>Commit details</summary>
        <dl><div><dt>Base</dt><dd><code>{pr.base_sha}</code></dd></div><div><dt>Head</dt><dd><code>{pr.head_sha}</code></dd></div></dl>
      </details>

      <div className="preview-file-section">
        <h3>Selected files ({selection.files_selected})</h3>
        {selection.selected.length === 0 && (
          <p className="preview-notice">{selection.files_seen === 0
            ? 'This pull request has no changed files.'
            : 'No patches were selected. Check the skipped-file reasons below.'}</p>
        )}
        {selection.selected.map(file => (
          <details className="preview-file" key={file.filename}>
            <summary>
              <code>{file.filename}</code>
              <span className="file-status">{file.status}</span>
              <span className="file-counts"><span>+{file.additions} added</span> / −{file.deletions} removed</span>
            </summary>
            {file.previous_filename && <p className="previous-filename">Previous path: <code>{file.previous_filename}</code></p>}
            <pre tabIndex={0} aria-label={`Patch for ${file.filename}`}><code>{file.patch}</code></pre>
          </details>
        ))}
      </div>

      <div className="preview-file-section">
        <h3>Skipped files ({selection.files_skipped})</h3>
        {selection.skipped.length === 0
          ? <p className="preview-notice">No files were skipped.</p>
          : <ul className="skipped-files">{selection.skipped.map(file => (
            <li key={file.filename}>
              <code>{file.filename}</code>
              <p>{skipReasons[file.reason]}</p>
              {file.previous_filename && <p>Previous path: <code>{file.previous_filename}</code></p>}
            </li>
          ))}</ul>}
      </div>
    </section>
  );
}

export function PrPreview() {
  const [url, setUrl] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const preview = usePrPreview();
  const error = validationError || preview.error;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (preview.pending) return;
    const normalized = normalizePrUrl(url);
    if (!normalized) {
      preview.reset();
      setValidationError('Enter an HTTPS GitHub PR URL, such as https://github.com/owner/repository/pull/123.');
      input.current?.focus();
      return;
    }
    setValidationError(null);
    setUrl(normalized);
    preview.submit(normalized);
  }

  function cancel() {
    preview.reset();
    requestAnimationFrame(() => input.current?.focus());
  }

  return (
    <section className="pr-preview" aria-labelledby="pr-preview-title">
      <div className="preview-intro">
        <p className="eyebrow">PULL REQUEST PREVIEW</p>
        <h1 id="pr-preview-title">See what changed.</h1>
        <p>Inspect a pull request’s files, available patches, and selection coverage.</p>
      </div>

      <form className="preview-form" onSubmit={handleSubmit} noValidate>
        <label htmlFor="pr-url">GitHub pull request URL</label>
        <div className="preview-form-controls">
          <input
            ref={input} id="pr-url" type="url" inputMode="url" value={url} maxLength={2048}
            placeholder="https://github.com/owner/repository/pull/123"
            autoComplete="off" autoCapitalize="none" spellCheck={false}
            disabled={preview.pending} aria-invalid={Boolean(validationError)}
            aria-describedby={`pr-url-hint${error ? ' pr-preview-error' : ''}`}
            onChange={event => {
              setUrl(event.target.value);
              setValidationError(null);
              preview.reset();
            }}
          />
          <button className="preview-submit" type="submit" disabled={preview.pending}>
            {preview.pending ? 'Fetching preview…' : 'Preview PR'}
          </button>
          {preview.pending && <button className="preview-cancel" type="button" onClick={cancel}>Cancel preview</button>}
        </div>
        <p id="pr-url-hint" className="preview-hint">Public repositories only. This previews changes for a later review.</p>
        {error && <p id="pr-preview-error" className="preview-error" role="alert">{error}</p>}
      </form>

      {preview.pending && (
        <div className="preview-progress" role="status">
          <span className="preview-spinner" aria-hidden="true" />
          <div><p>Fetching pull request details and changed files…</p><span>Large pull requests may take up to a minute.</span></div>
        </div>
      )}
      {preview.data && !preview.pending && <>
        <p className="visually-hidden" role="status">Preview ready. {preview.data.selection.files_selected} files selected, {preview.data.selection.files_skipped} skipped.</p>
        <PreviewResults data={preview.data} />
      </>}
      {!preview.data && !preview.pending && !error && <div className="preview-empty">Your PR details and file changes will appear here.</div>}
    </section>
  );
}
