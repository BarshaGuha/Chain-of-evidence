"""Copy the latest run of a stockout into examples/ so it can be committed.

    python3 -m agent.save_example OOS-002

Copies logs/<latest run of OOS-002>/ (trace, world model, receipts) and
outputs/OOS-002.md/.json into examples/OOS-002/. Nothing secret is in them:
receipts hold model, timing, token counts and Meterless signatures, not keys.
"""
import shutil
import sys

from . import config


def main(argv=None):
    args = argv or sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    for event in args:
        runs = sorted(config.LOG_DIR.glob(f"{event}_*"))
        if not runs:
            print(f"{event}: no run found in logs/. Run it first.")
            continue
        dest = config.ROOT / "examples" / event
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(runs[-1], dest)
        for ext in ("md", "json"):
            src = config.OUTPUT_DIR / f"{event}.{ext}"
            if src.exists():
                shutil.copy(src, dest / f"report.{ext}")
        receipts = (dest / "receipts.jsonl").read_text().splitlines()
        live = "offline-reasoner" not in "".join(receipts) and receipts
        print(f"{event}: saved {runs[-1].name} to examples/{event}/ "
              f"({'live: every model call on Nemotron' if live else 'NOT fully live: re-run it on the live stack'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
