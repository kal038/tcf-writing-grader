# Exporter contract, version 1

Export one UTF-8 `.md` file per writing attempt. Start directly with `---` (no BOM,
introductory prose, or outer code fence), then a YAML mapping and a closing `---`.

```yaml
---
type: tcf-learning
schema_version: 1
task: 1
topic: invitation-au-restaurant
date: 2026-11-02
level: B2
tags: [tcf-canada, writing]
---
```

- `type`: exactly `tcf-learning`.
- `schema_version`: integer `1`; strings and booleans are rejected.
- `task`: integer `1`, `2`, or `3`.
- `topic`: lowercase ASCII letters/digits separated by single hyphens.
- `date`: real calendar date, `YYYY-MM-DD`, quoted or unquoted.
- `level`: `B1`, `B2`, `C1`, or `unknown`.
- `tags`: array of strings, possibly empty.

Duplicate YAML keys and unsafe YAML tags are rejected. Additional metadata is
allowed but never used for routing. Filenames and metadata cannot choose a vault
subdirectory. Notes over 10 MiB are left in place for manual review.

Include each of these H2 headings exactly once, with nonempty content:

```markdown
## Reusable Vocabulary and Collocations
## Reusable Grammar
## Notable Personal Mistakes
## Active Recall and Transfer
```

Headings inside fenced code blocks do not count. The personal-mistakes section
may say `No notable mistakes identified.` Do not invent mistakes to fill it.

Suggested filename: `2026-11-02-task-1-invitation.md`. Save into
`~/Downloads/TCF-Inbox/`; preferably write a hidden temporary file first, then
rename it to the final `.md` name. Three matching observations over two seconds
are required, but no stability heuristic can distinguish a finished write from
a writer paused longer than that interval.

Byte-identical exports are deduplicated per vault. If two attempts should produce
separate notes, include their distinct attempt content or metadata. The importer
preserves the original bytes. See `examples/2026-11-02-task-1-invitation.md` for a
complete accepted export.
