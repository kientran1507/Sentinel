"""Prepare bounded synthetic pilot files for review without database access."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from uuid import uuid4

from scripts.validate_detection import build_scenarios


BATCH_COPIES = (1, 5, 10)


def build_pilot(scope, run_id):
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("explicit scope is required")
    files, batches, identities = {}, [], set()
    for copies in BATCH_COPIES:
        events = []
        for number in range(copies):
            collector = f"pilot-{run_id}-{copies}-{number}"
            for scenario in build_scenarios(scope, collector):
                events.extend((*scenario.controls, *scenario.positives))
        ids = {event.event_id for event in events}
        if len(ids) != len(events) or ids & identities:
            raise ValueError("pilot event identities overlap")
        identities.update(ids)
        name = f"pilot-{copies}.jsonl"
        data = ("\n".join(json.dumps(event.to_dict(), sort_keys=True) for event in events) + "\n").encode()
        files[name] = data
        batches.append({"file": name, "copies": copies, "event_count": len(events),
                        "expected_findings": copies * 5, "sha256": hashlib.sha256(data).hexdigest(),
                        "collectors": sorted({event.collector for event in events})})
    manifest = {"version": 1, "run_id": run_id, "scope": scope, "synthetic": True,
                "batches": batches, "event_count": len(identities),
                "expected_findings": sum(batch["expected_findings"] for batch in batches),
                "replay_expected_new_events": 0, "replay_expected_new_findings": 0,
                "execution_approved": False,
                "boundary": "input preparation only; no workload or database access"}
    files["pilot-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files, manifest


def main(argv=None, *, output=None):
    output = output or sys.stdout
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--output-dir", help="Create a new directory containing the pilot files; default is preview")
    args = parser.parse_args(argv)
    try:
        files, manifest = build_pilot(args.scope, uuid4().hex)
        if args.output_dir is not None:
            directory = Path(args.output_dir)
            directory.mkdir(mode=0o700, parents=False, exist_ok=False)
            # Manifest is written last; interrupted output remains available for inspection.
            for name, data in files.items():
                with (directory / name).open("xb") as stream:
                    stream.write(data)
        print(json.dumps({"status": "prepared" if args.output_dir is not None else "preview",
                          **manifest}), file=output)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}), file=output)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
