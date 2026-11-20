# EVALUATION_REPORT.md — 50-Post Random Stratified Tagging Evaluation

> **Evaluation Sample:** 50 active live posts drawn randomly (`seed=20261120`) from the **237 live Cloud SQL jobs**, proportionally stratified across all 7 active sources (`workday: 26`, `github_feeds: 12`, `greenhouse: 6`, `lever: 3`, `ashby: 1`, `smartrecruiters: 1`, `remotive: 1`).  
> **Model Evaluated:** `gemini-3.5-flash-lite`  
> **Files:**
> - Hand-labeling template: [`submission/accuracy_sample_50.csv`](file:///Users/adityamagar/Beep-Job-Search/submission/accuracy_sample_50.csv)
> - AI reviewer baseline *(NOT ground truth)*: [`submission/accuracy_ai_review_50.csv`](file:///Users/adityamagar/Beep-Job-Search/submission/accuracy_ai_review_50.csv)
> - Scoring script (Wilson 95% CI, per-source, confusion list, calibration, top-10 errors): [`submission/eval_accuracy.py`](file:///Users/adityamagar/Beep-Job-Search/submission/eval_accuracy.py)

---

## 1. How to Compute Final Hand-Checked Accuracy

Fill `my_correct_role` and `my_correct_city` in `submission/accuracy_sample_50.csv` by hand, then run:

```bash
python3 submission/eval_accuracy.py submission/accuracy_sample_50.csv
```

*(Note: Previous `scripts/eval_export.py` used a heuristic regex script rather than human labels and has been superseded by this hand-check harness.)*

---

## 2. Preliminary Baseline (AI Reviewer Labels — Pending Final Human Adjudication)

*Caveat: Numbers below are from an independent AI review of the 50 sampled posts, NOT human ground truth. Replace with your final `eval_accuracy.py` output once hand-labeled.*

| Metric | Preliminary Score | Wilson 95% CI (`n=50`) |
| :--- | :---: | :---: |
| **City Normalization Accuracy** | **98.0% (49/50)** | `[89.5%, 99.6%]` |
| **Role Category Accuracy** | **80.0% (40/50)** | `[67.0%, 88.8%]` |
| **Exact Both (Role + City)** | **80.0% (40/50)** | `[67.0%, 88.8%]` |

### Per-Source Breakdown (Preliminary)
| Source | n | Role Accuracy | City Accuracy |
| :--- | :---: | :---: | :---: |
| `workday` | 26 | 21/26 (80.8%) | 26/26 (100.0%) |
| `github_feeds` | 12 | 10/12 (83.3%) | 11/12 (91.7%) |
| `greenhouse` | 6 | 4/6 (66.7%) | 6/6 (100.0%) |
| `lever` | 3 | 3/3 (100.0%) | 3/3 (100.0%) |
| `ashby` / `smartrecruiters` | 1 each | 1/1 (100.0%) | 1/1 (100.0%) |
| `remotive` | 1 | 0/1 (0.0%) | 1/1 (100.0%) |

### Confidence Calibration Insight
- `< 0.85` (n=6): `100.0%` role / `100.0%` city (LLM conservatively chose `Other`/`Hardware` on short stubs).
- `0.85 – 0.94` (n=19): `63.2%` role / `94.7%` city (primary error cluster: Ops vs Finance in banking ops, pre-sales advisory, PoE hardware testing).
- `>= 0.95` (n=25): `88.0%` role / `100.0%` city.

### Primary Confusion Patterns
- `Ops -> Finance` (4): banking trade settlement / compliance operations vs pure finance/accounting.
- `Ops -> SDE` (2): Rubrik Engineering Program Manager Intern; Micron 24/7 IT Operations Support.
- `Hardware -> SDE` (1): HPE Network Switch Platform Test Engineer (PoE IEEE 802.3af/at/bt).
- `Mumbai -> Remote` (1): Third Bridge `Associate, Content Compliance (US Hours)` in Mumbai misclassified as `Remote` due to `"(US Hours)"` in title.
