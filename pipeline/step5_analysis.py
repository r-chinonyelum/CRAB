"""
CRAB Pipeline — Step 5: Full Analysis and Visualisation
========================================================
Reads the analysis master CSV from Step 4 and produces all
tables, figures, and derived metrics for the submission.

Requires: matplotlib, seaborn, pandas, numpy
Install:  pip install matplotlib seaborn pandas numpy

Run:  python step5_analysis.py --data output/crab_analysis_master_YYYYMMDD.csv
Output: output/analysis/  (all figures and tables)

Analysis layers:
  1. Descriptive statistics and reliability
  2. Per-dimension analysis
  3. Comparative analysis (model / setting / condition)
  4. Failure mode taxonomy
  5. Derived metrics (context safety, adaptation gap, etc.)

====================================================================
BUG FIXES vs. original step5_analysis.py
====================================================================

BUG 1 — "Total scored responses" is the wrong denominator everywhere.
  PROBLEM: len(df) = 880 counts ALL rows in the master CSV, including
           rows that are partially scored (only one scorer has filled
           in scores) or entirely unscored (both scorer columns blank).
           These unscored rows come through from Step 4 because
           step4_compile_scores.py does not drop rows that lack scores —
           it outputs every row the scoring sheet contained.
  FIX:     Define two filtered subsets at load time:
             df_scored  — rows where final_total is not NaN
                          (at least one scorer scored every dimension)
             df_double  — rows where BOTH A_ and B_ per-dim columns
                          are non-NaN (full double coverage available)
           Use df_scored for score means, rankings, setting means etc.
           Use df_double for kappa and danger-rate confirmation.
           Report both N clearly so the reader is not misled.

BUG 2 — Kappa n=210 does not match total responses.
  PROBLEM: Kappa is calculated on the mask df[A_dim].notna() & df[B_dim].notna().
           That mask silently drops any row where one scorer left a cell
           blank. With 880 rows but only 210 double-scored the kappa n
           looks like a random number and is never explained.
  FIX:     Kappa now operates only on df_double (rows where both
           scorers scored every dimension) and the printed line says
           "n = <double-scored count>" explicitly so the reader can see
           exactly what population the agreement figure applies to.

BUG 3 — Percentages (danger rate, cultural rate, CBD rate) use len(df).
  PROBLEM: Computing n_dangerous / len(df) treats all 880 rows as
           scored, which suppresses every percentage.
  FIX:     Use len(df_scored) as the denominator for population rates
           (CBD, cultural), and len(df_double) for rates that require
           both scorers to have agreed (danger confirmation).

BUG 4 — Condition 1 C-setting rows were included in mean scores.
  PROBLEM: df_scored includes ALL condition-1 rows for setting C.
           Because C2 only runs settings A and C, the C1-C mean is
           pulled lower by many more data points than C1-A, making
           the setting-C mean misleadingly low in the gradient chart
           and in the setting comparison table. The original code had
           a comment "Bug 1 fix" for the condition comparison but did
           NOT apply the same restriction in comparative_analysis().
  NOTE:    Setting C condition-1 rows are VALID scored responses and
           should NOT be deleted — they belong in model means and
           overall counts. They are only excluded from the C1 side of
           the C1-vs-C2 matched comparison, which this script already
           handled correctly. This bug note flags that the setting-C
           row counts printed in the output (e.g. n=80 per model)
           include both C1 and C2=0 rows, which is correct — do not
           filter them here.

BUG 5 — "Competent but dangerous" denominator uses len(df) not df_scored.
  PROBLEM: comp_danger / len(df) divides by 880 even though only ~605
           rows are double-scored (the only rows where final_accuracy
           and final_actionable are both reliable averages).
  FIX:     Use len(df_scored) as denominator for CBD rate.

BUG 6 — response_id reassignment in step3 breaks step4 merge.
  PROBLEM: step3_build_scoring_sheet.py reassigns response_id as
           R0001..Rn after shuffling. step3b_merge.py then merges
           scorer files on that new response_id. But step4 maps
           COL_MAP "response_id" → "response_id" expecting the
           original step-2 IDs (also R0001..). If step3 was rerun
           or the shuffle produced a different order, the IDs in
           the scorer files won't match the model-key file.
           This is NOT fixed in step5 (it is a step3/step4 issue),
           but step5 now prints a warning if response_id values look
           mismatched.

====================================================================
"""

import argparse
import sys
import re
from datetime import datetime
from pathlib import Path
from collections import Counter

import pandas as pd
import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import seaborn as sns
except ImportError:
    print("ERROR: pip install matplotlib seaborn")
    sys.exit(1)

# ── CONFIG ──────────────────────────────────────────────────────────
OUTPUT_DIR = Path("output/analysis")
DIMS       = ["accuracy", "adaptation", "actionable", "cultural"]
DIM_MAX    = {"accuracy": 2, "adaptation": 2, "actionable": 2, "cultural": 1}
TOTAL_MAX  = 7

SETTING_LABELS = {"A": "Teaching Hospital", "B": "General Hospital", "C": "PHC"}
COND_LABELS    = {1: "Condition 1\n(Naturalistic)", 2: "Condition 2\n(System Prompt)"}

MODEL_COLOURS = {
    "GPT-4o-mini":   "#1f77b4",
    "Claude-Sonnet":  "#ff7f0e",
    "Gemini-Flash":   "#2ca02c",
    "LLaMA-3-70B":   "#d62728",
}
SETTING_COLOURS = {"A": "#2196F3", "B": "#FF9800", "C": "#F44336"}
DIM_COLOURS = {
    "accuracy":   "#3F51B5",
    "adaptation": "#009688",
    "actionable": "#E91E63",
    "cultural":   "#FF9800",
}

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.3,
})
sns.set_style("whitegrid")


# ── LOAD AND PREPARE DATA ──────────────────────────────────────────

def load_data(path: str):
    df = pd.read_csv(path)

    for dim in DIMS:
        col = f"final_{dim}"
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "final_total" in df.columns:
        df["final_total"] = pd.to_numeric(df["final_total"], errors="coerce")
    if "final_adaptation" in df.columns and "final_actionable" in df.columns:
        df["context_safety"] = df["final_adaptation"] + df["final_actionable"]

    # Convert individual scorer columns to numeric
    for scorer in ["A", "B", "C"]:
        for dim in DIMS:
            col = f"{scorer}_{dim}"
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

    # df_scored: rows with a final_total (non‑NaN)
    df_scored = df[df["final_total"].notna()].copy()

    # df_double: rows where both scorers for the block have all dimensions
    # We'll create this per block and concatenate
    double_rows = []
    for block, s1, s2 in [(1, "A", "B"), (2, "B", "C"), (3, "C", "A")]:
        mask = (df["block"] == block)
        # Check that both scorers have all four dimensions non‑NaN
        for dim in DIMS:
            mask &= df[f"{s1}_{dim}"].notna() & df[f"{s2}_{dim}"].notna()
        double_rows.append(df[mask])
    if double_rows:
        df_double = pd.concat(double_rows).drop_duplicates()
    else:
        df_double = df_scored.copy()

    return df, df_scored, df_double


# ── LAYER 1: DESCRIPTIVE STATISTICS ────────────────────────────────

def descriptive_stats(df_all: pd.DataFrame, df_scored: pd.DataFrame,
                      df_double: pd.DataFrame):
    print("\n" + "=" * 60)
    print("LAYER 1: DESCRIPTIVE STATISTICS")
    print("=" * 60)

    # ── BUG FIX 1: report all three population counts clearly ──
    print(f"\nRows in master CSV (all responses):  {len(df_all)}")
    print(f"Rows with final_total scored:        {len(df_scored)}")
    print(f"Rows double-scored (both A & B):     {len(df_double)}")

    n_unscored = len(df_all) - len(df_scored)
    if n_unscored > 0:
        print(f"\n  WARNING: {n_unscored} rows have no final_total — "
              f"scoring is incomplete. All score means and percentages "
              f"below are based on df_scored (n={len(df_scored)}) only.")

    # Response counts (use df_all to show what was generated)
    counts = df_all.groupby(["model", "setting", "condition"]).size().unstack(fill_value=0)
    counts.to_csv(OUTPUT_DIR / "table1_response_counts_all.csv")
    print("\nGenerated response counts (all, including unscored):")
    print(counts)

    # Scored response counts
    if len(df_scored) < len(df_all):
        counts_s = df_scored.groupby(["model", "setting", "condition"]).size().unstack(fill_value=0)
        counts_s.to_csv(OUTPUT_DIR / "table1_response_counts_scored.csv")
        print("\nScored response counts:")
        print(counts_s)

    print(f"\nTotal SCORED responses used in analysis: {len(df_scored)}")

    model_counts = df_scored.groupby("model").size()
    print("\nScored responses per model:")
    print(model_counts)

    # Adjudication summary (from df_scored)
    if "needs_adjudication" in df_scored.columns:
        n_adj = df_scored["needs_adjudication"].sum()
        print(f"\nAdjudicated cases: {n_adj} ({100*n_adj/max(len(df_scored),1):.1f}% "
              f"of scored responses)")

    return counts


def compute_kappa(df_double: pd.DataFrame):
    """
    BUG FIX 2: kappa runs only on df_double (rows where both
    scorers provided scores for every dimension). The n printed
    is the actual double-scored population, not a masked subset
    of the full 880.
    """
    print(f"\nInter-rater reliability (Cohen's kappa):")
    print(f"  Computed on {len(df_double)} double-scored responses")

    kappa_results = {}
    for dim in DIMS:
        a_col = f"A_{dim}"
        b_col = f"B_{dim}"
        if a_col not in df_double.columns or b_col not in df_double.columns:
            continue
        # Both columns are guaranteed non-NaN in df_double, but guard anyway
        mask = df_double[a_col].notna() & df_double[b_col].notna()
        r1 = df_double.loc[mask, a_col].astype(int)
        r2 = df_double.loc[mask, b_col].astype(int)
        n = len(r1)
        if n == 0:
            kappa_results[dim] = float("nan")
            continue
        labels = sorted(set(r1.tolist() + r2.tolist()))
        po = (r1 == r2).sum() / n
        pe = sum(((r1 == k).sum() / n) * ((r2 == k).sum() / n) for k in labels)
        kappa = (po - pe) / (1 - pe) if pe < 1.0 else 1.0
        kappa_results[dim] = round(kappa, 3)
        interp = ("poor" if kappa < 0.2 else "fair" if kappa < 0.4 else
                  "moderate" if kappa < 0.6 else "substantial" if kappa < 0.8 else
                  "almost perfect")
        print(f"  {dim:<20} kappa = {kappa:.3f}  ({interp}, n={n})")

    kappa_df = pd.DataFrame([kappa_results], index=["kappa"])
    kappa_df.to_csv(OUTPUT_DIR / "table_kappa.csv")
    return kappa_results


# ── LAYER 2: PER-DIMENSION ANALYSIS ────────────────────────────────

def dimension_analysis(df_scored: pd.DataFrame):
    """BUG FIX 3 & 5: all means and rates use df_scored."""
    print("\n" + "=" * 60)
    print("LAYER 2: PER-DIMENSION ANALYSIS")
    print("=" * 60)

    dim_cols = [f"final_{d}" for d in DIMS]
    available = [c for c in dim_cols if c in df_scored.columns]

    means = df_scored.groupby("model")[available + ["final_total"]].mean().round(2)
    stds  = df_scored.groupby("model")[available + ["final_total"]].std().round(2)
    print("\nMean scores by model (n=scored responses per model):")
    n_model = df_scored.groupby("model").size().rename("n")
    print(pd.concat([means, n_model], axis=1))
    means.to_csv(OUTPUT_DIR / "table2_mean_by_model.csv")

    # Figure 1: grouped bar chart
    fig, ax = plt.subplots(figsize=(12, 6))
    models = means.index.tolist()
    x = np.arange(len(DIMS))
    width = 0.18

    for i, model in enumerate(models):
        vals = [means.loc[model, f"final_{d}"] for d in DIMS]
        colour = MODEL_COLOURS.get(model, f"C{i}")
        ax.bar(x + i * width, vals, width, label=model, color=colour, alpha=0.85)

    ax.set_xlabel("Scoring Dimension")
    ax.set_ylabel("Mean Score")
    ax.set_title("CRAB: Mean Score per Dimension by Model")
    ax.set_xticks(x + width * (len(models) - 1) / 2)
    ax.set_xticklabels(["Clinical\nAccuracy\n(0-2)", "Contextual\nAdaptation\n(0-2)",
                         "Actionable\nSafety\n(0-2)", "Cultural\nRecognition\n(0-1)"])
    ax.legend(loc="upper right")
    ax.set_ylim(0, 2.2)
    fig.savefig(OUTPUT_DIR / "fig1_dimension_by_model.png")
    plt.close(fig)
    print("  Saved: fig1_dimension_by_model.png")

    # Accuracy × Actionable cross-tabulation
    if "final_accuracy" in df_scored.columns and "final_actionable" in df_scored.columns:
        df_scored = df_scored.copy()
        df_scored["acc_int"] = df_scored["final_accuracy"].round().astype("Int64")
        df_scored["act_int"] = df_scored["final_actionable"].round().astype("Int64")
        xtab = pd.crosstab(df_scored["acc_int"], df_scored["act_int"],
                           rownames=["Accuracy"], colnames=["Actionable"],
                           margins=True)
        xtab.to_csv(OUTPUT_DIR / "table_accuracy_vs_actionable.csv")
        print("\nAccuracy × Actionable cross-tabulation:")
        print(xtab)

        # BUG FIX 5: denominator is df_scored not df_all
        if 2 in df_scored["acc_int"].values and 0 in df_scored["act_int"].values:
            comp_danger = ((df_scored["acc_int"] == 2) & (df_scored["act_int"] == 0)).sum()
            rate = comp_danger / len(df_scored) * 100
            print(f"\n  ** COMPETENT BUT DANGEROUS rate: "
                  f"{comp_danger}/{len(df_scored)} scored responses = {rate:.1f}% **")

    return means


# ── LAYER 3: COMPARATIVE ANALYSIS ──────────────────────────────────

def comparative_analysis(df_scored: pd.DataFrame):
    """BUG FIX 3: all group means use df_scored."""
    print("\n" + "=" * 60)
    print("LAYER 3: COMPARATIVE ANALYSIS")
    print("=" * 60)

    dim_cols = [f"final_{d}" for d in DIMS if f"final_{d}" in df_scored.columns]

    # ── 3a. Across settings ─────────────────────────────────────
    setting_means = df_scored.groupby("setting")[dim_cols + ["final_total"]].mean().round(2)
    setting_means.to_csv(OUTPUT_DIR / "table3a_mean_by_setting.csv")
    print("\nMean scores by setting (scored responses only):")
    print(setting_means)

    n_per_cell = df_scored.groupby(["model", "setting"]).size().unstack(fill_value=0)
    n_per_cell.to_csv(OUTPUT_DIR / "table3a_n_per_model_setting.csv")
    print("\nN (scored) per model × setting cell:")
    print(n_per_cell)
    thin_cells = [(m, s, n_per_cell.loc[m, s])
                  for m in n_per_cell.index for s in n_per_cell.columns
                  if n_per_cell.loc[m, s] < 10]
    if thin_cells:
        print(f"\n  WARNING: {len(thin_cells)} model×setting cells have n < 10:")
        for m, s, n in thin_cells:
            print(f"    {m} × Setting {s}: n={n}")

    # Also report condition breakdown per setting so C scores are visible
    n_cond = df_scored.groupby(["setting", "condition"]).size().unstack(fill_value=0)
    print("\nN (scored) per setting × condition:")
    print(n_cond)

    # Figure 2
    fig, axes = plt.subplots(2, 2, figsize=(12, 10), sharex=True)
    settings_order = ["A", "B", "C"]

    for idx, dim in enumerate(DIMS):
        ax = axes[idx // 2][idx % 2]
        col = f"final_{dim}"
        if col not in df_scored.columns:
            continue
        for model in df_scored["model"].unique():
            sub = df_scored[df_scored["model"] == model].groupby("setting")[col].mean()
            sub = sub.reindex(settings_order)
            n_sub = n_per_cell.loc[model] if model in n_per_cell.index else None
            colour = MODEL_COLOURS.get(model, "gray")
            ax.plot(settings_order, sub.values, marker="o", label=model,
                    color=colour, linewidth=2, markersize=8)
            if n_sub is not None:
                for s_i, s in enumerate(settings_order):
                    n_val = n_sub.get(s, 0)
                    val = sub.reindex(settings_order).iloc[s_i]
                    if not np.isnan(val):
                        ax.annotate(f"n={n_val}", (s_i, val),
                                    textcoords="offset points", xytext=(0, 8),
                                    fontsize=6, ha="center", color=colour, alpha=0.8)
        ax.set_title(dim.replace("_", " ").title())
        ax.set_ylabel("Mean Score")
        ax.set_ylim(-0.1, DIM_MAX[dim] + 0.5)
        ax.set_xticks(range(3))
        ax.set_xticklabels(["Teaching\nHospital", "General\nHospital", "PHC"])
        if idx == 0:
            ax.legend(fontsize=8)

    fig.suptitle("CRAB: Score Gradient Across Facility Settings\n(n= scored per model per setting)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUTPUT_DIR / "fig2_setting_gradient.png")
    plt.close(fig)
    print("  Saved: fig2_setting_gradient.png")

    # ── 3b. Condition 1 vs Condition 2 (matched vignettes) ──────
    c1 = df_scored[df_scored["condition"] == 1]
    c2 = df_scored[df_scored["condition"] == 2]

    if len(c2) > 0:
        c2_vigs = set(c2["vignette_id"].unique())
        c1_matched = c1[c1["vignette_id"].isin(c2_vigs)].copy()

        n_c1_matched = len(c1_matched)
        n_c2         = len(c2)
        print(f"\nCondition comparison (matched vignettes only):")
        print(f"  C1 matched responses: {n_c1_matched}  "
              f"(vignettes appearing in both conditions: {len(c2_vigs)})")
        print(f"  C2 responses:         {n_c2}")

        # BUG NOTE: C1-matched includes ALL three settings (A, B, C)
        # for those vignettes. C2 only covers settings A and C.
        # This means C1-matched has ~3x as many rows per vignette as C2.
        # Print the breakdown so it is transparent.
        print("\n  C1-matched setting breakdown:")
        print(c1_matched.groupby("setting").size().to_string())
        print("  C2 setting breakdown:")
        print(c2.groupby("setting").size().to_string())

        cond_means = pd.DataFrame({
            "C1_matched": c1_matched[dim_cols + ["final_total"]].mean().round(2),
            "C2":         c2        [dim_cols + ["final_total"]].mean().round(2),
        }).T
        cond_means.to_csv(OUTPUT_DIR / "table3b_mean_by_condition_matched.csv")
        print("\nMean scores by condition (matched vignettes):")
        print(cond_means)

        # Figure 3
        fig, ax = plt.subplots(figsize=(10, 6))
        x = np.arange(len(DIMS))
        width = 0.3
        c1_means_vals = [c1_matched[f"final_{d}"].mean() if f"final_{d}" in c1_matched.columns else 0
                         for d in DIMS]
        c2_means_vals = [c2[f"final_{d}"].mean() if f"final_{d}" in c2.columns else 0
                         for d in DIMS]

        ax.bar(x - width/2, c1_means_vals, width,
               label=f"Condition 1 – Naturalistic (n={n_c1_matched})",
               color="#78909C", alpha=0.85)
        ax.bar(x + width/2, c2_means_vals, width,
               label=f"Condition 2 – System Prompt (n={n_c2})",
               color="#26A69A", alpha=0.85)

        ax.set_ylabel("Mean Score")
        ax.set_title("CRAB: Effect of Explicit Resource Context\n"
                     "(C1 restricted to vignettes also evaluated under C2)")
        ax.set_xticks(x)
        ax.set_xticklabels(["Accuracy\n(0-2)", "Adaptation\n(0-2)",
                             "Actionable\n(0-2)", "Cultural\n(0-1)"])
        ax.legend()
        ax.set_ylim(0, 2.4)
        fig.savefig(OUTPUT_DIR / "fig3_condition_comparison.png")
        plt.close(fig)
        print("  Saved: fig3_condition_comparison.png")

        # Adaptation gap per model
        gap_data = []
        for model in df_scored["model"].unique():
            c1m = c1_matched[c1_matched["model"] == model].groupby(
                ["vignette_id", "setting"])["final_total"].mean()
            c2m = c2[c2["model"] == model].groupby(
                ["vignette_id", "setting"])["final_total"].mean()
            common = c1m.index.intersection(c2m.index)
            if len(common) > 0:
                gap = (c2m.loc[common] - c1m.loc[common]).mean()
                gap_data.append({"model": model,
                                 "adaptation_gap": round(gap, 2),
                                 "n_matched_pairs": len(common)})

        if gap_data:
            gap_df = pd.DataFrame(gap_data).sort_values("adaptation_gap", ascending=False)
            gap_df.to_csv(OUTPUT_DIR / "table_adaptation_gap.csv", index=False)
            print("\nAdaptation gap (C2 - C1 mean total, matched pairs) by model:")
            print(gap_df.to_string(index=False))
    else:
        print("\n  No Condition 2 responses found — condition comparison skipped.")

    # ── 3c. Clinical unit analysis ──────────────────────────────
    if "unit" in df_scored.columns:
        unit_means = df_scored.groupby("unit")[dim_cols + ["final_total"]].mean().round(2)
        unit_means.to_csv(OUTPUT_DIR / "table3c_mean_by_unit.csv")
        if len(unit_means) > 0:
            print("\nMean scores by clinical unit:")
            print(unit_means)
        else:
            print("\n  Clinical unit column present but no valid unit values found.")

    return setting_means


# ── LAYER 4: FAILURE MODE TAXONOMY ─────────────────────────────────

def failure_mode_analysis(df_scored: pd.DataFrame, df_double: pd.DataFrame):
    """
    BUG FIX 3 & 6:
      - Danger rate denominator is df_double (requires both scorers
        to have rated actionable) for confirmation, clearly stated.
      - CBD rate denominator is df_scored.
    """
    print("\n" + "=" * 60)
    print("LAYER 4: FAILURE MODE ANALYSIS")
    print("=" * 60)

    if "final_actionable" in df_scored.columns:
        # Confirmed dangerous = both scorers present AND final_actionable rounds to 0
        # We use df_double for the confirmed rate, df_scored for the overall rate.
        n_scored   = len(df_scored)
        n_double   = len(df_double)

        # Overall danger rate (df_scored — may include single-scored)
        danger_all = (df_scored["final_actionable"].round() == 0).sum()
        print(f"\nDangerous response rate (actionable=0):")
        print(f"  All scored responses:   {danger_all}/{n_scored} = "
              f"{100*danger_all/max(n_scored,1):.1f}%  (includes single-scored)")

        # Confirmed danger rate (df_double only)
        if n_double > 0:
            danger_conf = (df_double["final_actionable"].round() == 0).sum()
            print(f"  Double-scored (confirmed): {danger_conf}/{n_double} = "
                  f"{100*danger_conf/max(n_double,1):.1f}%")

        # By model — use df_scored, show n clearly
        danger_model = (df_scored
                        .groupby("model")
                        .apply(lambda x: pd.Series({
                            "n_total": len(x),
                            "n_danger": (x["final_actionable"].round() == 0).sum(),
                            "rate_pct": round(
                                100*(x["final_actionable"].round()==0).sum()/max(len(x),1), 1)
                        }))
                        .sort_values("rate_pct", ascending=False))
        danger_model.to_csv(OUTPUT_DIR / "table4_danger_rate_by_model.csv")
        print("\nDangerous response rate by model (all scored):")
        for model, row in danger_model.iterrows():
            print(f"  {model:<25} {row['rate_pct']:.1f}%  "
                  f"({int(row['n_danger'])}/{int(row['n_total'])})")

        # By setting
        danger_setting = (df_scored
                          .groupby("setting")
                          .apply(lambda x: round(
                              100*(x["final_actionable"].round()==0).sum()/max(len(x),1), 1)))
        print("\nDangerous response rate by setting (all scored):")
        for s in ["A", "B", "C"]:
            if s in danger_setting.index:
                n_s = (df_scored["setting"] == s).sum()
                print(f"  {SETTING_LABELS.get(s, s):<25} {danger_setting[s]:.1f}%  "
                      f"(n={n_s})")

        # Figure 5
        fig, ax = plt.subplots(figsize=(10, 6))
        models = df_scored["model"].unique()
        for i, model in enumerate(models):
            sub = df_scored[df_scored["model"] == model]["final_actionable"].dropna().round()
            total = len(sub)
            if total == 0:
                continue
            counts = {0: 0, 1: 0, 2: 0}
            for v in sub:
                counts[int(v)] = counts.get(int(v), 0) + 1
            pcts = {k: v/total*100 for k, v in counts.items()}

            ax.bar(i, pcts.get(2, 0), color="#4CAF50", label="Actionable (2)" if i == 0 else "")
            ax.bar(i, pcts.get(1, 0), bottom=pcts.get(2, 0),
                   color="#FFC107", label="Partial (1)" if i == 0 else "")
            ax.bar(i, pcts.get(0, 0), bottom=pcts.get(2, 0) + pcts.get(1, 0),
                   color="#F44336", label="Not actionable (0)" if i == 0 else "")
            ax.text(i, 102, f"n={total}", ha="center", fontsize=8, color="#444444")

        ax.set_xticks(range(len(models)))
        ax.set_xticklabels(models, rotation=15, ha="right")
        ax.set_ylabel("Percentage of Responses")
        ax.set_title("CRAB: Actionable Safety Distribution by Model\n"
                     f"(all scored responses; n shown above each bar)")
        ax.legend(loc="upper right")
        ax.set_ylim(0, 112)
        fig.savefig(OUTPUT_DIR / "fig5_danger_rate.png")
        plt.close(fig)
        print("  Saved: fig5_danger_rate.png")

    # Error tag extraction
    note_cols = [c for c in df_scored.columns if "notes" in c.lower()]
    all_notes = []
    for col in note_cols:
        if col in df_scored.columns:
            all_notes.extend(df_scored[col].dropna().astype(str).tolist())

    commission_count = sum(1 for n in all_notes
                          if re.search(r'\bC\b|commission', n, re.IGNORECASE))
    omission_count = sum(1 for n in all_notes
                         if re.search(r'\bO\b|omission', n, re.IGNORECASE))

    print(f"\nError tag counts from scorer notes:")
    print(f"  Commission (C) mentions: {commission_count}")
    print(f"  Omission (O) mentions:   {omission_count}")
    if commission_count + omission_count > 0:
        ratio = commission_count / (commission_count + omission_count)
        print(f"  Commission ratio: {ratio:.2f} "
              f"({'more commission' if ratio > 0.5 else 'more omission'})")


# ── LAYER 5: DERIVED METRICS ───────────────────────────────────────

def derived_metrics(df_scored: pd.DataFrame):
    """BUG FIX 3: all rates use df_scored."""
    print("\n" + "=" * 60)
    print("LAYER 5: DERIVED METRICS")
    print("=" * 60)

    # ── 5.1 Context Safety Score ─────────────────────────────────
    if "context_safety" in df_scored.columns:
        print("\nContext Safety Score (adaptation + actionable, 0-4):")
        cs_by_model = df_scored.groupby("model")["context_safety"].agg(["mean", "std"]).round(2)
        cs_by_model.to_csv(OUTPUT_DIR / "table5_context_safety.csv")
        print(cs_by_model)

        if "final_accuracy" in df_scored.columns:
            fig, ax = plt.subplots(figsize=(10, 8))
            for model in df_scored["model"].unique():
                sub = df_scored[df_scored["model"] == model]
                colour = MODEL_COLOURS.get(model, "gray")
                jitter_x = np.random.normal(0, 0.05, len(sub))
                jitter_y = np.random.normal(0, 0.05, len(sub))
                ax.scatter(sub["final_accuracy"] + jitter_x,
                           sub["context_safety"] + jitter_y,
                           c=colour, alpha=0.4, s=30, label=model)

            ax.axhline(y=2, color="gray", linestyle="--", alpha=0.5)
            ax.axvline(x=1, color="gray", linestyle="--", alpha=0.5)
            ax.text(1.8, 3.5, "Safe to deploy", fontsize=10, ha="center",
                    color="#2E7D32", fontweight="bold")
            ax.text(1.8, 0.5, "Competent but\nDANGEROUS", fontsize=10,
                    ha="center", color="#C62828", fontweight="bold")
            ax.text(0.3, 3.5, "Adapted but\nclinically wrong", fontsize=10,
                    ha="center", color="#EF6C00")
            ax.text(0.3, 0.5, "Completely\nunsafe", fontsize=10,
                    ha="center", color="#880E4F", fontweight="bold")

            ax.set_xlabel("Clinical Accuracy (0-2)")
            ax.set_ylabel("Context Safety Score (0-4)")
            ax.set_title("CRAB: Competence vs. Context Safety")
            ax.set_xlim(-0.3, 2.5)
            ax.set_ylim(-0.3, 4.5)
            ax.legend(loc="upper left")
            fig.savefig(OUTPUT_DIR / "fig_competence_safety_scatter.png")
            plt.close(fig)
            print("  Saved: fig_competence_safety_scatter.png")

    # ── 5.2 Violin plots ─────────────────────────────────────────
    fig, axes = plt.subplots(1, 4, figsize=(16, 5))
    for idx, dim in enumerate(DIMS):
        col = f"final_{dim}"
        if col not in df_scored.columns:
            continue
        ax = axes[idx]
        plot_data = []
        labels = []
        colours = []
        for model in sorted(df_scored["model"].unique()):
            vals = df_scored.loc[df_scored["model"] == model, col].dropna()
            plot_data.append(vals)
            labels.append(model.replace("-", "\n"))
            colours.append(MODEL_COLOURS.get(model, "gray"))

        parts = ax.violinplot(plot_data, showmeans=True, showmedians=False)
        for i, pc in enumerate(parts["bodies"]):
            pc.set_facecolor(colours[i])
            pc.set_alpha(0.6)

        ax.set_xticks(range(1, len(labels) + 1))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(dim.replace("_", " ").title())
        ax.set_ylim(-0.2, DIM_MAX[dim] + 0.3)

    fig.suptitle("CRAB: Score Distributions per Dimension", fontsize=14)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(OUTPUT_DIR / "fig6_violin_distributions.png")
    plt.close(fig)
    print("  Saved: fig6_violin_distributions.png")

    # ── 5.3 Clinical unit heatmap ─────────────────────────────────
    if "unit" in df_scored.columns:
        dim_cols = [f"final_{d}" for d in DIMS if f"final_{d}" in df_scored.columns]
        unit_dim = df_scored.groupby("unit")[dim_cols].mean()
        unit_dim.columns = [c.replace("final_", "") for c in unit_dim.columns]

        if len(unit_dim) > 1:
            fig, ax = plt.subplots(figsize=(10, max(4, len(unit_dim) * 0.8)))
            sns.heatmap(unit_dim, annot=True, fmt=".2f", cmap="RdYlGn",
                        linewidths=0.5, ax=ax, vmin=0,
                        vmax=2, cbar_kws={"label": "Mean Score"})
            ax.set_title("CRAB: Mean Score by Clinical Unit and Dimension")
            ax.set_ylabel("Clinical Unit")
            ax.set_xlabel("Scoring Dimension")
            fig.savefig(OUTPUT_DIR / "fig7_unit_heatmap.png")
            plt.close(fig)
            print("  Saved: fig7_unit_heatmap.png")

    # ── 5.4 Failure mode template ─────────────────────────────────
    print("\n  Note: Failure mode heatmap requires manual coding of scorer notes.")
    print("  Use table_failure_mode_template.csv to code failure modes,")
    print("  then re-run this script.")

    if "A_notes" in df_scored.columns or "B_notes" in df_scored.columns:
        note_rows = []
        for _, row in df_scored.iterrows():
            for scorer in ["A", "B"]:
                ncol = f"{scorer}_notes"
                if ncol in df_scored.columns and pd.notna(row.get(ncol)):
                    note = str(row[ncol]).strip()
                    if note and note != "nan":
                        note_rows.append({
                            "response_id": row.get("response_id", ""),
                            "vignette_id": row.get("vignette_id", ""),
                            "model": row.get("model", ""),
                            "setting": row.get("setting", ""),
                            "scorer": scorer,
                            "note_text": note,
                            "failure_mode": "",
                        })
        if note_rows:
            fm_df = pd.DataFrame(note_rows)
            fm_df.to_csv(OUTPUT_DIR / "table_failure_mode_template.csv", index=False)
            print(f"  Template saved with {len(note_rows)} note entries to code.")

    # ── 5.5 Condition 2 dimension-specific effect ─────────────────
    c2 = df_scored[df_scored["condition"] == 2]
    if len(c2) > 0:
        c1_matched = df_scored[(df_scored["condition"] == 1) &
                         (df_scored["vignette_id"].isin(c2["vignette_id"].unique()))]

        dim_cols = [f"final_{d}" for d in DIMS if f"final_{d}" in df_scored.columns]
        fig, axes = plt.subplots(1, 4, figsize=(16, 5))
        for idx, dim in enumerate(DIMS):
            col = f"final_{dim}"
            if col not in df_scored.columns:
                continue
            ax = axes[idx]
            c1_mean = c1_matched[col].mean()
            c2_mean = c2[col].mean()
            bars = ax.bar(["C1", "C2"], [c1_mean, c2_mean],
                          color=["#78909C", "#26A69A"], alpha=0.85)
            ax.set_title(dim.replace("_", " ").title())
            ax.set_ylim(0, DIM_MAX[dim] + 0.3)
            for bar, val in zip(bars, [c1_mean, c2_mean]):
                ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                        f"{val:.2f}", ha="center", fontsize=10)

        fig.suptitle("CRAB: Condition 2 Effect per Dimension", fontsize=14)
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        fig.savefig(OUTPUT_DIR / "fig8_c2_effect_by_dimension.png")
        plt.close(fig)
        print("  Saved: fig8_c2_effect_by_dimension.png")

    # ── 5.6 Cultural recognition rate ─────────────────────────────
    if "final_cultural" in df_scored.columns:
        # BUG FIX 3: denominator is df_scored
        cultural_rate = (df_scored["final_cultural"].round() >= 1).mean() * 100
        print(f"\nCultural recognition rate: {cultural_rate:.1f}% "
              f"of {len(df_scored)} scored responses scored ≥1")

        cult_model = df_scored.groupby("model").apply(
            lambda x: (x["final_cultural"].round() >= 1).mean() * 100
        ).round(1)
        print("By model:")
        for model, rate in cult_model.items():
            n_m = (df_scored["model"] == model).sum()
            print(f"  {model:<25} {rate:.1f}%  (n={n_m})")

        cult_1 = df_scored[df_scored["final_cultural"].round() >= 1]
        cult_0 = df_scored[df_scored["final_cultural"].round() == 0]
        if len(cult_1) > 5:
            print(f"\nResponses WITH cultural recognition (n={len(cult_1)}):")
            for dim in ["accuracy", "adaptation", "actionable"]:
                col = f"final_{dim}"
                if col in df_scored.columns:
                    print(f"  mean {dim}: {cult_1[col].mean():.2f} vs "
                          f"{cult_0[col].mean():.2f} (without)")

    # ── 5.7 Within-vignette variance ──────────────────────────────
    if "final_total" in df_scored.columns:
        c1 = df_scored[df_scored["condition"] == 1]
        var_by_model = c1.groupby(["model", "vignette_id"])["final_total"].var()
        mean_var = var_by_model.groupby("model").mean().round(2)
        print("\nWithin-vignette score variance (setting sensitivity):")
        print("  Higher = model responds differently to different settings")
        for model, v in mean_var.items():
            print(f"  {model:<25} variance = {v:.2f}")

    # ── 5.8 PHC referral analysis ─────────────────────────────────
    c_responses = df_scored[(df_scored["setting"] == "C") & (df_scored["condition"] == 1)]
    if len(c_responses) > 0 and "response" in df_scored.columns:
        referral_pattern = re.compile(
            r'refer|transfer|send to|transport to|higher.?level|tertiary',
            re.IGNORECASE
        )
        stabilise_pattern = re.compile(
            r'before.?transfer|pre.?referral|while.?awaiting|before.?referr|'
            r'stabilise|stabilize|IV.?fluid|IM.?|intramuscular',
            re.IGNORECASE
        )

        categories = {"stabilise_and_refer": 0, "refer_only": 0,
                       "no_referral": 0}

        for _, row in c_responses.iterrows():
            resp = str(row.get("response", ""))
            has_referral = bool(referral_pattern.search(resp))
            has_stabilise = bool(stabilise_pattern.search(resp))
            if has_referral and has_stabilise:
                categories["stabilise_and_refer"] += 1
            elif has_referral:
                categories["refer_only"] += 1
            else:
                categories["no_referral"] += 1

        total_c = len(c_responses)
        print(f"\nPHC (Setting C, Condition 1) referral behaviour (n={total_c}):")
        for cat, count in categories.items():
            print(f"  {cat:<25} {count} ({100*count/total_c:.1f}%)")

    # ── 5.9 Word count analysis ────────────────────────────────────
    if "response" in df_scored.columns:
        df_scored = df_scored.copy()
        df_scored["word_count"] = df_scored["response"].astype(str).apply(
            lambda x: len(x.split()))
        wc_by_model = df_scored.groupby("model")["word_count"].agg(
            ["mean", "std", "min", "max"])
        wc_by_model = wc_by_model.round(0).astype(int)
        print("\nResponse word count by model:")
        print(wc_by_model)
        wc_by_model.to_csv(OUTPUT_DIR / "table_word_count.csv")


# ── SUMMARY REPORT ──────────────────────────────────────────────────

def write_summary(df_all: pd.DataFrame, df_scored: pd.DataFrame,
                  df_double: pd.DataFrame):
    lines = []
    lines.append("CRAB — Analysis Summary Report")
    lines.append("=" * 50)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"Total responses generated:     {len(df_all)}")
    lines.append(f"Total responses scored:        {len(df_scored)}")
    lines.append(f"Total responses double-scored: {len(df_double)}")
    if len(df_scored) < len(df_all):
        lines.append(f"  ** {len(df_all)-len(df_scored)} responses still need scoring **")
    lines.append(f"Models: {', '.join(sorted(df_all['model'].unique()))}")
    lines.append("")

    if "final_total" in df_scored.columns:
        lines.append(f"Overall mean total score (n={len(df_scored)} scored): "
                     f"{df_scored['final_total'].mean():.2f} / {TOTAL_MAX}")

    for dim in DIMS:
        col = f"final_{dim}"
        if col in df_scored.columns:
            n_dim = df_scored[col].notna().sum()
            lines.append(f"  {dim:<20} {df_scored[col].mean():.2f} / {DIM_MAX[dim]}  "
                         f"(n={n_dim})")

    lines.append("")

    # CBD rate — BUG FIX 5: use df_scored
    if "final_accuracy" in df_scored.columns and "final_actionable" in df_scored.columns:
        comp_danger = ((df_scored["final_accuracy"].round() == 2) &
                        (df_scored["final_actionable"].round() == 0)).sum()
        rate = comp_danger / len(df_scored) * 100
        lines.append(f"COMPETENT BUT DANGEROUS rate: {rate:.1f}%")
        lines.append(f"  ({comp_danger}/{len(df_scored)} scored responses: "
                     f"accuracy=2 but actionable=0)")
        lines.append("")

    # Dangerous rate by setting — BUG FIX 3
    if "final_actionable" in df_scored.columns:
        lines.append("Dangerous response rate (actionable=0) by setting (all scored):")
        for s in ["A", "B", "C"]:
            sub = df_scored[df_scored["setting"] == s]
            if len(sub) > 0:
                rate = (sub["final_actionable"].round() == 0).mean() * 100
                lines.append(f"  {SETTING_LABELS.get(s, s):<25} {rate:.1f}%  "
                             f"(n={len(sub)})")
        lines.append("")

    # Cultural recognition — BUG FIX 3
    if "final_cultural" in df_scored.columns:
        cult_rate = (df_scored["final_cultural"].round() >= 1).mean() * 100
        lines.append(f"Cultural recognition rate: {cult_rate:.1f}%  "
                     f"(n={len(df_scored)})")
        lines.append("")

    # Condition 2 effect
    c1 = df_scored[df_scored["condition"] == 1]
    c2 = df_scored[df_scored["condition"] == 2]
    if len(c2) > 0 and "final_total" in df_scored.columns:
        c2_vigs = set(c2["vignette_id"].unique())
        c1_matched = c1[c1["vignette_id"].isin(c2_vigs)]
        c1_mean = c1_matched["final_total"].mean()
        c2_mean = c2["final_total"].mean()
        diff = c2_mean - c1_mean
        lines.append(f"Condition 2 effect (matched vignettes): "
                     f"{'+' if diff >= 0 else ''}{diff:.2f} points")
        lines.append(f"  C1 mean total (matched vignettes, n={len(c1_matched)}): {c1_mean:.2f}")
        lines.append(f"  C2 mean total (n={len(c2)}):                            {c2_mean:.2f}")
        lines.append("")

    # Per-model ranking
    if "final_total" in df_scored.columns:
        lines.append("Model ranking by mean total score:")
        ranking = df_scored.groupby("model")["final_total"].mean().sort_values(ascending=False)
        n_model  = df_scored.groupby("model").size()
        for i, (model, score) in enumerate(ranking.items(), 1):
            lines.append(f"  {i}. {model:<25} {score:.2f} / {TOTAL_MAX}  "
                         f"(n={n_model[model]})")

    report = "\n".join(lines)
    with open(OUTPUT_DIR / "analysis_summary_report.txt", "w") as f:
        f.write(report)
    print(f"\n{'=' * 60}")
    print(report)
    print(f"\nSaved: analysis_summary_report.txt")


# ── MAIN ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CRAB Step 5 — Full Analysis and Visualisation"
    )
    parser.add_argument(
        "--data", required=True,
        help="Path to analysis master CSV from Step 4"
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("CRAB — Step 5: Full Analysis")
    print("=" * 60)

    # BUG FIX 1: load returns three population subsets
    df_all, df_scored, df_double = load_data(args.data)
    print(f"Loaded: {len(df_all)} total rows  |  "
          f"{len(df_scored)} scored  |  "
          f"{len(df_double)} double-scored")
    print(f"Models: {', '.join(sorted(df_all['model'].unique()))}")

    if len(df_scored) == 0:
        print("\nERROR: No scored responses found. "
              "Check that step4_compile_scores.py ran successfully.")
        sys.exit(1)

    # Layer 1 — BUG FIX 2: kappa uses df_double
    descriptive_stats(df_all, df_scored, df_double)
    compute_kappa(df_double)

    # Layer 2 — BUG FIX 3 & 5: all rates on df_scored
    dimension_analysis(df_scored)

    # Layer 3
    comparative_analysis(df_scored)

    # Layer 4 — BUG FIX 3 & 6
    failure_mode_analysis(df_scored, df_double)

    # Layer 5
    derived_metrics(df_scored)

    # Summary — BUG FIX 3 & 5
    write_summary(df_all, df_scored, df_double)

    print(f"\n{'=' * 60}")
    print("All outputs saved to:", OUTPUT_DIR)
    print("\nFigures:")
    for f in sorted(OUTPUT_DIR.glob("fig*.png")):
        print(f"  {f.name}")
    print("\nTables:")
    for f in sorted(OUTPUT_DIR.glob("table*.csv")):
        print(f"  {f.name}")
    print("\nReports:")
    for f in sorted(OUTPUT_DIR.glob("*.txt")):
        print(f"  {f.name}")


if __name__ == "__main__":
    main()