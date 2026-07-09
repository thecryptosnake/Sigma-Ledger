# Calibration Protocol — pre-registered

**Version:** 1.0 · **Effective:** 2026-07-09 (UTC) · **Status:** in force

This document pre-registers how the Sigma engine's calibration may be changed
in response to outcomes recorded in this public ledger. It exists so that
calibration is a **mechanical consequence of pre-stated rules**, not a
post-hoc fit to whatever the rank histogram looks like. The file is committed
to this repository and anchored to Bitcoin via OpenTimestamps
(`CALIBRATION_PROTOCOL.md.ots`); any amendment must be committed and anchored
**before** it governs a decision (see §8).

**Honest timeline note.** This protocol postdates the genesis commitment
(2026-06-11, anchored 2026-06-18) and snapshot #1 (2026-07-09). It predates
every calibration decision: as of the effective date, **zero engine parameters
have been changed** in response to ledger outcomes. Both existing cohorts were
generated under the frozen defaults listed in §7.

---

## 1. Scope and definitions

- **Cohort** — all forecasts of one snapshot (one `asof`), per horizon.
  A monthly cohort is treated as **one draw of the market** per cell, not as
  N independent observations (names within a cohort share regime and factor
  exposure; see §5).
- **Cell** — the unit calibration is judged on:
  `horizon × universe_version × generation regime`. GICS sector sub-cells
  (sp500_v1) are diagnostic, not decision-bearing.
- **Generation regime** — from the sealed snapshot header:
  `vix_at_generation < 20` → **calm**; `≥ 20` → **elevated**.
  (Genesis: 22.22 = elevated. Snapshot #1: 16.9 = calm.)
- **Maturity** — true calendar months from `asof` (1m/3m/6m/1y/2y).

## 2. Grading conventions (binding)

Realized return for a record is measured **within a single
adjustment-consistent price series** fetched at grading time:

- **Anchor bar** = last completed close **strictly before** `asof`
  (snapshots are generated pre-open UTC; the recorded `anchor_price` is that
  bar in its generation-time basis and remains the sealed reference).
- **Maturity bar** = first close **on/after** the maturity date, within a
  7-calendar-day tolerance; otherwise the record is
  `unresolved_possible_delisting` — **counted, never dropped**.
- `realized = maturity_bar / anchor_bar − 1`, both bars taken from the same
  split- and dividend-adjusted series. This makes grading invariant to
  corporate actions between sealing and grading (splits, dividends).
- A delisted name is graded as a terminal outcome at its terminal print,
  never removed from the denominator.

## 3. Instruments

Computed per cohort at each maturity, per cell, and pooled cohort-wise:

1. **Interval coverage** — share of realized returns inside [P5, P95].
   Wilson 95% interval (z = 1.959963985) reported alongside, with the §5
   caveat. **Acceptance corridor: [90%, 96%]** (design 90%; bounded
   over-coverage is an accepted product property, unbounded is not).
2. **Rank histogram** — 6 bins (<P5, P5–P25, P25–P50, P50–P75, P75–P95,
   >P95) vs design {5, 20, 25, 25, 20, 5}%.
3. **CRPS** — per-record continuous ranked probability score against the
   sealed quantile grid (engine methodology `crps.py`); cohort mean and
   cross-cohort trend.
4. **Direction** — Brier score and reliability curve for
   `prob_positive / 100` against the binary outcome `realized > 0`.
5. **Drift bias** — median(realized − P50) per cell.

## 4. Decision rules

No engine or output parameter changes except through these rules. "Cohorts"
below means **consecutive monthly cohorts of the same horizon**, and every
rule requires the qualifying window to span **both generation regimes**
(≥1 calm and ≥1 elevated) unless stated otherwise.

| Rule | Watches | Trigger | Action unlocked | Kill / guard |
|---|---|---|---|---|
| **R1 — drift** | median bias vs P50 | same sign in ≥3 cohorts AND pooled \|median\| > 3pp × √(horizon months) | review of the drift blend's regime damping (engine change; maintainer approval required) | if bias sign is regime-conditional, the adjustment must be regime-conditional; a change may not widen pooled CRPS |
| **R2 — direction map** | Brier of prob_positive | ≥3 cohorts AND ≥240 graded records at the target horizon | fit **isotonic (monotone) recalibration** of `prob_positive` — output layer only, MC internals untouched | leave-one-cohort-out CV; adopt only if mean OOS Brier improves ≥2% relative vs identity; otherwise identity stands. Adopted maps are versioned (`calmap-1`, …) and disclosed in subsequent commitment headers |
| **R3 — width** | interval coverage | pooled cohort-level coverage outside [90, 96]% across ≥4 cohorts spanning both regimes | review of variance/tail-width parameters (vol scale, Student-t df) | never triggered by a single regime's cohorts: empty tails in a month where volatility fell is insurance that did not pay out, not evidence of over-pricing |
| **R4 — upper tail** | >P95 breach share | > 5% at cohort level in ≥3 cohorts within a group | unparks the parked heavy-upper-tail work (jump-diffusion / power-law amplifier) for review | stays parked otherwise; single-name melt-ups inside P95 are in-design |

## 5. Effective sample size discipline

Names within a cohort are correlated (shared month, shared regime, shared
factors). Therefore:

- Record-level Wilson intervals are reported but **never sufficient** to
  trigger a rule on their own; rules count **cohorts**, not records.
- Cross-cohort inference treats each cohort as one observation per cell.
- Any pooled record-level statistic quoted in ledger reports must carry an
  explicit `n_eff < n` caveat.

## 6. Change control

- Rules unlock a **review**, not an automatic parameter change; every engine
  change additionally requires explicit maintainer approval.
- Changes are **prospective only**: a sealed cohort is graded against the
  bands it sealed, under the engine version recorded in its snapshot
  (`engine_version`). Nothing is ever regraded under new parameters.
- Every change lands as: new engine version tag in subsequent snapshots +
  a disclosure note in the next commitment's metadata.
- Direction maps (R2) transform published probabilities of **future**
  snapshots only; sealed `prob_positive` values are graded as sealed.

## 7. Status quo declaration (frozen until a rule fires)

Forward-sweep engine defaults as of this protocol's effective date:
Monte Carlo n = 50,000 paths per (ticker × horizon); Student-t innovations
df = 5; GARCH(1,1) MLE volatility; drift blend 0.4 editorial / 0.4 realized /
0.2 CAPM with regime-conditional damping; per-record deterministic seed
crc32(ticker|horizon|asof); universes pinned additions-only, removals never.

## 8. Amendment rule

This protocol may be amended only prospectively: the amended version must be
committed to this repository and OTS-anchored **before** any decision is
taken under it. Superseded versions remain in git history; the anchor chain
of `.ots` proofs is the audit trail that no rule was written after the
outcome it was applied to.
