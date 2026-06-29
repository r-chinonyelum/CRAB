"""
step3b_merge.py
---------------
Combines the three scorer files (A, B, C) into one master scoring sheet
that Step 4 can consume directly.
"""

import pandas as pd
from pathlib import Path

# ── Column name mapping (from Step 3's build_workbook col_defs) ──────
# Maps the verbose headers in the Excel to clean internal names.
VERBOSE_TO_CLEAN = {
    "response_id": "response_id",
    "vignette_id": "vignette_id",
    "unit": "unit",
    "title": "title",
    "setting\nA / B / C": "setting",
    "condition\n1 or 2": "condition",
    "block": "block",
    "response_text": "response_text",
    "accuracy\n0-2": "accuracy",
    "adaptation\n0-2": "adaptation",
    "actionable\n0-2": "actionable",
    "cultural\n0-1": "cultural",
    "TOTAL\n(I+J+K+L)": "total",
    "notes\n(C=commission, O=omission)": "notes",
}

def load_scorer_file(path: str, scorer_letter: str) -> pd.DataFrame:
    """
    Reads a scorer's Excel file, renames columns to clean names,
    then prefixes score columns with the scorer letter (e.g., A_accuracy).
    Returns a DataFrame with metadata columns + scorer-specific score columns.
    """
    xl = pd.ExcelFile(path)
    # Find the sheet that contains "Scoring"
    scoring_sheet = None
    for s in xl.sheet_names:
        if "Scoring" in s:
            scoring_sheet = s
            break
    if scoring_sheet is None:
        raise ValueError(f"No 'Scoring' sheet found in {path}")

    df = pd.read_excel(path, sheet_name=scoring_sheet, header=2, skiprows=[3])

    # 1) Map the verbose Excel headers to clean names
    df.rename(columns=VERBOSE_TO_CLEAN, inplace=True)

    # 2) Prefix score columns with the scorer letter
    #    All columns that are score dimensions or notes
    score_cols_clean = ["accuracy", "adaptation", "actionable", "cultural", "total", "notes"]
    rename_scores = {}
    for col in score_cols_clean:
        if col in df.columns:
            rename_scores[col] = f"{scorer_letter}_{col}"
    df.rename(columns=rename_scores, inplace=True)

    # 3) Keep only the metadata columns + the scorer-specific columns
    metadata_cols = ["response_id", "vignette_id", "unit", "title",
                     "setting", "condition", "block"]
    scorer_cols = [f"{scorer_letter}_{c}" for c in score_cols_clean
                   if f"{scorer_letter}_{c}" in df.columns]
    keep = metadata_cols + scorer_cols
    # Only keep columns that actually exist (some might be missing, e.g., 'unit')
    keep = [c for c in keep if c in df.columns]
    return df[keep]


# ── Load the three scorer files ──────────────────────────────────────
# Adjust file names to match your actual files.
a = load_scorer_file("crab_scoring_A_2026.xlsx", "A")
b = load_scorer_file("crab_scoring_B_2026.xlsx", "B")
c = load_scorer_file("crab_scoring_C_2026.xlsx", "C")

# ── Merge the pairs (A+B, B+C, C+A) ──────────────────────────────────
# Each pair shares the same response_id for the overlapping blocks.
# We merge only on response_id and keep the metadata from the left frame.
ab = pd.merge(a, b, on="response_id", how="inner", suffixes=("", "_drop"))
bc = pd.merge(b, c, on="response_id", how="inner", suffixes=("", "_drop"))
ca = pd.merge(c, a, on="response_id", how="inner", suffixes=("", "_drop"))

# Combine all three blocks
combined = pd.concat([ab, bc, ca], ignore_index=True)
# Remove any "_drop" columns that came from the right DataFrame's metadata
combined = combined.loc[:, ~combined.columns.str.endswith("_drop")]

# ── Attach model identities ──────────────────────────────────────────
# Step 3's model key file has sheet "Model Key"
key = pd.read_excel("output/crab_model_key_20260603.xlsx", sheet_name="Model Key", header=1)
# Keep only response_id and model
key = key[["response_id", "model"]].drop_duplicates()
combined = pd.merge(combined, key, on="response_id", how="left")

# ── Add the adjudication placeholder columns required by Step 4 ─────
combined["adjudicate_flag"] = ""
combined["adjudication_notes"] = ""
combined["final_total_entered"] = ""

# ── Reorder columns to match Step 4's expected layout (optional) ───
# The exact order isn't critical as Step 4 uses a mapping.
first_cols = [
    "response_id", "vignette_id", "unit", "title",
    "setting", "condition", "block",
    "A_accuracy", "A_adaptation", "A_actionable", "A_cultural", "A_total", "A_notes",
    "B_accuracy", "B_adaptation", "B_actionable", "B_cultural", "B_total", "B_notes",
    "adjudicate_flag", "adjudication_notes", "final_total_entered", "model"
]
# Keep only columns that exist
first_cols = [c for c in first_cols if c in combined.columns]
# Add any remaining columns at the end
other_cols = [c for c in combined.columns if c not in first_cols]
combined = combined[first_cols + other_cols]

# ── Save the master scoring sheet ────────────────────────────────────
combined.to_excel("master_scoring_sheet.xlsx",
                  sheet_name="Scoring",
                  index=False)

print(f"Master scoring sheet saved with {len(combined)} responses.")
print(f"Columns: {list(combined.columns)}")