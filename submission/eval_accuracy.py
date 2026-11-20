#!/usr/bin/env python3
"""
submission/eval_accuracy.py — Hand-Checked Tagging Accuracy Evaluator

Usage:
  # After filling my_correct_role and my_correct_city in accuracy_sample_50.csv:
  python3 submission/eval_accuracy.py submission/accuracy_sample_50.csv

  # Preview using AI reviewer's preliminary labels (NOT ground truth):
  python3 submission/eval_accuracy.py submission/accuracy_ai_review_50.csv \
      --role-col ai_reviewer_role --city-col ai_reviewer_city
"""

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict


def wilson_ci_95(k: int, n: int) -> tuple[float, float]:
    """Computes the Wilson score 95% confidence interval for a binomial proportion."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    p = k / n
    denom = 1.0 + (z * z) / n
    center = (p + (z * z) / (2.0 * n)) / denom
    half = (z / denom) * math.sqrt((p * (1.0 - p) + (z * z) / (4.0 * n)) / n)
    return (max(0.0, center - half), min(1.0, center + half))


def norm(val: str) -> str:
    return (val or "").strip()


def evaluate(csv_path: str, role_col: str, city_col: str) -> None:
    with open(csv_path, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    labeled = [r for r in rows if norm(r.get(role_col)) and norm(r.get(city_col))]
    if not labeled:
        print(
            f"No labeled rows found in {csv_path} (columns '{role_col}' and '{city_col}' are empty).\n"
            f"Fill in '{role_col}' and '{city_col}' by hand, then re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    n = len(labeled)
    role_ok = 0
    city_ok = 0
    both_ok = 0

    by_source = defaultdict(lambda: {"n": 0, "role_ok": 0, "city_ok": 0})
    role_confusions = Counter()
    city_confusions = Counter()
    conf_buckets = defaultdict(lambda: {"n": 0, "role_ok": 0, "city_ok": 0})
    errors = []

    for r in labeled:
        pred_role = norm(r["llm_role"])
        true_role = norm(r[role_col])
        pred_city = norm(r["llm_city"])
        true_city = norm(r[city_col])
        src = norm(r["source"])
        try:
            conf = float(r.get("confidence") or 0.0)
        except ValueError:
            conf = 0.0

        r_match = pred_role.lower() == true_role.lower()
        c_match = pred_city.lower() == true_city.lower()

        role_ok += int(r_match)
        city_ok += int(c_match)
        both_ok += int(r_match and c_match)

        by_source[src]["n"] += 1
        by_source[src]["role_ok"] += int(r_match)
        by_source[src]["city_ok"] += int(c_match)

        bucket = "<0.85 (Low)" if conf < 0.85 else ("0.85-0.94 (Mid)" if conf < 0.95 else ">=0.95 (High)")
        conf_buckets[bucket]["n"] += 1
        conf_buckets[bucket]["role_ok"] += int(r_match)
        conf_buckets[bucket]["city_ok"] += int(c_match)

        if not r_match:
            role_confusions[(true_role, pred_role)] += 1
        if not c_match:
            city_confusions[(true_city, pred_city)] += 1
        if not r_match or not c_match:
            # Severity: both wrong (2) > single wrong (1), then highest LLM confidence (overconfident error)
            severity = (0 if r_match else 1) + (0 if c_match else 1)
            errors.append({
                "severity": severity,
                "confidence": conf,
                "id": r["id"],
                "source": src,
                "company": r["company"],
                "title": r["title"],
                "raw_location": r["raw_location"],
                "pred_role": pred_role,
                "true_role": true_role,
                "pred_city": pred_city,
                "true_city": true_city,
                "note": r.get("review_note", ""),
            })

    r_lo, r_hi = wilson_ci_95(role_ok, n)
    c_lo, c_hi = wilson_ci_95(city_ok, n)
    b_lo, b_hi = wilson_ci_95(both_ok, n)

    print(f"=== TAGGING ACCURACY REPORT ({csv_path}) ===")
    print(f"Labeled rows evaluated: {n} / {len(rows)}")
    print(f"Role Accuracy: {role_ok}/{n} = {role_ok/n*100:.1f}%  (Wilson 95% CI: [{r_lo*100:.1f}%, {r_hi*100:.1f}%])")
    print(f"City Accuracy: {city_ok}/{n} = {city_ok/n*100:.1f}%  (Wilson 95% CI: [{c_lo*100:.1f}%, {c_hi*100:.1f}%])")
    print(f"Exact Both:    {both_ok}/{n} = {both_ok/n*100:.1f}%  (Wilson 95% CI: [{b_lo*100:.1f}%, {b_hi*100:.1f}%])")

    print("\n--- Per-Source Accuracy ---")
    for src, st in sorted(by_source.items(), key=lambda kv: -kv[1]["n"]):
        sn = st["n"]
        print(
            f"  {src:16s} (n={sn:2d}): "
            f"role={st['role_ok']}/{sn} ({st['role_ok']/sn*100:5.1f}%) | "
            f"city={st['city_ok']}/{sn} ({st['city_ok']/sn*100:5.1f}%)"
        )

    print("\n--- Confidence Calibration ---")
    for bname in ["<0.85 (Low)", "0.85-0.94 (Mid)", ">=0.95 (High)"]:
        st = conf_buckets[bname]
        if st["n"]:
            bn = st["n"]
            print(
                f"  {bname:16s} (n={bn:2d}): "
                f"role={st['role_ok']}/{bn} ({st['role_ok']/bn*100:5.1f}%) | "
                f"city={st['city_ok']}/{bn} ({st['city_ok']/bn*100:5.1f}%)"
            )

    print("\n--- Role Confusion List (True -> Predicted) ---")
    if role_confusions:
        for (tr, pr), cnt in role_confusions.most_common():
            print(f"  {tr:12s} -> {pr:12s} : {cnt}")
    else:
        print("  None (100% agreement)")

    print("\n--- City Confusion List (True -> Predicted) ---")
    if city_confusions:
        for (tc, pc), cnt in city_confusions.most_common():
            print(f"  {tc:22s} -> {pc:22s} : {cnt}")
    else:
        print("  None (100% agreement)")

    errors.sort(key=lambda e: (-e["severity"], -e["confidence"], int(e["id"])))
    print(f"\n--- Top {min(10, len(errors))} Worst Errors (sorted by severity, then overconfidence) ---")
    for i, e in enumerate(errors[:10], 1):
        role_flag = f"ROLE {e['true_role']} != {e['pred_role']}" if e["true_role"].lower() != e["pred_role"].lower() else "role ok"
        city_flag = f"CITY {e['true_city']} != {e['pred_city']}" if e["true_city"].lower() != e["pred_city"].lower() else "city ok"
        print(f"  {i:2d}. [id={e['id']} | {e['source']} | conf={e['confidence']:.2f}] {e['company']} — {e['title']}")
        print(f"      raw_loc='{e['raw_location']}' | {role_flag} | {city_flag}")
        if e["note"]:
            print(f"      note: {e['note']}")


def main() -> None:
    p = argparse.ArgumentParser(description="Evaluate LLM role & city tagging accuracy on 50-post CSV.")
    p.add_argument("csv_path", nargs="?", default="submission/accuracy_sample_50.csv")
    p.add_argument("--role-col", default="my_correct_role")
    p.add_argument("--city-col", default="my_correct_city")
    args = p.parse_args()
    evaluate(args.csv_path, args.role_col, args.city_col)


if __name__ == "__main__":
    main()
