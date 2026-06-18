"""Anchor a commitment file to Bitcoin via OpenTimestamps (core lib only).

  python -X utf8 ots_stamp.py commitments/2026-06-11/COMMITMENT.txt

Bypasses the `ots` CLI, which fails to import on Windows/Py3.12 because
python-bitcoinlib eagerly loads OpenSSL for EC operations that stamping never
needs. This uses the opentimestamps CORE library: it hashes the file, adds a
random nonce, submits the digest to the public calendar servers, and writes a
standard detached `<file>.ots` proof.

The proof is "pending" until the calendars' aggregation is confirmed in a
Bitcoin block (a few hours). Upgrade/verify it later with any working OTS
verifier (opentimestamps.org drag-drop, or `ots upgrade`/`ots verify` on a
machine where the CLI works) -- the `.ots` is the standard portable format,
independent of which tool created it.

No engine import, no secrets; network only to the OTS calendars. Replicates
otsclient.cmds.stamp_command (read from the installed package, not guessed).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import datetime, timezone

from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.op import OpAppend, OpSHA256
from opentimestamps.core.serialize import StreamSerializationContext
from opentimestamps.core.timestamp import DetachedTimestampFile

# Default public calendars, verbatim from otsclient/cmds.py (the real client).
CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://a.pool.eternitywall.com",
    "https://ots.btc.catallaxy.com",
)
PER_CALENDAR_TIMEOUT = 20  # seconds


def stamp(path: str) -> str:
    ots_path = path + ".ots"
    if os.path.exists(ots_path):
        raise SystemExit(f"refusing to overwrite existing proof: {ots_path}")

    with open(path, "rb") as fd:
        file_timestamp = DetachedTimestampFile.from_fd(OpSHA256(), fd)

    # Random nonce so a detached proof cannot leak the digests of sibling files.
    nonce_appended = file_timestamp.timestamp.ops.add(OpAppend(os.urandom(16)))
    tip = nonce_appended.ops.add(OpSHA256())

    merged: list[str] = []
    for url in CALENDARS:
        try:
            cal_ts = RemoteCalendar(url).submit(tip.msg, timeout=PER_CALENDAR_TIMEOUT)
            tip.merge(cal_ts)
            merged.append(url)
            print(f"  ok   {url}")
        except Exception as exc:  # calendar down / timeout -> skip, keep the rest
            print(f"  skip {url}: {exc}")
    if not merged:
        raise SystemExit("no calendar responded; nothing anchored")

    with open(ots_path, "xb") as out:
        file_timestamp.serialize(StreamSerializationContext(out))
    print(f"wrote {ots_path}  (pending; {len(merged)}/{len(CALENDARS)} calendars)")
    _update_commitment_json(path, ots_path, merged)
    return ots_path


def _update_commitment_json(src_path: str, ots_path: str, calendars: list[str]) -> None:
    """If a commitment_*.json sits beside the stamped file, flag it anchored."""
    d = os.path.dirname(os.path.abspath(src_path))
    for cj in glob.glob(os.path.join(d, "commitment_*.json")):
        with open(cj, encoding="utf-8") as f:
            obj = json.load(f)
        obj["anchor"] = {
            "status": "pending",
            "method": "opentimestamps-bitcoin",
            "ots_file": os.path.basename(ots_path),
            "calendars": calendars,
            "stamped_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": "pending Bitcoin confirmation; upgrade+verify with any OTS verifier",
        }
        with open(cj, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
        print(f"  updated {os.path.basename(cj)} anchor -> pending")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="file to anchor, e.g. commitments/<asof>/COMMITMENT.txt")
    args = ap.parse_args()
    stamp(args.file)


if __name__ == "__main__":
    main()
