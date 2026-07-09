# Sigma · Public Validation Ledger

A tamper-evident, prospective track record for **Sigma Risk Intelligence**.

Sigma forecasts a full return distribution (P5/P25/P50/P75/P95 + `prob_positive`)
for each name in a pinned universe, at multiple horizons, every month. This
repository commits to those forecasts **before the outcomes are known**, then
grades them as reality arrives. It is the one asset that cannot be backfilled:
a forecast only counts if it was provably made *before* the outcome.

This repo is **engine-free**. It contains no model code and no engine
internals — only forecast commitments and, once graded, the realized outcomes.

---

## Trust model — why these numbers can't be faked

> ⚠️ **First-cohort limitation (2026-06-11).** This genesis snapshot was sealed
> and Bitcoin-anchored on **2026-06-18** — seven days after its `asof` label,
> because the public-ledger infrastructure was built that day. **The
> cryptographic proof date is the anchor date, not `asof`.** For those seven
> days the outcomes were already observable, so this first cohort must be given
> **near-zero calibration weight**. Every subsequent cohort is sealed within
> ~1 day of its `asof`, so its proof is tight. The gap is recorded
> machine-readably as `sealed_anchor_gap_days` in each commitment (`7` here, `0`
> going forward).

Two independent guarantees:

1. **Integrity (a commitment hash).** Each monthly snapshot is projected to a
   set of engine-free *leaves* — one per `(ticker, horizon)`, carrying the
   forecast band and nothing about how the engine computed it. The leaves are
   hashed (SHA-256) and combined into a **Merkle root** (`commitments/<asof>/`).
   Change one digit of one forecast and the root changes.

2. **Time (a Bitcoin anchor).** The Merkle root is timestamped with
   [OpenTimestamps](https://opentimestamps.org), which commits it into the
   Bitcoin blockchain. Anyone can later prove the root existed at-or-before a
   given block — independently of GitHub, of us, and of this repo's git history
   (git timestamps are author-settable and prove nothing on their own).

Together: the forecast set is *fixed* by the hash and *dated* by Bitcoin. We
cannot alter a forecast after the fact, nor backdate one we made later.

### Sealed envelope + reveal-at-grading

We publish the **commitment** (the Merkle root) for every snapshot immediately,
but the **forecasts themselves are revealed per name as they are graded** —
each with a Merkle membership proof that ties it back to the already-anchored
root. This proves pre-registration without dumping the whole forecast set (and
its distributional fingerprint) up front. The unrevealed leaves live only in
`seals_private/` (gitignored), never pushed until reveal.

---

## What's committed (the leaf)

Exactly these fields, all rendered as strings:

| key | meaning |
|-----|---------|
| `ticker`, `horizon`, `asof` | which forecast |
| `anchor_price` | price at forecast time (basis for the realized return) |
| `p5 p25 p50 p75 p95` | forecast return band, percent |
| `prob_positive` | P(return > 0), percent — the directional claim |
| `in_domain`, `domain_severity` | out-of-domain honesty flag |

Deliberately **excluded** (engine fingerprint): `seed`, `df`, `n_sims`,
`return_model`, `engine_version`, and all derived risk metrics (vol, Sharpe,
Sortino, Calmar, CVaR, drawdown).

## Canonicalization (reproducible in any language)

- Leaf = JSON object with the keys above, every value a string.
- Numbers → fixed 4-decimal text (`-61.1` → `"-61.1000"`); `-0.0` → `"0.0000"`.
- Booleans → `"true"` / `"false"`.
- Serialize: `json.dumps(leaf, sort_keys=True, separators=(",", ":"),
  ensure_ascii=True)`; the SHA-256 of those UTF-8 bytes is the leaf hash.
- Leaf hashes are sorted ascending (hex) before the Merkle tree is built, so
  the root is independent of source record order. Odd node at a level is
  promoted unchanged (not duplicated).

## How to verify

**What's externally verifiable, and when.** Before the first grading, a public
cloner can confirm only that the commitment root *exists* and is *Bitcoin-
timestamped*: `--chain` checks internal link consistency and `--selftest`
exercises the machinery on synthetic data. The 400 real forecasts stay sealed,
so their *contents* cannot be independently recomputed yet — `--seal` needs a
revealed sealed file, which is published per name as it matures. In short: the
root's existence + timestamp are checkable today; each forecast becomes
checkable when it is revealed at grading.

```bash
python -X utf8 verify.py --selftest                 # the machinery itself
python -X utf8 verify.py --chain commitments        # no snapshot reordered
python -X utf8 verify.py --seal <revealed sealed file>   # leaves -> root
ots verify commitments/<asof>/COMMITMENT.txt.ots    # root existed at block T
```

## Honest caveats

- **The clock starts at the first anchor.** The 2026-06-11 snapshot is anchored
  on the day this infrastructure was built (later than 06-11); its
  cryptographic date is that anchor date, not 06-11. Every snapshot from then
  on is anchored the day it is generated, so its proof is airtight.
- **Low statistical power early.** The first months carry n = 1, 2, 3… per
  horizon, with very wide Wilson confidence intervals. The first meaningful
  read is the 1-month horizon after ~3 cohorts; the 1-year horizon after ~12
  months. Coverage is always reported with its CI; early numbers must not be
  over-read.
- **Interval coverage is the calibration claim — not P50.** Sigma deliberately
  under-promises the median on growth/AI names (a disclosed conservative bias).
  Read `prob_positive` for direction and the P5–P95 band for risk; treat P50 as
  a conservative anchor, not a point prediction.

## Pre-registered calibration policy

How (and whether) the engine's calibration may change in response to ledger
outcomes is itself pre-registered and Bitcoin-anchored **before any such
decision has been made**: see [`CALIBRATION_PROTOCOL.md`](CALIBRATION_PROTOCOL.md)
(+ its `.ots` proof). Rules are mechanical (metric → threshold → number of
cohorts → which knob unlocks), changes are prospective-only, and sealed
cohorts are always graded under the parameters they sealed. A protocol that
exists before the first knob is turned is the counterpart of forecasts that
exist before the outcome.

## Layout

```
ledger_core.py          commitment primitives (project → hash → Merkle)
seal.py                 seal one snapshot → commitment (public) + envelope (private)
verify.py               independent verifier + self-test
CALIBRATION_PROTOCOL.md pre-registered calibration rules (anchored, amend-prospectively)
commitments/<asof>/     PUBLIC: COMMITMENT.txt (anchor this) + commitment_<asof>.json
seals_private/<asof>/   PRIVATE (gitignored): the sealed leaves, until revealed
```
