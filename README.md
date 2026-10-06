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
