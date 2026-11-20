#!/usr/bin/env python3
"""
submission/label_helper.py — Interactive CLI for Hand-Labeling the 50 Posts

Usage:
  python3 submission/label_helper.py

Features:
- Numbered shortcuts (1-9, 0) for instant role selection.
- Press [Enter] to accept the LLM's tag, or type a number/correction.
- Auto-saves after every post. Resumes right where you left off.
- Automatically calculates accuracy and Wilson 95% confidence intervals when done.
"""

import csv
import os
import sys
import subprocess

ROLES_MAP = {
    "1": "SDE",
    "2": "Data/ML",
    "3": "Hardware",
    "4": "Design",
    "5": "Marketing",
    "6": "Sales",
    "7": "Ops",
    "8": "Finance",
    "9": "HR",
    "0": "Other",
}

VALID_ROLES = list(ROLES_MAP.values())
CSV_PATH = os.path.join(os.path.dirname(__file__), "accuracy_sample_50.csv")

def main():
    if not os.path.exists(CSV_PATH):
        print(f"Error: {CSV_PATH} not found!")
        sys.exit(1)

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        fieldnames = reader[0].keys() if reader else []

    if not reader:
        print("CSV is empty.")
        sys.exit(1)

    print("\n" + "=" * 75)
    print("      BEEP JOB HUB — 50-POST HAND ACCURACY EVALUATION HELPER")
    print("=" * 75)
    print("Shortcuts:")
    print("  [1] SDE       [2] Data/ML   [3] Hardware  [4] Design    [5] Marketing")
    print("  [6] Sales     [7] Ops       [8] Finance   [9] HR        [0] Other")
    print("  [Enter]       Accept LLM guess")
    print("  'q'           Save and exit anytime")
    print("=" * 75 + "\n")

    filled_count = sum(1 for r in reader if (r.get("my_correct_role") or "").strip() and (r.get("my_correct_city") or "").strip())
    if filled_count > 0:
        print(f"Resuming: {filled_count} of {len(reader)} posts already labeled.\n")

    for i, row in enumerate(reader, 1):
        existing_role = (row.get("my_correct_role") or "").strip()
        existing_city = (row.get("my_correct_city") or "").strip()

        # If already filled, skip
        if existing_role and existing_city:
            continue

        title = row.get("title", "")
        company = row.get("company", "")
        raw_loc = row.get("raw_location", "")
        llm_role = row.get("llm_role", "")
        llm_city = row.get("llm_city", "")
        snippet = (row.get("description_snippet", "") or "")[:260].replace("\n", " ")

        print(f"\n--- Post {i} of {len(reader)} [ID: {row.get('id')} | Source: {row.get('source')}] ---")
        print(f"Company:   \033[1m{company}\033[0m")
        print(f"Title:     \033[1m{title}\033[0m")
        print(f"Location:  {raw_loc}")
        print(f"Snippet:   {snippet}...")
        print(f"LLM Guess: Role = \033[36m{llm_role}\033[0m | City = \033[36m{llm_city}\033[0m")

        # 1. Role Selection
        while True:
            choice = input(f"Role [Enter='{llm_role}', or 1-9,0, or name] > ").strip()
            if choice.lower() == 'q':
                print("\nProgress saved. Exiting...")
                _save(reader, fieldnames)
                return
            if not choice:
                chosen_role = llm_role
                break
            if choice in ROLES_MAP:
                chosen_role = ROLES_MAP[choice]
                break
            matched = [r for r in VALID_ROLES if r.lower() == choice.lower()]
            if matched:
                chosen_role = matched[0]
                break
            print(f"  Invalid choice '{choice}'. Enter 1-9, 0, or role name.")

        # 2. City Selection
        city_choice = input(f"City [Enter='{llm_city}', or type city] > ").strip()
        if city_choice.lower() == 'q':
            row["my_correct_role"] = chosen_role
            _save(reader, fieldnames)
            return
        chosen_city = city_choice if city_choice else llm_city

        row["my_correct_role"] = chosen_role
        row["my_correct_city"] = chosen_city
        _save(reader, fieldnames)

        is_role_match = (chosen_role == llm_role)
        is_city_match = (chosen_city == llm_city)
        status_str = f"Saved: Role={chosen_role} ({'MATCH' if is_role_match else 'DIFF'}), City={chosen_city} ({'MATCH' if is_city_match else 'DIFF'})"
        print(status_str)

    print("\n" + "=" * 75)
    print("All 50 posts completed! Running statistical evaluation...")
    print("=" * 75 + "\n")
    eval_script = os.path.join(os.path.dirname(__file__), "eval_accuracy.py")
    subprocess.run([sys.executable, eval_script, CSV_PATH])

def _save(rows, fieldnames):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

if __name__ == "__main__":
    main()
