#!/usr/bin/env python3
"""
fanta-lab — Unified CLI Pipeline Entry Point

Executes the full analytics, machine learning, and auction optimization pipeline
or individual standalone stages.

Usage:
  python run_pipeline.py              # Execute entire end-to-end pipeline
  python run_pipeline.py --step 6     # Run Stage 6 (Build Dataset)
  python run_pipeline.py --step 8     # Run Stage 8 (Quantile Regression Model)
  python run_pipeline.py --step 9     # Run Stage 9 (VORP & Fair Pricing)
  python run_pipeline.py --step 10    # Run Stage 10 (MILP Roster Optimizer)
  python run_pipeline.py --step 7     # Run Stage 7 (Generate Excel Workbook)
  python run_pipeline.py --from 8     # Run from Machine Learning stages onward
"""

import argparse
import importlib
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STEPS = {
    1:  ("01_scrape_historical",     "Stage 1 — Historical Player & Team Stats Scraper"),
    3:  ("03_update_listone",        "Stage 2 — Official Price Sheet Ingestion"),
    4:  ("04_scrape_understat",      "Stage 2b — Understat xG/xA Scraping"),
    5:  ("05_scrape_injuries",       "Stage 3 — Transfermarkt Medical Scraper"),
    6:  ("06_build_dataset",         "Stage 4 — Fuzzy Entity Resolution & Composite Scoring"),
    8:  ("08_quantile_points_model", "Stage 5 — Machine Learning Quantile Regression (P10/P50/P90)"),
    9:  ("09_vorp_auction_pricing",  "Stage 6 — Sabermetric VORP & Fair Auction Valuation"),
    10: ("10_roster_optimizer",      "Stage 7 — Mathematical MILP 25-Player Roster Optimizer"),
    7:  ("07_generate_excel",        "Stage 8 — Formatted Multi-Tab Excel Spreadsheet Export"),
}


def run_step(step_num):
    if step_num not in STEPS:
        print(f"Error: Step {step_num} is not valid. Available steps: {sorted(STEPS.keys())}")
        return False

    module_name, description = STEPS[step_num]
    print(f"\n{'='*70}")
    print(f"  {description}")
    print(f"{'='*70}\n")

    try:
        mod = importlib.import_module(f"pipeline.{module_name}")
        mod.main()
        return True
    except Exception as e:
        print(f"\nError in {description}: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all(from_step=1):
    print("=" * 70)
    print("  fanta-lab — Quantitative Fantasy Football Analytics Pipeline")
    print("=" * 70)

    # Execution sequence
    ordered_steps = [1, 3, 4, 5, 6, 8, 9, 10, 7]
    steps_to_run = [s for s in ordered_steps if s >= from_step]

    for i, step_num in enumerate(steps_to_run, 1):
        _, desc = STEPS[step_num]
        print(f"  [{i}/{len(steps_to_run)}] {desc}")

    print()

    for step_num in steps_to_run:
        success = run_step(step_num)
        if not success:
            print(f"\nPipeline interrupted at step {step_num}.")
            return False

    print("\n" + "=" * 70)
    print("  PIPELINE COMPLETED SUCCESSFULLY!")
    print("=" * 70)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="fanta-lab — Quantitative Fantasy Football Analytics Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available Pipeline Stages:
  1   Stage 1   Historical Player & Team Stats Ingestion
  3   Stage 2   Official Price Sheet Ingestion
  4   Stage 2b  Understat xG/xA API Scraping
  5   Stage 3   Transfermarkt Medical & Injury History
  6   Stage 4   Dataset Synthesis & Composite Scoring Engine
  8   Stage 5   Machine Learning Quantile Regression (P10/P50/P90 Points)
  9   Stage 6   Value Over Replacement Player (VORP) & Fair Pricing Engine
  10  Stage 7   Mathematical MILP 25-Player Roster Optimizer
  7   Stage 8   Formatted Multi-Tab Excel Workbook Export

Examples:
  python run_pipeline.py              # Full end-to-end execution
  python run_pipeline.py --step 8     # Run only Quantile ML Model
  python run_pipeline.py --step 9     # Run only VORP & Pricing Engine
  python run_pipeline.py --step 10    # Run only MILP Roster Optimizer
  python run_pipeline.py --from 8     # Run ML & Optimization stages through Excel
        """
    )

    parser.add_argument("--step", type=int, help="Execute a single standalone step")
    parser.add_argument("--from", dest="from_step", type=int, default=1,
                        help="Execute the pipeline starting from this step")

    args = parser.parse_args()

    if args.step:
        run_step(args.step)
    else:
        run_all(from_step=args.from_step)


if __name__ == "__main__":
    main()
