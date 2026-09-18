"""
After scorers have completed the scoring sheet, this script
reads their scores, merges them with the raw response data,
applies the adjudication rules, and produces the master analysis dataset.

python step4_compile_scores.py --scored output/crab_scoring_sheet_YYYYMMDD.xlsx
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np

OUTPUT_DIR = Path("output")

DIMS = ["accuracy", "adaptation", "actionable", "cultural"]

# Column mapping from the scoring sheet to clean names.
# This should match the output of step3b_merge.py.
COL_MAP = {
    "response_id":              "response_id",
    "vignette_id":              "vignette_id",
    "unit":                     "unit",
    "title":                    "title",
    "setting":                  "setting",
    "condition":                "condition",
    "block":                    "block",
    "primary\nscorer":          "primary",
    "A — accuracy\n0–2":        "A_accuracy",
    "A — adaptation\n0–2":      "A_adaptation",
    "A — actionable\n0–2":      "A_actionable",
    "A — cultural\n0–1":        "A_cultural",
    "A — TOTAL\n0–7":           "A_total",
    "A — notes\n(flag C/O errors)": "A_notes",
    "B — accuracy\n0–2":        "B_accuracy",
    "B — adaptation\n0–2":      "B_adaptation",
    "B — actionable\n0–2":      "B_actionable",
    "B — cultural\n0–1":        "B_cultural",
    "B — TOTAL\n0–7":           "B_total",
    "B — notes\n(flag C/O errors)": "B_notes",
    "ADJUDICATE?\nY / N":       "adjudicate_flag",
    "adjudication\nnotes":      "adjudication_notes",
    "final_total\n(adjudicated)": "final_total_entered",
    "model_KEY\n(hidden — see key sheet)": "model",
    "C — accuracy\n0–2":        "C_accuracy",
    "C — adaptation\n0–2":      "C_adaptation",
    "C — actionable\n0–2":      "C_actionable",
    "C — cultural\n0–1":        "C_cultural",
    "C — TOTAL\n0–7":           "C_total",
    "C — notes\n(flag C/O errors)": "C_notes",
}


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def load_scored(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="Scoring", header=0)
    rename = {}
    for orig, clean in COL_MAP.items():
        for c in df.columns:
            if str(c).strip() == orig.strip():
                rename[c] = clean
    df = df.rename(columns=rename)
    df = df.dropna(subset=["response_id"]).copy()
    df = df[df["response_id"].astype(str).str.startswith("R")].copy()
    # Convert all score columns to numeric
    for scorer in ["A", "B", "C"]:
        for dim in DIMS:
            col = f"{scorer}_{dim}"
            if col in df.columns:
                df[col] = safe_numeric(df[col])
        # cnvert total columns that might exist too;
        total_col = f"{scorer}_total"
        if total_col in df.columns:
            df[total_col] = safe_numeric(df[total_col])
    return df


def compute_scorer_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute total for each scorer if not already present."""
    for scorer in ["A", "B", "C"]:
        dim_cols = [f"{scorer}_{d}" for d in DIMS]
        available = [c for c in dim_cols if c in df.columns]
        if available:
            total_col = f"{scorer}_total_computed"
            df[total_col] = df[available].sum(axis=1, min_count=len(available))
    return df


def get_scorer_pair(block: int):
    """Return tuple of two scorer letters for the given block."""
    if block == 1:
        return ("A", "B")
    elif block == 2:
        return ("B", "C")
    elif block == 3:
        return ("C", "A")
    else:
        return (None, None)


def resolve_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each row, use the appropriate scorer pair based on block.
    Compute:
      - final dimension scores (mean of two scorers)
      - final total (mean of two totals)
      - total difference (abs difference of the two totals)
      - needs_adjudication flag if difference > 1
    """
    finals = []
    diff_list = []
    need_adj = []
    final_total_list = []

    for idx, row in df.iterrows():
        block = row.get("block")
        if pd.isna(block):
            finals.append({d: np.nan for d in DIMS})
            diff_list.append(np.nan)
            need_adj.append(False)
            final_total_list.append(np.nan)
            continue

        s1, s2 = get_scorer_pair(int(block))
        if s1 is None or s2 is None:
            finals.append({d: np.nan for d in DIMS})
            diff_list.append(np.nan)
            need_adj.append(False)
            final_total_list.append(np.nan)
            continue

        # Get dimension scores for both scorers
        dim_scores = {}
        for dim in DIMS:
            c1 = f"{s1}_{dim}"
            c2 = f"{s2}_{dim}"
            v1 = row.get(c1, np.nan)
            v2 = row.get(c2, np.nan)
            # Mean of the two; if one is NaN, use the other (shouldn't happen if scoring complete)
            if pd.isna(v1) and pd.isna(v2):
                dim_scores[dim] = np.nan
            elif pd.isna(v1):
                dim_scores[dim] = v2
            elif pd.isna(v2):
                dim_scores[dim] = v1
            else:
                dim_scores[dim] = (v1 + v2) / 2.0

        # totals for each scorer (computed from their four dimensions)
        t1_col = f"{s1}_total_computed"
        t2_col = f"{s2}_total_computed"
        t1 = row.get(t1_col, np.nan)
        t2 = row.get(t2_col, np.nan)

        if pd.isna(t1):
            t1 = sum(row.get(f"{s1}_{d}", np.nan) for d in DIMS)
        if pd.isna(t2):
            t2 = sum(row.get(f"{s2}_{d}", np.nan) for d in DIMS)

        if pd.isna(t1) and pd.isna(t2):
            final_total = np.nan
        elif pd.isna(t1):
            final_total = t2
        elif pd.isna(t2):
            final_total = t1
        else:
            final_total = (t1 + t2) / 2.0

        # adjudication
        if pd.isna(t1) or pd.isna(t2):
            diff = np.nan
        else:
            diff = abs(t1 - t2)

        finals.append(dim_scores)
        diff_list.append(diff)
        need_adj.append(not pd.isna(diff) and diff > 1)
        final_total_list.append(final_total)

    # assign columns
    for dim in DIMS:
        df[f"final_{dim}"] = [d[dim] for d in finals]
    df["total_diff"] = diff_list
    df["needs_adjudication"] = need_adj
    df["final_total_raw"] = final_total_list 

    if "final_total_entered" in df.columns:
        entered = df["final_total_entered"]
        mask = pd.notna(entered) & (entered != "") & (entered != "—")
        df["final_total"] = df["final_total_raw"].copy()
        df.loc[mask, "final_total"] = entered.loc[mask]
    else:
        df["final_total"] = df["final_total_raw"]

    df = df.drop(columns=["final_total_raw"], errors="ignore")

    return df


def cohens_kappa(rater1: pd.Series, rater2: pd.Series) -> float:
    """Compute Cohen's kappa for two raters (ordinal)."""
    mask = rater1.notna() & rater2.notna()
    r1 = rater1[mask].astype(int)
    r2 = rater2[mask].astype(int)
    n = len(r1)
    if n == 0:
        return float("nan")
    labels = sorted(set(r1.tolist()) | set(r2.tolist()))
    po = (r1 == r2).sum() / n
    pe = sum(((r1 == k).sum() / n) * ((r2 == k).sum() / n) for k in labels)
    if pe == 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def reliability_report(df: pd.DataFrame) -> str:
    lines = ["CRAB Inter-Rater Reliability Report",
             "=" * 50, ""]

    # compute kappa per dimension per pair
    pairs = [(1, "A", "B"), (2, "B", "C"), (3, "C", "A")]
    all_kappas = []
    for block, s1, s2 in pairs:
        sub = df[df["block"] == block]
        if len(sub) == 0:
            continue
        lines.append(f"Pair {s1}-{s2} (block {block}, n={len(sub)}):")
        for dim in DIMS:
            c1 = f"{s1}_{dim}"
            c2 = f"{s2}_{dim}"
            if c1 in sub.columns and c2 in sub.columns:
                k = cohens_kappa(sub[c1], sub[c2])
                all_kappas.append(k)
                interp = ("poor" if k < 0.2 else "fair" if k < 0.4 else
                          "moderate" if k < 0.6 else "substantial" if k < 0.8 else
                          "almost perfect")
                lines.append(f"  {dim:<20} κ = {k:.3f}  ({interp})")
        lines.append("")

    if all_kappas:
        mean_k = np.nanmean(all_kappas)
        lines.append(f"Overall mean kappa: κ = {mean_k:.3f}")
        lines.append("")

    n_adj = df["needs_adjudication"].sum()
    n_total = len(df)
    lines.append(f"Adjudicated cases: {n_adj} ({100*n_adj/n_total:.1f}%)")
    lines.append("")

    # score distribution
    if "final_total" in df.columns:
        desc = df["final_total"].describe()
        lines.append("Score distribution (final totals):")
        lines.append(f"  Mean:    {desc['mean']:.2f} / 7")
        lines.append(f"  Median:  {desc['50%']:.1f}")
        lines.append(f"  SD:      {desc['std']:.2f}")
        lines.append(f"  Min:     {desc['min']:.1f}")
        lines.append(f"  Max:     {desc['max']:.1f}")
        lines.append("")

    # per model
    if "model" in df.columns and "final_total" in df.columns:
        lines.append("Mean score by model:")
        model_scores = df.groupby("model")["final_total"].agg(["mean", "std", "count"]).round(2)
        for model, row in model_scores.iterrows():
            lines.append(f"  {model:<25} {row['mean']:.2f} ± {row['std']:.2f}  (n={int(row['count'])})")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="CRAB Step 4 — Compile Scored Data (using all three scorers)"
    )
    parser.add_argument(
        "--scored",
        required=True,
        help="Path to completed scoring sheet Excel file"
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d")

    print("CRAB — Step 4: Compile Scored Data (three‑scorer version)")
    print("=" * 50)

    print(f"\nLoading scored sheet: {args.scored}")
    df = load_scored(args.scored)
    print(f"  Responses loaded: {len(df)}")

    print("\nComputing scorer totals...")
    df = compute_scorer_totals(df)

    print("\nResolving final scores using appropriate scorer pairs...")
    df = resolve_scores(df)

    # master dataset
    analysis_cols = [
        "response_id", "vignette_id", "unit", "title",
        "setting", "condition", "block", "model",
        "A_accuracy", "A_adaptation", "A_actionable", "A_cultural",
        "B_accuracy", "B_adaptation", "B_actionable", "B_cultural",
        "C_accuracy", "C_adaptation", "C_actionable", "C_cultural",
        "final_accuracy", "final_adaptation", "final_actionable", "final_cultural",
        "final_total",
        "needs_adjudication", "total_diff",
        "A_notes", "B_notes", "C_notes", "adjudication_notes",
    ]
    available = [c for c in analysis_cols if c in df.columns]
    master = df[available].copy()

    master_out = OUTPUT_DIR / f"crab_analysis_master_{stamp}.csv"
    master.to_csv(master_out, index=False)
    print(f"\n  Master dataset saved: {master_out}")
    print(f"  Rows: {len(master)}")

    # adjudication log
    adj_log = df[df["needs_adjudication"] == True][[
        "response_id", "vignette_id", "title", "setting", "condition", "model",
        "A_total_computed", "B_total_computed", "C_total_computed",
        "total_diff",
        "final_total", "A_notes", "B_notes", "C_notes", "adjudication_notes"
    ]].copy()
    adj_out = OUTPUT_DIR / f"crab_adjudication_log_{stamp}.csv"
    adj_log.to_csv(adj_out, index=False)
    print(f"  Adjudication log saved: {adj_out}  ({len(adj_log)} cases)")

    # reliability report
    report = reliability_report(df)
    rep_out = OUTPUT_DIR / f"crab_reliability_report_{stamp}.txt"
    with open(rep_out, "w") as f:
        f.write(report)
    print(f"  Reliability report saved: {rep_out}")

    print("\n" + "=" * 50)
    print(report)

    print("\nStep 4 complete. Ready for Step 5.")


if __name__ == "__main__":
    main()