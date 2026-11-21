import axios from 'axios';
import { apiClient } from './client';

export const skipReasons = {
  generated_file: 'Generated or dependency file',
  lock_file: 'Dependency lockfile',
  binary_file: 'Binary file type',
  unsupported_file_type: 'Unsupported file type',
  missing_patch: 'No readable patch was provided',
  patch_too_large: 'Patch exceeds the per-file size limit',
  invalid_patch: 'Patch format is invalid',
  incomplete_patch: 'Patch appears incomplete',
  no_text_changes: 'No text changes in the patch',
  file_limit_exceeded: 'Selected-file limit reached',
  patch_budget_exceeded: 'Patch does not fit the remaining size budget',
} as const;

type FileStatus = 'added' | 'removed' | 'modified' | 'renamed' | 'copied' | 'changed' | 'unchanged';
type FileMetadata = {
  filename: string;
  previous_filename: string | null;
  status: FileStatus;
  additions: number;
  deletions: number;
  changes: number;
};
export type SelectedFile = FileMetadata & { patch: string };
export type SkippedFile = FileMetadata & { reason: keyof typeof skipReasons };
export type PrPreview = {
  metadata: {
    owner: string;
    repository: string;
    pr_number: number;
    pr_url: string;
    title: string;
    author: string | null;
    state: 'open' | 'closed';
    merged: boolean;
    base_sha: string;
    head_sha: string;
    changed_files: number;
  };
  selection: {
    selected: SelectedFile[];
    skipped: SkippedFile[];
    files_seen: number;
    files_selected: number;
    files_skipped: number;
    patch_chars: number;
  };
};

const invalidResponse = 'The server returned an unexpected preview. Please try again.';
const errorMessages: Record<string, string> = {
  invalid_pr_url: 'Enter a valid public GitHub pull request URL.',
  invalid_request: 'The preview request was not accepted. Check the URL and try again.',
  request_too_large: 'The preview request is too large. Enter only the pull request URL.',
  unsupported_media_type: 'The server could not read the preview request. Please try again.',
  github_not_found: 'Pull request not found. Check the URL and make sure the repository is public.',
  github_private_repository: 'Private repositories are not supported. Use a public pull request.',
  github_forbidden: 'GitHub denied access to this pull request.',
  github_rate_limited: 'GitHub’s rate limit has been reached. Please try again later.',
  github_auth_failed: 'GitHub access is unavailable on the server. Please try again later.',
  github_unavailable: 'GitHub is temporarily unavailable. Please try again later.',
  github_timeout: 'GitHub took too long to respond. Please try again.',
  github_redirect: 'This repository has moved. Use its current pull request URL.',
  github_too_many_files: 'This pull request exceeds the supported limit of 300 changed files.',
  github_response_too_large: 'This pull request’s data exceeds the supported size limit.',
  github_pr_changed: 'New changes arrived while fetching this PR. Preview it again.',
  github_incomplete_files: 'GitHub returned an incomplete file list. Please try again.',
  github_invalid_response: invalidResponse,
  github_request_failed: 'GitHub could not return this pull request. Please try again.',
};

// Match the backend's canonical public-PR syntax. The server remains authoritative.
export function normalizePrUrl(input: string): string | null {
  const value = input.trim();
  const prefix = 'https://github.com/';
  if (value.length > 2048 || value.slice(0, prefix.length).toLowerCase() !== prefix) return null;
  const match = value.slice(prefix.length).match(
    /^([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\/([A-Za-z0-9_.-]{1,100})\/pull\/([1-9][0-9]{0,9})\/?$/,
  );
  if (!match || match[1].length > 39 || ['.', '..'].includes(match[2]) || Number(match[3]) > 2_147_483_647) return null;
  return `${prefix}${match[1]}/${match[2]}/pull/${match[3]}`;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function count(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function relativePath(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 && !/[\\\x00-\x1f\x7f]/.test(value)
    && !/^[A-Za-z]:/.test(value) && !value.split('/').some(part => ['', '.', '..'].includes(part));
}

function fileMetadata(value: unknown): value is FileMetadata {
  return record(value) && relativePath(value.filename)
    && (value.previous_filename === null || relativePath(value.previous_filename))
    && typeof value.status === 'string'
    && ['added', 'removed', 'modified', 'renamed', 'copied', 'changed', 'unchanged'].includes(value.status)
    && (value.status !== 'renamed' || typeof value.previous_filename === 'string')
    && count(value.additions) && count(value.deletions) && count(value.changes)
    && value.changes === value.additions + value.deletions;
}

function validPreview(value: unknown, requestedUrl: string): value is PrPreview {
  if (!record(value) || !record(value.metadata) || !record(value.selection)) return false;
  const { metadata: meta, selection } = value;
  if (typeof meta.owner !== 'string' || typeof meta.repository !== 'string'
    || !count(meta.pr_number) || meta.pr_number === 0 || typeof meta.pr_url !== 'string'
    || normalizePrUrl(meta.pr_url) !== meta.pr_url
    || meta.pr_url.toLowerCase() !== requestedUrl.toLowerCase()
    || meta.pr_url !== `https://github.com/${meta.owner}/${meta.repository}/pull/${meta.pr_number}`
    || typeof meta.title !== 'string' || !meta.title
    || !(meta.author === null || typeof meta.author === 'string')
    || typeof meta.state !== 'string' || !['open', 'closed'].includes(meta.state) || typeof meta.merged !== 'boolean'
    || typeof meta.base_sha !== 'string' || !/^[0-9a-f]{40}$/.test(meta.base_sha)
    || typeof meta.head_sha !== 'string' || !/^[0-9a-f]{40}$/.test(meta.head_sha)
    || !count(meta.changed_files) || meta.changed_files > 300) return false;
  if (!Array.isArray(selection.selected) || !Array.isArray(selection.skipped)
    || selection.selected.length + selection.skipped.length > 300) return false;
  let patchChars = 0;
  const filenames = new Set<string>();
  for (const file of selection.selected) {
    if (!fileMetadata(file) || !('patch' in file) || typeof file.patch !== 'string' || !file.patch || file.patch.length > 200_000
      || filenames.has(file.filename)) return false;
    // Python counts Unicode code points; JS string.length counts UTF-16 units.
    const chars = Array.from(file.patch).length;
    if (chars > 100_000) return false;
    patchChars += chars;
    filenames.add(file.filename);
  }
  for (const file of selection.skipped) {
    if (!fileMetadata(file) || !('reason' in file) || typeof file.reason !== 'string'
      || !Object.hasOwn(skipReasons, file.reason) || 'patch' in file || filenames.has(file.filename)) return false;
    filenames.add(file.filename);
  }
  return count(selection.files_seen) && selection.files_seen === meta.changed_files
    && selection.files_seen === filenames.size
    && selection.files_selected === selection.selected.length
    && selection.files_skipped === selection.skipped.length
    && selection.patch_chars === patchChars && patchChars <= 200_000;
}

export async function fetchPrPreview(prUrl: string, signal: AbortSignal): Promise<PrPreview> {
  try {
    const response = await apiClient.post<unknown>(
      '/api/v1/pull-requests/preview', { pr_url: prUrl }, { signal, timeout: 70_000 },
    );
    if (!validPreview(response.data, prUrl)) throw new Error(invalidResponse);
    return response.data;
  } catch (error) {
    if (axios.isCancel(error)) throw error;
    if (axios.isAxiosError(error)) {
      if (error.code === 'ETIMEDOUT' || error.code === 'ECONNABORTED') {
        throw new Error('The preview timed out. Please try again.');
      }
      const data: unknown = error.response?.data;
      if (record(data) && record(data.detail) && typeof data.detail.code === 'string'
        && Object.hasOwn(errorMessages, data.detail.code)) {
        throw new Error(errorMessages[data.detail.code]);
      }
      if (error.response && (error.response.status < 200 || error.response.status >= 300)) {
        throw new Error(`The preview could not be completed (HTTP ${error.response.status}). Please try again.`);
      }
      if (error.code === 'ERR_BAD_RESPONSE' || error.response) throw new Error(invalidResponse);
      throw new Error('Could not reach GitFox. Make sure the backend is running and try again.');
    }
    throw error;
  }
}
