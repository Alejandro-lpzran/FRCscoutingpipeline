from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RAW_DIR       = ROOT / "data" / "raw"        # Inputs no script produces (scouting export, team list)
PROCESSED_DIR = ROOT / "data" / "processed"  # Everything the pipeline writes; safe to rebuild
REPORTS_DIR   = PROCESSED_DIR / "reports"    # LLM scouting reports
