#!/usr/bin/env python3
import json, glob, os, re

D = os.path.dirname(os.path.abspath(__file__))


def ts(sec):
    sec = int(sec)
    return f"{sec//60:d}:{sec%60:02d}"


for p in sorted(glob.glob(os.path.join(D, "subs", "*.en.json3"))):
    vid = os.path.basename(p).split(".")[0]
    d = json.load(open(p))
    cues = []
    for e in d["events"]:
        segs = e.get("segs")
        if not segs:
            continue
        s = "".join(x.get("utf8", "") for x in segs)
        s = s.replace("\n", " ").strip()
        if not s:
            continue
        cues.append((e["tStartMs"] / 1000.0, s))
    out = []
    buf, t0 = [], None
    for t, s in cues:
        if t0 is None:
            t0 = t
        buf.append(s)
        if t - t0 >= 20:
            out.append(f"[{ts(t0)}] {' '.join(buf)}")
            buf, t0 = [], None
    if buf:
        out.append(f"[{ts(t0)}] {' '.join(buf)}")
    op = os.path.join(D, "txt", f"{vid}.txt")
    os.makedirs(os.path.dirname(op), exist_ok=True)
    open(op, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(vid, len(cues), "cues ->", op)
