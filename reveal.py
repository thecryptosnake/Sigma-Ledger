"""Reveal one matured horizon cohort from a private seal, with Merkle proofs.

  python -X utf8 reveal.py --asof 2026-06-11 --horizon 1m \
      [--grades <path to Sigma grades_<date>.json>] [--out reveals]

Opens the sealed envelope for ONE (asof, horizon) cohort: every committed
leaf of that horizon is published verbatim together with its Merkle
membership proof against the Bitcoin-anchored root. ALL leaves of the
matured horizon are revealed -- graded, unresolved, good or bad. Nothing is
dropped (survivorship discipline).

The output file has two layers with different trust properties:

  leaf + merkle_proof   COVERED by the anchored commitment. Anyone can
      recompute each leaf hash from its canonical fields and walk the proof
      to the root committed before maturity (verify.py --reveal).

  grade + rollup        Our MEASUREMENT ANNOTATION, not covered by the
      commitment. Grading convention: public CALIBRATION_PROTOCOL.md section 2
      (single adjusted series; anchor bar = last close strictly before asof).
      A skeptic should recompute grades from any adjusted price series using
      the revealed bands -- the bands are the committed claim, the grades are
      arithmetic on top.

Fail-closed: every proof is verified in-process before writing, and the
sealed root must equal the published commitment root for that asof.

Pure standard library; no engine import, no network.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import datetime, timezone

import ledger_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
PRIVATE_DIR = os.path.join(HERE, "seals_private")
PUBLIC_DIR = os.path.join(HERE, "commitments")
DEFAULT_OUT_DIR = os.path.join(HERE, "reveals")
REVEAL_SCHEMA = "sigma-public-reveal-1"

Z_95_TWO_SIDED = 1.959963985  # two-sided 95% normal quantile, for Wilson CI

# Rank-histogram bins over the committed band, lower-edge-strict (a realized
# return exactly on a quantile falls in the bin ABOVE it, matching the
# grader's below_<q> = realized < q convention). Nominal mass under a
# perfectly calibrated band:
RANK_BINS = (("below_p5", 5.0), ("p5_p25", 20.0), ("p25_p50", 25.0),
             ("p50_p75", 25.0), ("p75_p95", 20.0), ("at_or_above_p95", 5.0))


def wilson_ci(k: int, n: int, z: float = Z_95_TWO_SIDED) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, as percentages."""
    if n == 0:
        return (0.0, 100.0)
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return (max(0.0, center - half) * 100.0, min(1.0, center + half) * 100.0)


def _rank_bin(realized: float, leaf: dict) -> str:
    """Which committed-band bin the realized return falls in."""
    edges = [float(leaf[q]) for q in ("p5", "p25", "p50", "p75", "p95")]
    for (name, _), edge in zip(RANK_BINS[:-1], edges):
        if realized < edge:
            return name
    return RANK_BINS[-1][0]


def _load_json(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _index_grades(grades_doc: dict, asof: str) -> dict:
    """(ticker, horizon) -> grade record, restricted to this snapshot asof."""
    if grades_doc.get("snapshot_asof") not in (None, asof):
        raise SystemExit(f"grades file is for snapshot {grades_doc.get('snapshot_asof')!r}, "
                         f"not {asof!r}")
    out = {}
    for g in grades_doc.get("grades", []):
        if g.get("asof") == asof:
            out[(g.get("ticker"), g.get("horizon"))] = g
    return out


def build_rollup(entries: list[dict]) -> dict:
    """Self-contained calibration read, recomputable from this file alone:
    in-band coverage (+ Wilson CI), rank histogram vs nominal, median bias.
    Derived from (leaf bands, grade.realized_pct) only."""
    graded = [e for e in entries
              if e.get("grade") and e["grade"].get("grade_status") == "graded"]
    unresolved = len(entries) - len(graded)
    rollup: dict = {
        "n_revealed": len(entries),
        "n_graded": len(graded),
        "n_unresolved": unresolved,
        "caveat": ("one cohort = ONE market draw; the names are cross-"
                   "correlated, so n_effective is far below n_graded. "
                   "Judge calibration across cohorts, not within one."),
    }
    if not graded:
        return rollup
    in_band, biases, hist = 0, [], {name: 0 for name, _ in RANK_BINS}
    for e in graded:
        leaf, r = e["leaf"], float(e["grade"]["realized_pct"])
        if float(leaf["p5"]) <= r <= float(leaf["p95"]):
            in_band += 1
        biases.append(r - float(leaf["p50"]))
        hist[_rank_bin(r, leaf)] += 1
    n = len(graded)
    lo, hi = wilson_ci(in_band, n)
    rollup.update({
        "coverage_p5_p95": {"in_band": in_band, "n": n,
                            "pct": round(100.0 * in_band / n, 1),
                            "nominal_pct": 90.0,
                            "wilson_95_ci_pct": [round(lo, 1), round(hi, 1)]},
        "median_bias_vs_p50_pp": round(statistics.median(biases), 2),
        "rank_histogram": {name: {"count": hist[name],
                                  "pct": round(100.0 * hist[name] / n, 1),
                                  "nominal_pct": nominal}
                           for name, nominal in RANK_BINS},
    })
    return rollup


def reveal(asof: str, horizon: str, grades_path: str | None,
           out_dir: str) -> dict:
    sealed = _load_json(os.path.join(PRIVATE_DIR, asof, f"sealed_{asof}.json"))
    public = _load_json(os.path.join(PUBLIC_DIR, asof, f"commitment_{asof}.json"))
    root = sealed["merkle_root"]
    if public["merkle_root"] != root:
        raise SystemExit(f"sealed root {root} != published commitment root "
                         f"{public['merkle_root']} -- refusing to reveal")

    hashes: list[str] = sealed["ordered_leaf_hashes"]
    index_of = {h: i for i, h in enumerate(hashes)}
    grades_doc = _load_json(grades_path) if grades_path else None
    grades = _index_grades(grades_doc, asof) if grades_doc else {}

    entries: list[dict] = []
    for leaf in sealed["leaves"]:
        if leaf["horizon"] != horizon:
            continue
        canonical = {k: v for k, v in leaf.items() if k != "leaf_hash"}
        h = core.leaf_hash(canonical)
        if h != leaf["leaf_hash"]:
            raise SystemExit(f"leaf hash mismatch for {leaf['ticker']} -- seal corrupt?")
        proof = core.merkle_proof(hashes, index_of[h])
        if not core.verify_membership(h, proof, root):
            raise SystemExit(f"membership proof FAILED for {leaf['ticker']} -- aborting")
        entries.append({"leaf": canonical, "leaf_hash": h, "merkle_proof": proof,
                        "grade": grades.get((leaf["ticker"], horizon))})
    if not entries:
        raise SystemExit(f"no leaves for horizon {horizon!r} in seal {asof}")
    entries.sort(key=lambda e: e["leaf"]["ticker"])

    n_graded = sum(1 for e in entries
                   if e["grade"] and e["grade"].get("grade_status") == "graded")
    doc = {
        "schema": REVEAL_SCHEMA,
        "asof": asof,
        "horizon": horizon,
        "chain_index": sealed["chain_index"],
        "merkle_root": root,
        "commitment_file": f"commitments/{asof}/commitment_{asof}.json",
        "n_revealed": len(entries),
        "n_leaves_total_in_seal": sealed["n_leaves"],
        "revealed_at_utc": datetime.now(timezone.utc).isoformat(),
        "grading_convention": grades_doc.get("grading_convention") if grades_doc else None,
        "note": ("leaf + merkle_proof are covered by the Bitcoin-anchored "
                 "commitment (verify.py --reveal). grade + rollup are our "
                 "measurement annotation, NOT covered by the commitment -- "
                 "recompute them from any adjusted price series using the "
                 "revealed bands (CALIBRATION_PROTOCOL.md section 2). All "
                 "leaves of the matured horizon are revealed; unresolved "
                 "grades are counted, never dropped."),
        "rollup": build_rollup(entries),
        "reveals": entries,
    }

    dest_dir = os.path.join(out_dir, asof, horizon)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"reveals_{asof}_{horizon}.json")
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=1, sort_keys=True)
        f.write("\n")
    doc["_dest"] = dest
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True, help="seal date, e.g. 2026-06-11")
    ap.add_argument("--horizon", required=True, help="matured horizon, e.g. 1m")
    ap.add_argument("--grades", default=None,
                    help="optional Sigma grades_<date>.json to annotate with")
    ap.add_argument("--out", default=DEFAULT_OUT_DIR,
                    help="output root (default: reveals/ in this repo)")
    args = ap.parse_args()
    doc = reveal(args.asof, args.horizon, args.grades, args.out)
    r = doc["rollup"]
    print(f"revealed {doc['asof']} {doc['horizon']}  "
          f"leaves={doc['n_revealed']}/{doc['n_leaves_total_in_seal']}  "
          f"graded={r['n_graded']}  unresolved={r['n_unresolved']}")
    if r.get("coverage_p5_p95"):
        c = r["coverage_p5_p95"]
        print(f"  coverage P5-P95: {c['in_band']}/{c['n']} = {c['pct']}%  "
              f"(nominal 90, Wilson95 {c['wilson_95_ci_pct']})")
        print(f"  median bias vs P50: {r['median_bias_vs_p50_pp']:+.2f}pp")
    print(f"  all {doc['n_revealed']} membership proofs verified against root "
          f"{doc['merkle_root'][:16]}...")
    print(f"  -> {doc['_dest']}")


if __name__ == "__main__":
    main()
