# TCF Evaluator v0

Build a **tiny local Python CLI** for personally grading TCF Canada Writing practice essays.

The goal is NOT to build a production application. The goal is to replace my current manual/Custom-GPT workflow with a simple local command that I can use repeatedly.

## Core workflow

```text
essay.md
   ↓
Python CLI
   ↓
OpenAI-compatible LLM API
   ↓
structured textual evaluation
   ↓
terminal + optional saved evaluation
```

I want to be able to run:

```bash
python main.py essay.md
```

and receive a useful TCF writing evaluation.

## Requirements

### 1. Input

Accept a Markdown/text essay file:

```bash
python main.py essay.md
```

Read the entire file as UTF-8.

Optionally support stdin if trivial:

```bash
cat essay.md | python main.py -
```

Do not overengineer argument parsing.

### 2. LLM API

Use the standard Python `openai` SDK.

The API should be OpenAI-compatible so the endpoint/model can be configured through environment variables.

Example:

```text
OPENAI_API_KEY
OPENAI_BASE_URL
OPENAI_MODEL
```

Do not build a provider abstraction yet.

Do not hardcode API keys.

Use low temperature / deterministic settings where supported.

The project should work with an OpenAI-compatible endpoint that I can configure to use the model/token setup I already have available through my OpenCode workflow, rather than requiring a separate application architecture.

### 3. Prompt

Put the evaluator instructions in a separate:

```text
prompt.md
```

The Python program should load this file rather than embedding a giant prompt in `main.py`.

The evaluator should behave as a strict TCF Canada Writing evaluator.

Evaluate:

- task fulfillment
- coherence/cohesion
- vocabulary/lexical range
- grammatical accuracy
- estimated CEFR level
- overall TCF writing performance

For errors, identify:

- original fragment
- correction
- category
- concise explanation

Distinguish between:

- objectively incorrect French
- awkward but acceptable French
- stylistic improvement

Do not invent errors just to produce more feedback.

Also provide:

1. estimated CEFR level
2. criterion-by-criterion justification
3. important grammar errors
4. vocabulary problems
5. cohesion/coherence problems
6. task-fulfillment problems
7. three high-priority action items for improvement
