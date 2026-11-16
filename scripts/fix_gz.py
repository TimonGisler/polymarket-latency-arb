#!/usr/bin/env python3
"""Repair recorder files damaged by a restart. A killed recorder leaves a gzip member without its end; the next
start appends a new member to the same hour file, and normal readers (gzip, zcat) then stop at the junction and lose
everything after it. This rewrites such a file as one clean gzip with every complete line of every member.
Skips the current hour (the recorder has those files open). Originals go to data/ext/crypto/live_damaged/.

    python3 scripts/fix_gz.py [--dry]      # run after the hour in which the recorder was restarted has ended
"""
import glob, gzip, os, subprocess, sys, time, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = ROOT + "/data/ext/crypto/live"
KEEP = ROOT + "/data/ext/crypto/live_damaged"


def members(raw, name):
    """byte offsets where a gzip member written by live_fwd.py starts (header with this file's name in it)"""
    mark, out, i = b"\x1f\x8b\x08\x08", [], 0
    while (i := raw.find(mark, i)) >= 0:
        if raw[i + 10:i + 10 + len(name) + 1] == name + b"\x00":
            out.append(i)
        i += 1
    return out


def repair(path, dry):
    raw = open(path, "rb").read()
    offs = members(raw, os.path.basename(path)[:-3].encode())
    if not offs or offs[0] != 0:
        return f"{os.path.basename(path)}: unknown layout, left alone"
    tmp, lines, cut = path + ".tmp", 0, 0
    with gzip.open(tmp, "wb", compresslevel=5) as out:
        for a, b in zip(offs, offs[1:] + [len(raw)]):
            d, carry = zlib.decompressobj(31), b""
            try:
                for k in range(a, b, 1 << 20):
                    carry += d.decompress(raw[k:min(k + (1 << 20), b)])
                    done, _, carry = carry.rpartition(b"\n")
                    if done:
                        out.write(done + b"\n"); lines += done.count(b"\n") + 1
            except zlib.error:
                pass                      # the member's unfinished end
            cut += bool(carry)            # a last line without its end is dropped
    msg = f"{os.path.basename(path)}: {len(offs)} parts, {lines} lines kept, {cut} unfinished lines dropped"
    if dry:
        os.remove(tmp); return msg + " (dry)"
    os.makedirs(KEEP, exist_ok=True)
    os.replace(path, KEEP + "/" + os.path.basename(path)); os.replace(tmp, path)
    return msg


if __name__ == "__main__":
    dry, now = "--dry" in sys.argv, time.strftime("%Y%m%d_%H", time.gmtime())
    for p in sorted(glob.glob(LIVE + "/*.jsonl.gz")):
        if os.path.basename(p).startswith(now):
            continue
        if subprocess.run(["gzip", "-t", p], capture_output=True).returncode:
            print(repair(p, dry))
