#!/usr/bin/env python3
"""Validate a job contract and optionally its manuscript approval receipt."""

import argparse
import json

try:
    from scripts.paper_card_core import load_job, verify_approval
except ModuleNotFoundError:
    from paper_card_core import load_job, verify_approval


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--job", required=True)
parser.add_argument("--approval", help="Exact-manuscript approval receipt; omit before the boss confirms")
args = parser.parse_args()
job = load_job(args.job)
status = "CONTRACT_PASS_APPROVAL_PENDING"
if args.approval:
    verify_approval(job, args.approval)
    status = "CONTRACT_AND_APPROVAL_PASS"
print(json.dumps({
    "status": status,
    "job": job["id"],
    "manuscript": job["_manuscript_path"],
    "manuscript_sha256": job["_manuscript_sha256"],
    "scenes": len(job["scenes"]),
    "cards": sum(len(scene["lines"]) for scene in job["scenes"]),
}, ensure_ascii=False, indent=2))
