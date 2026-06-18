"""Engine-free commitment primitives for the Sigma public validation ledger.

Pure standard library. NO imports from the Sigma engine and NO market data.
This module turns a forward-ledger snapshot into a tamper-evident commitment:

    raw snapshot  --project-->  engine-free leaves  --hash-->  Merkle root
                                (one per ticker x horizon)      (the commitment)

The Merkle root is what we anchor to Bitcoin via OpenTimestamps. Committing to
the root lets us:
  * reveal a single forecast later (with a Merkle membership proof) WITHOUT
    revealing the others, and
  * let anyone recompute the root from the revealed leaves and check it against
    the anchored value -- trustless, no need to trust us.

Engine internals (seed, df, n_sims, return_model, engine_version, and every
derived risk metric) are intentionally EXCLUDED from the leaf, so the
commitment leaks no fingerprint of the model.

Canonicalization (must be reproducible in ANY language -- see README.md):
  * a leaf is a JSON object with exactly the keys produced by canonical_leaf(),
    every value rendered as a string;
  * numbers -> fixed NUM_DECIMALS-decimal text (e.g. -61.1 -> "-61.1000"),
    with negative zero normalized to "0.0000";
  * booleans -> "true" / "false";
  * serialize with json.dumps(obj, sort_keys=True, separators=(",", ":"),
    ensure_ascii=True); the SHA-256 of those UTF-8 bytes is the leaf hash;
  * leaf hashes are sorted ascending (hex) before the tree is built, so the
    commitment is independent of record order in the source snapshot.
"""
from __future__ import annotations

import hashlib
import json

# Fields copied verbatim from the raw snapshot record into the public leaf.
LEAF_STRING_FIELDS = ("ticker", "horizon", "asof")
LEAF_NUM_FIELDS = ("anchor_price", "p5", "p25", "p50", "p75", "p95", "prob_positive")
NUM_DECIMALS = 4


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fmt_num(v: float) -> str:
    """Deterministic fixed-decimal rendering; -0.0 normalized to 0.0."""
    x = float(v)
    if x == 0:
        x = 0.0
    return f"{x:.{NUM_DECIMALS}f}"


def canonical_leaf(rec: dict) -> dict | None:
    """Project one raw snapshot record to its engine-free canonical leaf.

    Returns None if the record is not a gradable forecast (non-"ok" status or a
    missing/invalid forecast band). The caller COUNTS such records as skipped --
    they are never silently dropped (survivorship discipline).
    """
    if rec.get("status") != "ok":
        return None
    for f in LEAF_STRING_FIELDS:
        if not isinstance(rec.get(f), str) or not rec.get(f):
            return None
    for f in LEAF_NUM_FIELDS:
        if not isinstance(rec.get(f), (int, float)):
            return None
    if not isinstance(rec.get("domain_in_domain"), bool):
        return None

    leaf: dict[str, str] = {
        "ticker": rec["ticker"],
        "horizon": rec["horizon"],
        "asof": rec["asof"],
        "domain_severity": str(rec.get("domain_severity", "")),
        "in_domain": "true" if rec["domain_in_domain"] else "false",
    }
    for f in LEAF_NUM_FIELDS:
        leaf[f] = _fmt_num(rec[f])
    return leaf


def leaf_hash(leaf: dict) -> str:
    blob = json.dumps(leaf, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256_hex(blob.encode("utf-8"))


def _combine(left: str, right: str) -> str:
    return sha256_hex(bytes.fromhex(left) + bytes.fromhex(right))


def merkle_root(hashes: list[str]) -> str:
    """Merkle root over `hashes` (assumed already in tree order).

    Odd node at a level is promoted unchanged (NOT duplicated) -- avoids the
    duplicate-leaf malleability of Bitcoin's scheme. n==0 -> SHA-256 of empty.
    """
    if not hashes:
        return sha256_hex(b"")
    level = list(hashes)
    while len(level) > 1:
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(_combine(level[i], level[i + 1]))
            else:
                nxt.append(level[i])  # odd one promoted unchanged
        level = nxt
    return level[0]


def merkle_proof(hashes: list[str], index: int) -> list[dict]:
    """Sibling path proving membership of leaf at `index` (in tree order).

    Each step is {"hash": <sibling hex>, "side": "left"|"right"} where `side`
    is the side the SIBLING sits on relative to the running node. A promoted
    odd node contributes no step at that level.
    """
    proof: list[dict] = []
    level = list(hashes)
    idx = index
    while len(level) > 1:
        if idx % 2 == 0:
            if idx + 1 < len(level):
                proof.append({"hash": level[idx + 1], "side": "right"})
        else:
            proof.append({"hash": level[idx - 1], "side": "left"})
        nxt: list[str] = []
        for i in range(0, len(level), 2):
            if i + 1 < len(level):
                nxt.append(_combine(level[i], level[i + 1]))
            else:
                nxt.append(level[i])
        level = nxt
        idx //= 2
    return proof


def verify_membership(a_leaf_hash: str, proof: list[dict], root: str) -> bool:
    """Recompute the root from one leaf hash + its sibling path."""
    h = a_leaf_hash
    for step in proof:
        if step["side"] == "right":
            h = _combine(h, step["hash"])
        elif step["side"] == "left":
            h = _combine(step["hash"], h)
        else:
            return False
    return h == root


def build_commitment(records: list[dict]) -> dict:
    """Project + hash + Merkle-commit a list of raw snapshot records.

    Returns a dict with the sorted canonical leaves (each carrying its
    leaf_hash), the ordered leaf-hash list (tree order), the Merkle root, and
    the skip count. This is the SEALED (private) structure; the public
    commitment exposes only `merkle_root` and metadata, never the leaves.
    """
    leaves: list[dict] = []
    n_skipped = 0
    for rec in records:
        leaf = canonical_leaf(rec)
        if leaf is None:
            n_skipped += 1
            continue
        leaf_with_hash = dict(leaf)
        leaf_with_hash["leaf_hash"] = leaf_hash(leaf)
        leaves.append(leaf_with_hash)
    # Sort by leaf hash so the commitment is order-independent.
    leaves.sort(key=lambda d: d["leaf_hash"])
    ordered_hashes = [d["leaf_hash"] for d in leaves]
    return {
        "leaves": leaves,
        "ordered_leaf_hashes": ordered_hashes,
        "merkle_root": merkle_root(ordered_hashes),
        "n_leaves": len(leaves),
        "n_skipped": n_skipped,
    }
