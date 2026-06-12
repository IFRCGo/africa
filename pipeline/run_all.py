"""Run the full information-management workflow end to end.

  python run_all.py            # incremental: only new PDFs are cataloged/extracted
  python run_all.py --reparse  # re-run parsing/eventing/export only (fast)

Steps: catalog -> extract text -> parse figures/tags -> events -> export platform JSON.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS_FULL = ["s01_catalog.py", "s02_extract_text.py", "s03_parse.py", "s04_events.py", "s05_export.py"]
STEPS_REPARSE = ["s03_parse.py", "s04_events.py", "s05_export.py"]


def main():
    steps = STEPS_REPARSE if "--reparse" in sys.argv else STEPS_FULL
    for step in steps:
        print(f"\n=== {step} ===")
        r = subprocess.run([sys.executable, str(HERE / step)], cwd=HERE)
        if r.returncode != 0:
            sys.exit(f"step {step} failed")
    print("\nWorkflow complete. Open platform/index.html (via a local server) or push to GitHub Pages.")


if __name__ == "__main__":
    main()
