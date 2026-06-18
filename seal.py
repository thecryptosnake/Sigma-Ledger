"""Seal one forward-ledger snapshot into a tamper-evident public commitment.

  python -X utf8 seal.py --asof 2026-06-11

Reads the raw snapshot from the (private, local) Sigma forward ledger, builds
the engine-free Merkle commitment, and writes TWO artifacts:

  seals_private/<asof>/sealed_<asof>.json   PRIVATE (gitignored) -- full
      canonical leaves + per-leaf hash + tree order + root. This is the
      "sealed envelope": it lets us reveal exact forecasts later and prove they
      match the anchored root. NEVER pushed until a forecast is revealed.

  commitments/<asof>/commitment_<asof>.json  PUBLIC -- Merkle root + chain
      link + universe metadata, NO leaves. Plus COMMITMENT.txt, the tiny file
      that gets OpenTimestamps-anchored to Bitcoin.

Chain: each commitment carries the previous commitment's root (prev_commitment)
and a chain_index, so snapshots cannot be reordered/inserted/removed without
breaking the chain.

Pure standard library; no engine import, no network.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import date, datetime, timezone

import ledger_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LEDGER_DIR = os.path.normpath(os.path.join(HERE, "..", "Sigma", "forward_ledger"))
PRIVATE_DIR = os.path.join(HERE, "seals_private")
PUBLIC_DIR = os.path.join(HERE, "commitments")
SEAL_SCHEMA = "sigma-public-seal-1"
COMMIT_SCHEMA = "sigma-public-commitment-1"

# Header fields carried (public) from the snapshot -- market context + scope,
# NOT engine internals.
PUBLIC_HEADER_FIELDS = ("universe_version", "universe_size", "horizons",
                        "vix_at_generation")


def _load_snapshot(ledger_dir: str, asof: str) -> dict:
    path = os.path.join(ledger_dir, asof, f"forward_sweep_{asof}.json")
    if not os.path.isfile(path):
        raise SystemExit(f"snapshot not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _prev_commitment(asof: str) -> tuple[str | None, int]:
    """Latest existing commitment with asof < this one -> (root, chain_index)."""
    prev_root, prev_index, prev_asof = None, -1, ""
    for path in glob.glob(os.path.join(PUBLIC_DIR, "*", "commitment_*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                c = json.load(f)
        except Exception:
            continue
        a = c.get("asof", "")
        if a < asof and a > prev_asof:
            prev_asof, prev_root, prev_index = a, c.get("merkle_root"), c.get("chain_index", 0)
    if prev_root is None:
        return None, 0
    return prev_root, prev_index + 1


def seal(asof: str, ledger_dir: str) -> dict:
    snap = _load_snapshot(ledger_dir, asof)
    if snap.get("asof") != asof:
        raise SystemExit(f"snapshot asof {snap.get('asof')!r} != requested {asof!r}")

    commitment = core.build_commitment(snap.get("records", []))
    prev_root, chain_index = _prev_commitment(asof)
    sealed_dt = datetime.now(timezone.utc)
    sealed_at = sealed_dt.isoformat()
    # Days between the forecast label (asof) and when it was actually sealed +
    # anchored. The cryptographic proof date is the ANCHOR date, not asof; this
    # field makes the gap auditable from the public commitment, not just prose.
    # Same-day seals (the steady state) report 0.
    gap_days = (sealed_dt.date() - date.fromisoformat(asof)).days
    header = {k: snap.get(k) for k in PUBLIC_HEADER_FIELDS}

    sealed = {
        "schema": SEAL_SCHEMA,
        "asof": asof,
        "chain_index": chain_index,
        "prev_commitment": prev_root,
        "merkle_root": commitment["merkle_root"],
        "n_leaves": commitment["n_leaves"],
        "n_skipped": commitment["n_skipped"],
        "sealed_at_utc": sealed_at,
        "sealed_anchor_gap_days": gap_days,
        "header": header,
        "ordered_leaf_hashes": commitment["ordered_leaf_hashes"],
        "leaves": commitment["leaves"],
        "note": ("engine-free public projection of a forward_ledger snapshot; "
                 "engine internals (seed/df/n_sims/return_model/engine_version "
                 "and all risk metrics) intentionally excluded"),
    }
    public = {
        "schema": COMMIT_SCHEMA,
        "asof": asof,
        "chain_index": chain_index,
        "prev_commitment": prev_root,
        "merkle_root": commitment["merkle_root"],
        "n_leaves": commitment["n_leaves"],
        "n_skipped": commitment["n_skipped"],
        "sealed_at_utc": sealed_at,
        "sealed_anchor_gap_days": gap_days,
        "header": header,
        "anchor": {"status": "unanchored", "method": "opentimestamps-bitcoin",
                   "ots_file": None, "note": "run ots stamp on COMMITMENT.txt"},
    }

    priv_dir = os.path.join(PRIVATE_DIR, asof)
    pub_dir = os.path.join(PUBLIC_DIR, asof)
    os.makedirs(priv_dir, exist_ok=True)
    os.makedirs(pub_dir, exist_ok=True)
    with open(os.path.join(priv_dir, f"sealed_{asof}.json"), "w", encoding="utf-8") as f:
        json.dump(sealed, f, indent=1, sort_keys=True)
    with open(os.path.join(pub_dir, f"commitment_{asof}.json"), "w", encoding="utf-8") as f:
        json.dump(public, f, indent=1, sort_keys=True)
    with open(os.path.join(pub_dir, "COMMITMENT.txt"), "w", encoding="utf-8") as f:
        f.write(
            "Sigma public validation ledger -- forecast commitment\n"
            f"asof:            {asof}\n"
            f"chain_index:     {chain_index}\n"
            f"prev_commitment: {prev_root or '(genesis)'}\n"
            f"merkle_root:     {commitment['merkle_root']}\n"
            f"n_leaves:        {commitment['n_leaves']}\n"
            f"sealed_at_utc:   {sealed_at}\n"
            f"anchor_gap_days: {gap_days}   (proof date = anchor date, NOT asof)\n"
            "\nThis Merkle root commits to the engine-free forecast set sealed\n"
            "privately on the above date. Anchor this file with OpenTimestamps\n"
            "(Bitcoin) to prove it existed at that time; reveal individual\n"
            "forecasts with Merkle membership proofs as they are graded.\n")
    return public


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True, help="snapshot date, e.g. 2026-06-11")
    ap.add_argument("--ledger-dir", default=DEFAULT_LEDGER_DIR)
    args = ap.parse_args()
    pub = seal(args.asof, args.ledger_dir)
    print(f"sealed {pub['asof']}  chain_index={pub['chain_index']}  "
          f"leaves={pub['n_leaves']}  skipped={pub['n_skipped']}")
    print(f"  prev_commitment: {pub['prev_commitment'] or '(genesis)'}")
    print(f"  merkle_root:     {pub['merkle_root']}")
    print(f"  public  -> commitments/{pub['asof']}/COMMITMENT.txt  (anchor this)")
    print(f"  private -> seals_private/{pub['asof']}/  (gitignored, holds the leaves)")


if __name__ == "__main__":
    main()
