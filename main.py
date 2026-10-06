#!/usr/bin/env python3
"""TCF Writing Evaluator CLI - Evaluates French practice essays against TCF Canada criteria."""

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv
from openai import OpenAI


def get_default_prompt_path() -> Path:
    """Returns the default prompt.md path located in the same directory as this script."""
    return Path(__file__).resolve().parent / "prompt.md"


def read_input(file_arg: str | None) -> str:
    """Reads essay content from file path or stdin."""
    if file_arg == "-" or (file_arg is None and not sys.stdin.isatty()):
        content = sys.stdin.read()
    elif file_arg:
        path = Path(file_arg)
        if not path.is_file():
            sys.exit(f"Error: File not found: {file_arg}")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            sys.exit(f"Error reading {file_arg}: UTF-8 decoding failed ({e})")
    else:
        sys.exit(
            "Error: No input essay provided.\n"
            "Usage: python main.py <essay.md> or 'cat essay.md | python main.py -'"
        )

    content = content.strip()
    if not content:
        sys.exit("Error: Essay input is empty.")
    return content


def load_evaluator_prompt(prompt_path: Path) -> str:
    """Loads system instructions from prompt file."""
    if not prompt_path.is_file():
        sys.exit(f"Error: Prompt file not found at '{prompt_path}'.")
    return prompt_path.read_text(encoding="utf-8").strip()


def main() -> None:
    # Load environment variables from .env if present
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Grade TCF Canada Writing practice essays using an OpenAI-compatible LLM."
    )
    parser.add_argument(
        "essay",
        nargs="?",
        default=None,
        help="Path to markdown/text essay file, or '-' to read from stdin",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Optional file path to save the evaluation result (e.g., evaluation.md)",
        default=None,
    )
    parser.add_argument(
        "-m",
        "--model",
        help="Model name (overrides OPENAI_MODEL env var, default: gpt-4o)",
        default=None,
    )
    parser.add_argument(
        "-p",
        "--prompt",
        help="Path to custom prompt file (default: prompt.md next to main.py)",
        default=None,
    )
    parser.add_argument(
        "-t",
        "--temperature",
        type=float,
        default=0.1,
        help="Sampling temperature (default: 0.0 for deterministic evaluation)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming output to the terminal",
    )

    args = parser.parse_args()

    # Read essay content
    essay_text = read_input(args.essay)

    # Determine and load prompt
    prompt_file = Path(args.prompt) if args.prompt else get_default_prompt_path()
    system_prompt = load_evaluator_prompt(prompt_file)

    # Environment configuration
    api_key = os.environ.get("OPENAI_API_KEY")
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    model = args.model or os.environ.get("OPENAI_MODEL") or "gpt-4o"

    if not api_key:
        sys.exit(
            "Error: OPENAI_API_KEY is not set.\n"
            "Please export OPENAI_API_KEY in your environment or provide it in a .env file."
        )

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Voici ma production écrite pour le TCF Canada à évaluer :\n\n---\n{essay_text}\n---",
        },
    ]

    try:
        if args.no_stream:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=args.temperature,
            )
            output_text = response.choices[0].message.content or ""
            print(output_text)
        else:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=args.temperature,
                stream=True,
            )
            collected_chunks = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content if chunk.choices else None
                if delta:
                    sys.stdout.write(delta)
                    sys.stdout.flush()
                    collected_chunks.append(delta)
            output_text = "".join(collected_chunks)
            if not output_text.endswith("\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()

        # Save to output file if requested
        if args.output:
            out_path = Path(args.output)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(output_text, encoding="utf-8")
            print(f"\n[Evaluation saved to {args.output}]", file=sys.stderr)

    except KeyboardInterrupt:
        sys.exit("\nEvaluation cancelled by user.")
    except Exception as e:
        sys.exit(f"\nAPI Error: {e}")


if __name__ == "__main__":
    main()
