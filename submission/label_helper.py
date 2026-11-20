#!/usr/bin/env python3
"""
submission/label_helper.py — Interactive CLI for Hand-Labeling the 50 Posts

Usage:
  python3 submission/label_helper.py

Features:
- Fast terminal UI to review each of the 50 sampled posts in ~5 minutes.
- Shows Title, Company, Raw Location, Description Snippet, and LLM Tag.
- Press [Enter] to accept LLM tag, or type your own label.
- Auto-saves after every single row.
- Resumes where you left off if interrupted.
- Automatically calculates and prints accuracy when all 50 rows are done!
"""

import csv
import os
import sys
import subprocess

VALID_ROLES = [
    "SDE", "Data/ML", "Hardware", "Design", "Marketing", "Sales", "Ops", "Finance", "HR", "Other"
]

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

    print("\n" + "=" * 70)
    print("   BEEP JOB HUB — 50-POST ACCURACY HAND-LABELING HELPER")
    print("=" * 70)
    print("Instructions:")
    print("  - Press [Enter] to ACCEPT the LLM's tag.")
    print("  - Or type a custom value (e.g. SDE, Hardware, Ops, Bangalore).")
    print("  - Type 'q' to quit at any time (progress is saved automatically).")
    print("Valid Roles:", ", ".join(VALID_ROLES))
    print("=" * 70 + "\n")

    for i, row in enumerate(reader, 1):
        existing_role = (row.get("my_correct_role") or "").strip()
        existing_city = (row.get("my_correct_city") or "").strip()

        # If already filled, skip unless user asks to re-review
        if existing_role and existing_city:
            continue

        title = row.get("title", "")
        company = row.get("company", "")
        raw_loc = row.get("raw_location", "")
        llm_role = row.get("llm_role", "")
        llm_city = row.get("llm_city", "")
        snippet = (row.get("description_snippet", "") or "")[:280].replace("\n", " ")

        print(f"\n--- Post {i} of {len(reader)} [ID: {row.get('id')}, Source: {row.get('source')}] ---")
        print(f"Company:  \033[1m{company}\033[0m")
        print(f"Title:    \033[1m{title}\033[0m")
        print(f"Location: {raw_loc}")
        print(f"Snippet:  {snippet}...")
        print(f"LLM Tag:  Role = \033[36m{llm_role}\033[0m | City = \033[36m{llm_city}\033[0m")

        # Prompt for Role
        while True:
            prompt_str = f"Your Role [Enter = '{llm_role}'] > "
            user_role = input(prompt_str).strip()
            if user_role.lower() == 'q':
                print("\nSaving and quitting...")
                _save(reader, fieldnames)
                return
            if not user_role:
                chosen_role = llm_role
                break
            # Case-insensitive match against VALID_ROLES
            matched = [r for r in VALID_ROLES if r.lower() == user_role.lower()]
            if matched:
                chosen_role = matched[0]
                break
            else:
                print(f"  Invalid role '{user_role}'. Valid options: {', '.join(VALID_ROLES)}")

        # Prompt for City
        prompt_city = f"Your City [Enter = '{llm_city}'] > "
        user_city = input(prompt_city).strip()
        if user_city.lower() == 'q':
            row["my_correct_role"] = chosen_role
            _save(reader, fieldnames)
            return
        chosen_city = user_city if user_city else llm_city

        row["my_correct_role"] = chosen_role
        row["my_correct_city"] = chosen_city

        _save(reader, fieldnames)
        print(f"Saved: Role = {chosen_role}, City = {chosen_city}")

    print("\n" + "=" * 70)
    print("All 50 posts have been hand-labeled! Running evaluation script...")
    print("=" * 70 + "\n")
    eval_script = os.path.join(os.path.dirname(__file__), "eval_accuracy.py")
    subprocess.run([sys.executable, eval_script, CSV_PATH])

def _save(rows, fieldnames):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

if __name__ == "__main__":
    main()
