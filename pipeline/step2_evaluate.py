"""
Reads the prompt manifest from Step 1, calls each model API,
and writes every response to a CSV. Safe to interrupt and resume —
already-completed responses are skipped on restart.

Run:
  python step2_evaluate.py --manifest output/crab_prompt_manifest_YYYYMMDD.csv
  python step2_evaluate.py --manifest output/crab_prompt_manifest_YYYYMMDD.csv --models GPT-4o-mini Claude-Sonnet
  python step2_evaluate.py --manifest output/crab_prompt_manifest_YYYYMMDD.csv --dry-run
  python step2_evaluate.py --manifest output/crab_prompt_manifest_YYYYMMDD.csv --models Claude-Sonnet --resume output/crab_raw_responses_YYYYMMDD_HHMM.csv
"""

import os
import csv
import time
import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

def get_openai():
    import openai
    return openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def get_anthropic():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

def get_gemini():
    from google import genai
    return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

def get_together():
    from together import Together
    return Together(api_key=os.environ["TOGETHER_API_KEY"])

OUTPUT_DIR   = Path("output")
MAX_TOKENS   = 800       # Safety ceiling as instruction targets ~250 words
TEMPERATURE  = 0         
RETRY_LIMIT  = 3
RETRY_DELAY  = 5         
RATE_DELAY   = 1.2       

# provider must be one of: openai | anthropic | gemini | together
MODEL_SPECS = {
    "GPT-4o-mini": {
        "provider": "openai",
        "model_id": "gpt-4o-mini",
    },
    "Claude-Sonnet": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6",
    },
    "Gemini-Flash": {
        "provider": "gemini",
        "model_id": "gemini-3.5-flash",
    },
    "LLaMA-3-70B": {
        "provider": "together",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    },
}

def call_openai(client, model_id: str, system: str, user: str) -> str:
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    return resp.choices[0].message.content.strip()


def call_anthropic(client, model_id: str, system: str, user: str) -> str:
    resp = client.messages.create(
        model=model_id,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text.strip()

def call_gemini(client, model_id: str, system: str, user: str) -> str:
    from google.genai import types
    full_prompt = f"{system}\n\n{user}"
    resp = client.models.generate_content(
        model=model_id,
        contents=full_prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return resp.text.strip()


def call_together(client, model_id: str, system: str, user: str) -> str:
    resp = client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
    )
    return resp.choices[0].message.content.strip()


def call_model(model_name: str, system: str, user: str,
               clients: dict) -> tuple[str, str]:
    spec = MODEL_SPECS.get(model_name)
    if not spec:
        return "", f"Unknown model: {model_name}"

    provider = spec["provider"]
    model_id = spec["model_id"]

    for attempt in range(1, RETRY_LIMIT + 1):
        try:
            if provider == "openai":
                text = call_openai(clients["openai"], model_id, system, user)
            elif provider == "anthropic":
                text = call_anthropic(clients["anthropic"], model_id, system, user)
            elif provider == "gemini":
                text = call_gemini(clients["gemini"], model_id, system, user)
            elif provider == "together":
                text = call_together(clients["together"], model_id, system, user)
            else:
                return "", f"Unknown provider: {provider}"
            return text, ""

        except Exception as e:
            err = str(e)
            if attempt < RETRY_LIMIT:
                print(f"      Attempt {attempt} failed: {err[:80]}. "
                      f"Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            else:
                return "", err

    return "", "All retries exhausted"

def load_completed(responses_path: Path) -> set:
    """Return set of prompt_ids already successfully completed."""
    if not responses_path.exists():
        return set()
    done = set()
    with open(responses_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            error = row.get("error", "")
            response = row.get("response", "")
            # Only count as complete if no error and response is not empty
            if (not error or error.strip() == "") and response.strip():
                done.add(row["prompt_id"])
    return done

def init_clients(models_to_run: list, dry_run: bool) -> dict:
    clients = {}
    if dry_run:
        return clients

    providers_needed = {
        MODEL_SPECS[m]["provider"]
        for m in models_to_run
        if m in MODEL_SPECS
    }

    if "openai" in providers_needed:
        if not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY not set.")
            sys.exit(1)
        clients["openai"] = get_openai()
        print("  OpenAI client ready.")

    if "anthropic" in providers_needed:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ERROR: ANTHROPIC_API_KEY not set.")
            sys.exit(1)
        clients["anthropic"] = get_anthropic()
        print("  Anthropic client ready.")

    if "gemini" in providers_needed:
        if not os.environ.get("GOOGLE_API_KEY"):
            print("ERROR: GOOGLE_API_KEY not set.")
            sys.exit(1)
        clients["gemini"] = get_gemini()
        print("  Gemini client ready.")

    if "together" in providers_needed:
        if not os.environ.get("TOGETHER_API_KEY"):
            print("ERROR: TOGETHER_API_KEY not set.")
            sys.exit(1)
        clients["together"] = get_together()
        print("  Together (LLaMA) client ready.")

    return clients

def main():
    parser = argparse.ArgumentParser(
        description="CRAB Step 2 — Model Evaluation"
    )
    parser.add_argument(
        "--manifest", required=True,
        help="Path to prompt manifest CSV from Step 1"
    )
    parser.add_argument(
        "--models", nargs="+",
        default=list(MODEL_SPECS.keys()),
        choices=list(MODEL_SPECS.keys()),
        help="Which models to run (default: all four)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print prompts without calling any API"
    )
    parser.add_argument(
        "--resume", metavar="RESPONSES_FILE",
        help="Append to this existing responses file, skipping completed prompt_ids"
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    print("CRAB — Step 2: Model Evaluation")
    print("=" * 50)

    manifest = pd.read_csv(args.manifest)
    manifest = manifest[manifest["model"].isin(args.models)].reset_index(drop=True)
    print(f"\nPrompts loaded: {len(manifest)}")
    print(f"Models: {', '.join(args.models)}")

    responses_path = (Path(args.resume) if args.resume
                      else OUTPUT_DIR / f"crab_raw_responses_{stamp}.csv")

    completed = load_completed(responses_path)
    if completed:
        print(f"Resuming — {len(completed)} already complete, skipping.")

    remaining = manifest[~manifest["prompt_id"].isin(completed)]
    print(f"To run: {len(remaining)} prompts")

    if len(remaining) == 0:
        print("Nothing to run — all prompts already complete.")
        return

    # Dry run to preview prompts without calling APIs
    if args.dry_run:
        print("\nDRY RUN — first 3 prompts:")
        for _, row in remaining.head(3).iterrows():
            print(f"\n  [{row['prompt_id']}] {row['vignette_id']} "
                  f"S{row['setting']} C{row['condition']} {row['model']}")
            print(f"  SYSTEM: {row['system_prompt'][:150]}...")
            print(f"  USER:   {row['user_prompt'][:200]}...")
        print("\nDry run complete. No API calls made.")
        return

    print("\nInitialising API clients...")
    clients = init_clients(args.models, args.dry_run)

    write_header = not responses_path.exists()
    fieldnames = [
        "response_id", "prompt_id", "vignette_id",
        "setting", "condition", "model", "facility",
        "block", "primary_scorer", "secondary_scorer",
        "system_prompt", "user_prompt",
        "response", "tokens_approx",
        "call_timestamp", "duration_s", "error",
    ]

    success_count = 0
    error_count   = 0
    response_counter = len(completed) + 1

    with open(responses_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if write_header:
            writer.writeheader()

        for i, (_, row) in enumerate(remaining.iterrows()):
            pid    = row["prompt_id"]
            model  = row["model"]
            system = row["system_prompt"]
            user   = row["user_prompt"]

            print(f"  [{i+1}/{len(remaining)}] "
                  f"{row['vignette_id']} S{row['setting']} "
                  f"C{row['condition']} {model}")

            t0 = time.time()
            response_text, error_msg = call_model(model, system, user, clients)
            duration = round(time.time() - t0, 2)

            if error_msg:
                print(f"    x ERROR: {error_msg[:100]}")
                error_count += 1
            else:
                success_count += 1

            writer.writerow({
                "response_id":     f"R{response_counter:04d}",
                "prompt_id":        pid,
                "vignette_id":      row["vignette_id"],
                "setting":          row["setting"],
                "condition":        row["condition"],
                "model":            model,
                "facility":         row.get("facility", ""),
                "block":            row.get("block", ""),
                "primary_scorer":   row.get("primary", ""),
                "secondary_scorer": row.get("secondary", ""),
                "system_prompt":    system,
                "user_prompt":      user,
                "response":         response_text,
                "tokens_approx":    (round(len(response_text.split()) * 1.3)
                                     if response_text else 0),
                "call_timestamp":   datetime.now().isoformat(),
                "duration_s":       duration,
                "error":            error_msg,
            })

            f.flush()  
            response_counter += 1

            if not error_msg:
                time.sleep(RATE_DELAY)

    print(f"\n{'='*50}")
    print(f"  Evaluation complete.")
    print(f"  Successful responses: {success_count}")
    print(f"  Errors:               {error_count}")
    print(f"  Output file:          {responses_path}")
    if error_count > 0:
        print(f"\n  Re-run with --resume {responses_path} to retry failed calls.")
    print("\nStep 2 complete. Run step3_build_scoring_sheet.py next.")


if __name__ == "__main__":
    main()