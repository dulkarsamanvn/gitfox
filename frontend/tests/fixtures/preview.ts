import type { PrPreview } from '../../src/api/pullRequests';

export function previewFixture(number = 42): PrPreview {
  const selected: PrPreview['selection']['selected'] = [
    {
      filename: 'src/users.py', previous_filename: null, status: 'modified',
      additions: 1, deletions: 1, changes: 2,
      patch: '@@ -1 +1 @@\n-return users[0]\n+return users[0] if users else None',
    },
    {
      filename: 'frontend/profile.tsx', previous_filename: 'frontend/user.tsx', status: 'renamed',
      additions: 1, deletions: 1, changes: 2,
      patch: '@@ -1 +1 @@\n-oldName\n+newName',
    },
  ];
  return {
    metadata: {
      owner: 'example', repository: 'project', pr_number: number,
      pr_url: `https://github.com/example/project/pull/${number}`,
      title: 'Guard empty user lists', author: 'contributor', state: 'open', merged: false,
      base_sha: 'a'.repeat(40), head_sha: 'b'.repeat(40), changed_files: 3,
    },
    selection: {
      selected,
      skipped: [{ filename: 'logo.png', previous_filename: null, status: 'modified',
        additions: 0, deletions: 0, changes: 0, reason: 'binary_file' }],
      files_seen: 3, files_selected: 2, files_skipped: 1,
      patch_chars: selected.reduce((total, file) => total + Array.from(file.patch).length, 0),
    },
  };
}
