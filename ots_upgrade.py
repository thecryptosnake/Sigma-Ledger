"""Upgrade pending OTS proofs to confirmed Bitcoin attestations (core lib).

For each <file>.ots: query the calendar servers referenced inside the proof
for the completed attestation path, merge it, and rewrite the .ots IN PLACE
(the digest binding is unchanged — an upgrade only ADDS the Bitcoin path).
Prints the attested block heights. Refuses to touch a proof that already
holds a Bitcoin attestation unless it still carries pendings too.

Usage:  python -X utf8 ots_upgrade.py <file1> [<file2> ...]
"""
from __future__ import annotations

import hashlib
import sys

from opentimestamps.calendar import RemoteCalendar
from opentimestamps.core.notary import (BitcoinBlockHeaderAttestation,
                                        PendingAttestation)
from opentimestamps.core.serialize import (BytesDeserializationContext,
                                           StreamSerializationContext)
from opentimestamps.core.timestamp import DetachedTimestampFile


def walk(ts, out):
    for a in ts.attestations:
        out.append((ts, a))
    for _op, sub in ts.ops.items():
        walk(sub, out)


def upgrade(path: str) -> bool:
    raw = open(path, "rb").read()
    dtf = DetachedTimestampFile.deserialize(BytesDeserializationContext(raw))

    src_path = path[:-4] if path.endswith(".ots") else None
    if src_path:
        actual = hashlib.sha256(open(src_path, "rb").read()).digest()
        assert dtf.file_digest == actual, f"digest mismatch vs {src_path}"

    pairs: list = []
    walk(dtf.timestamp, pairs)
    heights = sorted({a.height for _t, a in pairs
                      if isinstance(a, BitcoinBlockHeaderAttestation)})
    pendings = [(t, a) for t, a in pairs if isinstance(a, PendingAttestation)]
    if heights and not pendings:
        print(f"  {path}: already confirmed at {heights}, nothing to do")
        return False

    upgraded = 0
    for stamp, att in pendings:
        uri = att.uri
        try:
            cal_ts = RemoteCalendar(uri).get_timestamp(stamp.msg, timeout=20)
            stamp.merge(cal_ts)
            upgraded += 1
            print(f"  ok   {uri}")
        except Exception as exc:
            print(f"  skip {uri}: {str(exc)[:80]}")

    pairs2: list = []
    walk(dtf.timestamp, pairs2)
    heights2 = sorted({a.height for _t, a in pairs2
                       if isinstance(a, BitcoinBlockHeaderAttestation)})
    if not heights2:
        print(f"  {path}: still pending (no calendar returned a Bitcoin path)")
        return False

    with open(path, "wb") as f:
        dtf.serialize(StreamSerializationContext(f))
    print(f"  {path}: CONFIRMED at Bitcoin heights {heights2} "
          f"({upgraded} calendar path(s) merged, rewritten in place)")
    return True


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: ots_upgrade.py <file.ots> [...]")
    any_up = False
    for p in sys.argv[1:]:
        print(p)
        any_up |= upgrade(p)
    sys.exit(0 if any_up else 2)


if __name__ == "__main__":
    main()
