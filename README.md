# TCF learning-note importer

A local Linux importer for Markdown notes exported by your ChatGPT plugin. The
existing API-backed evaluator remains available below and is unchanged. Importing
requires no API key, network service, root privileges, or Obsidian plugin.

## Install and configure

Requires Python 3.11+, a virtualenv-capable Python installation, and optionally
`notify-send` (libnotify) for desktop notifications. From this project directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/tcf-importer setup
```

Setup asks for your **existing** Obsidian vault directory. It never creates a
vault, imports notes, or enables a service. It saves
`~/.config/tcf-importer/config.toml` and creates the configured inbox, quarantine,
and state directories. An existing configuration is validated and preserved;
edit it directly to change settings. `config.example.toml` lists all defaults.
The vault path is intentionally blank until you supply it.

Paths must not overlap or pass through symlink directories. Keep the project,
inbox, vault, and state directory under your own account's control. Importer
state is private to your user. Separate configurations must not share an inbox
or vault while using different state directories.

## Commands

```bash
.venv/bin/tcf-importer validate examples/2026-11-02-task-1-invitation.md
.venv/bin/tcf-importer dry-run examples/2026-11-02-task-1-invitation.md
.venv/bin/tcf-importer import ~/Downloads/TCF-Inbox/lesson.md
.venv/bin/tcf-importer watch
.venv/bin/tcf-importer status
.venv/bin/tcf-importer --config /path/to/config.toml status
```

`validate` does not require configuration. `dry-run` requires an existing configured
vault but writes nothing; its proposed filename is advisory until import.
`import` consumes its source after persistence, including files outside the inbox;
never point it at a sample you intend to retain. Files inside the vault, quarantine,
or state directory are refused as sources. Exit codes: 0 success, 1 invalid note,
2 operational/configuration error, 130 keyboard interruption.

Valid notes go to `TCF Canada/Writing/Learnings/Task-1/` (or Task-2/Task-3).
Safe filenames are preserved; unsafe characters are replaced, long names are
shortened, and collisions receive numbered suffixes. Nothing is overwritten.
Invalid stable notes go to quarantine with a `.reason.json` diagnostic. Correct
the rejected note and save a new copy into the inbox to retry.

## Background service — opt in explicitly

```bash
./scripts/install.sh
```

This installs the package into this project's `.venv`, renders a user service
with its absolute executable path, and reloads the user daemon. **It does not
enable or start anything.** Run setup first. When you decide to enable imports:

```bash
systemctl --user enable --now tcf-importer.service
systemctl --user status tcf-importer.service
journalctl --user -u tcf-importer.service
```

No `sudo` is used. Moving the project requires rerunning installation. Installing
an update does not restart an already running watcher; restart it explicitly.
The user service normally runs while your user session exists; this project does
not enable lingering. To remove the service:

```bash
./scripts/uninstall.sh
```

Uninstallation explicitly stops/disables the service and preserves notes,
configuration, state, and the virtualenv.

Notifications require a desktop notification daemon and a usable user-session
D-Bus environment. SSH sessions, headless sessions, and user managers outside an
active graphical session may not display them. Notification failure is logged
and never rolls back a successful import. Set `notifications = false` to disable.

## Durability and recovery

The watcher scans at startup, reacts to filesystem events, and reconciles every
30 seconds by default. It ignores hidden files, temporary names, and symlinks.
Changing files are deferred. Prefer saving with a temporary-file rename: a long
pause during a write can otherwise look like completion.

Copies are staged and fsynced inside the destination directory, then published
with a no-overwrite hard link and directory fsync. Inbox and vault can be on
different filesystems. The destination filesystem must support hard links and
file/directory fsync; unsupported or full filesystems leave the source in place.
No source-to-vault rename is used. Persistence precedes source deletion.

Atomic JSON receipts under `log_dir/receipts` record pending and committed
transactions. A matching destination recovers a crash after publication but
before source deletion. Receipts deduplicate identical bytes across filenames;
a missing or edited destination is not treated as a duplicate. Preserve receipts
if you want this history retained. Do not manually move/edit published notes
while an import is in progress. Process locks coordinate instances sharing state.
Source identity and content are checked before cleanup; like other pathname-based
Linux tools, the importer assumes files are not maliciously replaced during the
final check/unlink window.

Operational failures retain sources and are retried. Invalid notes are quarantined
with stable content-based names so interrupted quarantine operations can resume.
Logs rotate at 2 MB with three backups. `status` shows pending files, service state,
and recent errors. An abrupt kill can leave hidden `.tcf-stage-*` or `.tcf-json-*`
files; these are ignored and may be removed manually after stopping the importer.

See [exporter contract v1](docs/exporter-contract-v1.md) and the
[sample note](examples/2026-11-02-task-1-invitation.md).

## Tests

```bash
.venv/bin/python -m pytest -q
```

Tests use temporary directories, mocked notifications, fault injection, and an
actual second filesystem when `/dev/shm` is available. They do not use your vault
or enable services. The existing evaluator tests are included.

---

# TCF Evaluator CLI

A lightweight local Python CLI tool to evaluate French practice essays for **TCF Canada Writing** (*Épreuve d'expression écrite*) using an OpenAI-compatible LLM endpoint.

---

## Features

- **Strict TCF Canada evaluation** based on official FEI / CEFR (CECRL) standards:
  - Task fulfillment (*Respect de la consigne*)
  - Coherence & cohesion (*Cohérence et cohésion*)
  - Lexical range & accuracy (*Compétence lexicale*)
  - Grammatical accuracy & morphosyntax (*Compétence grammaticale*)
- **Granular error classification**:
  - 🔴 **Erreur objective** (grammatical / agreement / conjugation errors)
  - 🟡 **Tournure maladroite** (awkward phrasing / calques / anglicisms)
  - 🔵 **Amélioration stylistique** (refinements for higher CEFR band)
- **Estimated CEFR level** (A1 to C2 / TCF Niveaux 1 à 6).
- **3 high-priority action items** for targeted improvement.
- **Configurable prompt**: System instructions reside in `prompt.md` and can be customized or swapped.
- **OpenAI-compatible**: Works with OpenAI, OpenCode, OpenRouter, Ollama, vLLM, or any compatible provider.
- **Streaming response**: Real-time output in the terminal with optional file saving.

---

## Setup

### 1. Install dependencies

```bash
# Create and activate virtual environment (if not already done)
python3 -m venv .venv
source .venv/bin/activate

# Install requirements
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your API configuration:

```env
OPENAI_API_KEY=your_api_key_here

# Optional: Custom OpenAI-compatible base URL (e.g. OpenCode, OpenRouter, LocalAI)
# OPENAI_BASE_URL=https://api.openai.com/v1

# Optional: Model name (defaults to gpt-4o)
# OPENAI_MODEL=gpt-4o
```

---

## Usage

### Basic Usage

Evaluate a Markdown or text essay:

```bash
python main.py sample_essay.md
```

### Using Stdin / Pipe

Pipe text directly into the CLI:

```bash
cat sample_essay.md | python main.py -
```

or simply:

```bash
cat sample_essay.md | python main.py
```

### Save Evaluation to a File

Save the resulting markdown evaluation while streaming to the terminal:

```bash
python main.py sample_essay.md -o evaluation.md
```

### CLI Options

```text
usage: main.py [-h] [-o OUTPUT] [-m MODEL] [-p PROMPT] [-t TEMPERATURE] [--no-stream] [essay]

positional arguments:
  essay                 Path to markdown/text essay file, or '-' to read from stdin

options:
  -h, --help            Show this help message and exit
  -o, --output OUTPUT   Optional file path to save the evaluation result (e.g., evaluation.md)
  -m, --model MODEL     Model name (overrides OPENAI_MODEL env var, default: gpt-4o)
  -p, --prompt PROMPT   Path to custom prompt file (default: prompt.md next to main.py)
  -t, --temperature T   Sampling temperature (default: 0.0 for deterministic evaluation)
  --no-stream           Disable streaming output to the terminal
```
