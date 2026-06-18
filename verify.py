"""Independent verifier for Sigma public-ledger commitments. Stdlib only.

  python -X utf8 verify.py --selftest
      Build synthetic seals (n = 1, 2, 3, 5), verify the root, generate and
      check a membership proof for every leaf, then tamper one leaf and assert
      the root no longer matches and the proof fails.

  python -X utf8 verify.py --seal seals_private/2026-06-11/sealed_2026-06-11.json
      Recompute every leaf hash from its canonical fields, rebuild the Merkle
      root, and confirm it equals the sealed root.

  python -X utf8 verify.py --chain commitments
      Walk the commitment chain (by chain_index) and confirm each
      prev_commitment matches the previous commitment's root.

Anchor (timestamp) verification is separate and trustless: `ots verify
commitments/<asof>/COMMITMENT.txt.ots` against the Bitcoin blockchain.
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import ledger_core as core

LEAF_KEYS = ("ticker", "horizon", "asof", "domain_severity", "in_domain",
             "anchor_price", "p5", "p25", "p50", "p75", "p95", "prob_positive")


def _canonical_only(leaf: dict) -> dict:
    """Strip leaf_hash (and anything else) down to the canonical hashed keys."""
    return {k: leaf[k] for k in LEAF_KEYS}


def verify_seal(path: str) -> bool:
    with open(path, encoding="utf-8") as f:
        sealed = json.load(f)
    ok = True
    recomputed = []
    for leaf in sealed["leaves"]:
        h = core.leaf_hash(_canonical_only(leaf))
        if h != leaf.get("leaf_hash"):
            print(f"  LEAF HASH MISMATCH: {leaf.get('ticker')} {leaf.get('horizon')}")
            ok = False
        recomputed.append(h)
    recomputed.sort()
    if recomputed != sealed["ordered_leaf_hashes"]:
        print("  ORDERED LEAF-HASH LIST MISMATCH")
        ok = False
    root = core.merkle_root(sealed["ordered_leaf_hashes"])
    if root != sealed["merkle_root"]:
        print(f"  ROOT MISMATCH: recomputed {root} != sealed {sealed['merkle_root']}")
        ok = False
    print(f"{'OK ' if ok else 'FAIL'} seal {sealed['asof']}  "
          f"leaves={len(sealed['leaves'])}  root={sealed['merkle_root'][:16]}...")
    return ok


def verify_chain(commit_dir: str) -> bool:
    commits = []
    for path in glob.glob(os.path.join(commit_dir, "*", "commitment_*.json")):
        with open(path, encoding="utf-8") as f:
            commits.append(json.load(f))
    commits.sort(key=lambda c: c.get("chain_index", 0))
    if not commits:
        print("  (no commitments found)")
        return True
    ok = True
    prev_root = None
    for c in commits:
        if c.get("prev_commitment") != prev_root:
            print(f"  CHAIN BREAK at {c['asof']}: prev_commitment "
                  f"{c.get('prev_commitment')} != expected {prev_root}")
            ok = False
        prev_root = c.get("merkle_root")
    print(f"{'OK ' if ok else 'FAIL'} chain  links={len(commits)}  head={prev_root[:16]}...")
    return ok


def _synthetic_records(n: int) -> list[dict]:
    recs = []
    for i in range(n):
        recs.append({
            "ticker": f"TST{i:02d}", "horizon": "1m", "asof": "2026-06-11",
            "status": "ok", "anchor_price": 100.0 + i, "p5": -20.0 - i,
            "p25": -8.0, "p50": 1.0 + i, "p75": 12.0, "p95": 40.0 + i,
            "prob_positive": 50.0 + i, "domain_in_domain": (i % 2 == 0),
            "domain_severity": "green" if i % 2 == 0 else "red",
            "seed": 123, "df": 18, "engine_version": "secret",  # must be ignored
        })
    return recs


def selftest() -> bool:
    ok = True
    for n in (1, 2, 3, 5):
        comm = core.build_commitment(_synthetic_records(n))
        if comm["n_leaves"] != n:
            print(f"  n={n}: leaf count {comm['n_leaves']} != {n}"); ok = False
        root = comm["merkle_root"]
        hashes = comm["ordered_leaf_hashes"]
        # every leaf must produce a valid membership proof
        for idx, h in enumerate(hashes):
            proof = core.merkle_proof(hashes, idx)
            if not core.verify_membership(h, proof, root):
                print(f"  n={n}: membership proof FAILED for leaf {idx}"); ok = False
        # tamper: flip one leaf's p50 and confirm the root changes
        tampered = _synthetic_records(n)
        tampered[0]["p50"] = 999.0
        if core.build_commitment(tampered)["merkle_root"] == root:
            print(f"  n={n}: TAMPER NOT DETECTED (root unchanged)"); ok = False
        # a stale proof from the original tree must fail against itself if the
        # leaf hash is altered
        bad_proof = core.merkle_proof(hashes, 0)
        if core.verify_membership("00" * 32, bad_proof, root):
            print(f"  n={n}: forged leaf accepted"); ok = False
        # engine internals must not leak into the leaf
        leaf0 = comm["leaves"][0]
        if any(k in leaf0 for k in ("seed", "df", "engine_version", "return_model")):
            print(f"  n={n}: ENGINE INTERNAL LEAKED into leaf"); ok = False
        print(f"  n={n}: root={root[:16]}...  membership+tamper+leak checks "
              f"{'OK' if ok else 'FAIL'}")
    print(f"{'OK  ' if ok else 'FAIL'} selftest")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seal", help="verify a sealed_<asof>.json file")
    ap.add_argument("--chain", help="verify the commitment chain under this dir")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    results = []
    if args.selftest:
        results.append(selftest())
    if args.seal:
        results.append(verify_seal(args.seal))
    if args.chain:
        results.append(verify_chain(args.chain))
    if not results:
        ap.error("nothing to do: pass --selftest, --seal, and/or --chain")
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
