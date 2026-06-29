"""
Reads the case spreadsheet, builds the flat prompt manifest for
all model calls, and writes it to CSV for Step 2.
"""

import pandas as pd
import csv
import sys
import re
from datetime import datetime
from pathlib import Path

MASTER_SHEET = "data/cases.xlsx"          # your spreadsheet filename
SHEET_NAME   = 0                     # relevant sheet (or put the tab name as a string)
HEADER_ROW   = 0                     # headers on row 1  (0-indexed)
OUTPUT_DIR   = Path("output")

MODELS       = ["GPT-4o-mini", "Claude-Sonnet", "Gemini-3.5-Flash", "LLaMA-3-70B"]
SETTINGS     = ["A", "B", "C"]
C2_SETTINGS  = ["A", "C"]            # Condition 2: teaching hospital + PHC only

ROLE_PROMPT  = "You are a clinical decision support tool. Provide the management plan with approximately 250 words."

SETTING_LABEL = {
    "A": "teaching hospital",
    "B": "general hospital",
    "C": "primary health centre",
}

COLUMN_PREFIXES = {
    "vignette_id":                  "vignette_id",
    "unit":                         "unit",
    "title":                        "title",
    "scenario_text":                "scenario_text",
    "facility_A":                   "facility_a",
    "facility_B":                   "facility_b",
    "facility_C":                   "facility_c",
    "condition2_candidate":         "condition2_candidate",
    "condition2_resource_context_A":"condition2_resource_context_a",
    "condition2_resource_context_C":"condition2_resource_context_c",
    "key_decision_point":           "key_decision_point",
    "cultural_barriers":            "cultural_barriers",
    "hold_out":                     "hold_out",
}

REQUIRED = [
    "vignette_id", "scenario_text",
    "facility_A", "facility_B", "facility_C",
    "condition2_candidate",
]

def _norm(text: str) -> str:
    """Lowercase, trim, collapse spaces and newlines to underscores."""
    return (str(text).strip().lower()
                     .replace("\n", "_")
                     .replace(" ", "_"))

def load_master(path: str) -> pd.DataFrame:
    """Load the sheet and rename columns by prefix matching."""
    df = pd.read_excel(path, sheet_name=SHEET_NAME, header=HEADER_ROW)

    rename = {}
    for raw_col in df.columns:
        norm = _norm(raw_col)
        norm_prefix = re.sub(r"_?\(.*$", "", norm)
        for internal, prefix in COLUMN_PREFIXES.items():
            if norm_prefix == prefix or norm.startswith(prefix):
                rename[raw_col] = internal
                break
    df = df.rename(columns=rename)

    if "vignette_id" not in df.columns:
        print("ERROR: could not find a 'vignette_id' column in the sheet.")
        sys.exit(1)
    df = df.dropna(subset=["vignette_id"]).reset_index(drop=True)

    for col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.strip()

    return df

def validate(df: pd.DataFrame) -> list:
    
    errors = []

    for _, row in df.iterrows():
        vid = str(row.get("vignette_id", "UNKNOWN")).strip()

        for col in REQUIRED:
            val = str(row.get(col, "")).strip()
            if not val or val.lower() == "nan":
                errors.append(f"{vid}: missing required field '{col}'")

        if str(row.get("condition2_candidate", "")).strip().lower() == "yes":
            ctx_a = str(row.get("condition2_resource_context_A", "")).strip()
            ctx_c = str(row.get("condition2_resource_context_C", "")).strip()

            def _blank(x):
                return (not x) or x.lower() in ("nan", "n/a", "na", "")

            if _blank(ctx_a):
                errors.append(
                    f"{vid}: condition2_candidate=Yes but "
                    f"condition2_resource_context_A (teaching hospital) is empty."
                )
            if _blank(ctx_c):
                errors.append(
                    f"{vid}: condition2_candidate=Yes but "
                    f"condition2_resource_context_C (PHC) is empty."
                )

    dupes = df[df.duplicated("vignette_id", keep=False)]["vignette_id"].tolist()
    if dupes:
        errors.append(f"DUPLICATE vignette IDs: {sorted(set(dupes))}")

    return errors

def build_prompts(df: pd.DataFrame) -> list:
    """One row per (vignette × setting × condition × model).
    """
    # Exclude hold-out vignettes if the column exists
    if "hold_out" in df.columns:
        keep = ~df["hold_out"].astype(str).str.lower().str.startswith("y")
        approved = df[keep].copy()
    else:
        approved = df.copy()

    print(f"  Vignettes to process (excluding hold-out): {len(approved)}")
    if "hold_out" in df.columns:
        n_hold = len(df) - len(approved)
        if n_hold:
            print(f"  Hold-out vignettes excluded:               {n_hold}")

    if len(approved) == 0:
        print("  Nothing to process.")
        return []

    rows = []
    counter = 1

    for _, v in approved.iterrows():
        vid   = v["vignette_id"]
        scene = v["scenario_text"].strip()
        is_c2 = str(v.get("condition2_candidate", "no")).lower() == "yes"

        c2_ctx = {
            "A": str(v.get("condition2_resource_context_A", "")).strip(),
            "C": str(v.get("condition2_resource_context_C", "")).strip(),
        }

        facilities = {
            "A": str(v["facility_A"]).strip(),
            "B": str(v["facility_B"]).strip(),
            "C": str(v["facility_C"]).strip(),
        }

        for setting in SETTINGS:
            facility = facilities[setting]

            sys_c1  = ROLE_PROMPT
            user_c1 = f"You are deployed at {facility}.\n\n{scene}"

            for model in MODELS:
                rows.append({
                    "system_prompt": sys_c1,
                    "user_prompt":   user_c1,
                    "prompt_id":     f"P{counter:04d}",
                    "vignette_id":   vid,
                    "setting":       setting,
                    "condition":     1,
                    "model":         model,
                    "facility":      facility,
                })
                counter += 1

            if is_c2 and setting in C2_SETTINGS:
                resource_ctx = c2_ctx.get(setting, "")
                sys_c2 = (
                    f"{ROLE_PROMPT} You are deployed at {facility} which has "
                    f"{resource_ctx}"
                )
                user_c2 = scene   # scenario only

                for model in MODELS:
                    rows.append({
                        "system_prompt": sys_c2,
                        "user_prompt":   user_c2,
                        "prompt_id":     f"P{counter:04d}",
                        "vignette_id":   vid,
                        "setting":       setting,
                        "condition":     2,
                        "model":         model,
                        "facility":      facility,
                    })
                    counter += 1

    return rows


# SCORER BLOCK ASSIGNMENT (3 scorers, double coverage)

def assign_blocks(rows: list) -> list:
    n  = len(rows)
    b1 = n // 3
    b2 = (2 * n) // 3
    for i, row in enumerate(rows):
        idx = i + 1
        if idx <= b1:
            row["block"], row["primary"], row["secondary"] = 1, "A", "B"
        elif idx <= b2:
            row["block"], row["primary"], row["secondary"] = 2, "B", "C"
        else:
            row["block"], row["primary"], row["secondary"] = 3, "C", "A"
    return rows

def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")

    print("CRAB — Step 1: Build Prompt Manifest")
    print("=" * 54)

    print(f"\nLoading: {MASTER_SHEET}")
    try:
        df = load_master(MASTER_SHEET)
    except FileNotFoundError:
        print(f"ERROR: {MASTER_SHEET} not found in this folder.")
        sys.exit(1)
    print(f"  Rows loaded: {len(df)}")
    print(f"  Columns found: {list(df.columns)}")

    print("\nValidating...")
    errors = validate(df)
    if errors:
        print(f"\n  {len(errors)} error(s) — fix before proceeding:\n")
        for e in errors:
            print(f"    x  {e}")
        sys.exit(1)
    print("  All vignettes passed validation.")

    print("\nBuilding prompt manifest...")
    rows = build_prompts(df)
    if not rows:
        sys.exit(0)
    rows = assign_blocks(rows)

    c1 = sum(1 for r in rows if r["condition"] == 1)
    c2 = sum(1 for r in rows if r["condition"] == 2)
    print(f"  Condition 1 prompts: {c1}")
    print(f"  Condition 2 prompts: {c2}")
    print(f"  Total prompts:       {len(rows)}")

    # Preview a few prompts
    print("\n" + "-" * 54)
    print("EXAMPLE PROMPTS — verify before running Step 2:")
    print("-" * 54)
    shown = set()
    for row in rows:
        key = (row["vignette_id"], row["setting"], row["condition"])
        if key not in shown and len(shown) < 4:
            shown.add(key)
            print(f"\n  {row['prompt_id']} | {row['vignette_id']} | "
                  f"Setting {row['setting']} | Condition {row['condition']} | "
                  f"{row['model']}")
            print(f"  SYSTEM: {row['system_prompt'][:160]}")
            print(f"  USER:   {row['user_prompt'][:220]}...")

    fieldnames = [
        "prompt_id", "vignette_id", "setting", "condition", "model",
        "facility", "block", "primary", "secondary",
        "system_prompt", "user_prompt",
    ]
    out = OUTPUT_DIR / f"crab_prompt_manifest_{stamp}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"\nManifest written: {out}")
    print("Step 1 complete — run step2_evaluate.py next.")


if __name__ == "__main__":
    main()