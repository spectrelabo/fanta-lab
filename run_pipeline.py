#!/usr/bin/env python3
"""
fanta-lab — Entry Point CLI

Esegue la pipeline completa o singoli step della pipeline
di analisi Fantacalcio Serie A.

Uso:
  python run_pipeline.py              # Esegue tutta la pipeline
  python run_pipeline.py --step 1     # Solo Fase 1 (storico)
  python run_pipeline.py --step 3     # Solo Fase 2 (listone)
  python run_pipeline.py --step 4     # Solo Fase 2b (Understat)
  python run_pipeline.py --step 5     # Solo Fase 3 (infortuni)
  python run_pipeline.py --step 6     # Solo Fase 4 (build dataset)
  python run_pipeline.py --step 7     # Solo Fase 5 (genera Excel)
  python run_pipeline.py --from 4     # Da Fase 2b in poi
"""

import argparse
import importlib
import sys
import os

# Assicura che il progetto sia nel path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STEPS = {
    1: ("01_scrape_historical",  "Fase 1 — Raccolta dati storici (fantacalcio.it)"),
    3: ("03_update_listone",     "Fase 2 — Aggiornamento listone (Quotazioni)"),
    4: ("04_scrape_understat",   "Fase 2b — Scraping xG/xA (Understat)"),
    5: ("05_scrape_injuries",    "Fase 3 — Scraping infortuni (Transfermarkt)"),
    6: ("06_build_dataset",      "Fase 4 — Build dataset finale (merge + score)"),
    7: ("07_generate_excel",     "Fase 5 — Generazione Excel multi-scheda"),
}


def run_step(step_num):
    """Esegue un singolo step della pipeline."""
    if step_num not in STEPS:
        print(f"❌ Step {step_num} non valido. Step disponibili: {list(STEPS.keys())}")
        return False

    module_name, description = STEPS[step_num]
    print(f"\n{'='*70}")
    print(f"  🚀 {description}")
    print(f"{'='*70}\n")

    try:
        mod = importlib.import_module(f"pipeline.{module_name}")
        mod.main()
        return True
    except Exception as e:
        print(f"\n❌ Errore in {description}: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all(from_step=1):
    """Esegue tutti gli step della pipeline a partire da from_step."""
    print("=" * 70)
    print("  ⚽ fanta-lab — Pipeline Analisi Fantacalcio Serie A")
    print("=" * 70)

    steps_to_run = sorted(s for s in STEPS if s >= from_step)

    for i, step_num in enumerate(steps_to_run, 1):
        _, desc = STEPS[step_num]
        print(f"\n  [{i}/{len(steps_to_run)}] {desc}")

    print()

    for step_num in steps_to_run:
        success = run_step(step_num)
        if not success:
            print(f"\n⚠️  Pipeline interrotta allo step {step_num}.")
            return False

    print("\n" + "=" * 70)
    print("  ✅ PIPELINE COMPLETATA CON SUCCESSO!")
    print("=" * 70)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="fanta-lab — Pipeline di analisi Fantacalcio Serie A",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Step disponibili:
  1  Fase 1   Raccolta dati storici (fantacalcio.it + football-data.co.uk)
  3  Fase 2   Aggiornamento listone (Quotazioni ufficiali)
  4  Fase 2b  Scraping xG/xA (Understat)
  5  Fase 3   Scraping infortuni (Transfermarkt)
  6  Fase 4   Build dataset finale (merge multi-sorgente + score composito)
  7  Fase 5   Generazione Excel multi-scheda formattato

Esempi:
  python run_pipeline.py              # Pipeline completa
  python run_pipeline.py --step 6     # Solo build dataset
  python run_pipeline.py --from 4     # Da Understat in poi
        """
    )

    parser.add_argument("--step", type=int, help="Esegui un singolo step")
    parser.add_argument("--from", dest="from_step", type=int, default=1,
                        help="Esegui la pipeline a partire da questo step")

    args = parser.parse_args()

    if args.step:
        run_step(args.step)
    else:
        run_all(from_step=args.from_step)


if __name__ == "__main__":
    main()
