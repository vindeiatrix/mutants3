Instruction Header (for Assistant when generating a Codex task)

Author the task in strict, deterministic form. Use unified diff patches with ample context (no “insert above/below” prose). Provide exact file paths. Only modify files explicitly patched. Keep edits idempotent and avoid any unrelated refactors or formatting.

Output must follow this structure, in order:

Task Title — one line.

Preconditions — assumptions (branch, paths, tools).

Patches — one or more fenced blocks with diff unified patches (*** a/... → --- b/..., with @@ hunks). Prefer replacing whole functions/blocks.

New Files — if any; full file contents in fenced code blocks.

Fallback — only if needed; include regex-anchored replacements or full-file replacements for each file whose patch might fail to apply.

Acceptance Criteria — concrete, observable checks (behavior + simple grep checks).

Smoke Test (Terminal) — exact commands to validate quickly (non-interactive when possible).

Constraints:

Do not be creative: no extra changes, no reformatting, no renames.

Preserve encoding/line endings; no trailing whitespace.

Do not touch files not listed.

If something is ambiguous, assume minimal change consistent with the task intent.

Style reference: Match the format used in “Task: Fix room header resolution (store-aware + price substitution) and keep store_id nullable”—i.e., clear title, preconditions, diff patches, optional fallback, acceptance criteria, and a smoke test.
