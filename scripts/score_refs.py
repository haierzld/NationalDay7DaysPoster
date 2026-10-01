# -*- coding: utf-8 -*-
"""给已采集的参考图做一次打分体检，看分数分布与建议合格线。

    python scripts/score_refs.py            # 全部主体
    python scripts/score_refs.py 上海       # 只看一个

分数构成（见 generate_browser._score_item）：
  题材贴合 0~4.2｜分辨率 0~3.8｜竖构图 -1.5~+1.2｜来源可信度 -1.2~+1.5
"""
import contextlib
import io
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from generate_browser import _auto_refs, _score_item, _keywords  # noqa: E402

BINS = [("<0", lambda s: s < 0), ("0~2", lambda s: 0 <= s < 2), ("2~4", lambda s: 2 <= s < 4),
        ("4~6", lambda s: 4 <= s < 6), ("6~8", lambda s: 6 <= s < 8), ("≥8", lambda s: s >= 8)]


def pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = min(len(s) - 1, max(0, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def audit(subject: str) -> dict:
    idx_path = ROOT / "assets" / subject / "_refs.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    subj_path = ROOT / "config" / "subjects" / f"{subject}.json"
    events_all = []
    days = []
    if subj_path.exists():
        subj = json.loads(subj_path.read_text(encoding="utf-8"))
        days = subj.get("days", [])
        events_all = [ev for d in days for ev in d.get("events", [])]

    all_scores, per_topic_best, missing = [], {}, []
    for slug, meta in idx.items():
        best = None
        for it in (meta or {}).get("items", []):
            f = it.get("file") or ""
            p = (ROOT / f) if not Path(f).is_absolute() else Path(f)
            if not p.exists():
                missing.append(f)
                continue
            if events_all:
                sc = max(_score_item(it, _keywords(ev)) for ev in events_all)
            else:
                sc = _score_item(it, [meta.get("query") or ""])
            all_scores.append(sc)
            best = sc if best is None else max(best, sc)
        if best is not None:
            per_topic_best[slug] = best

    # 当前挑选逻辑实际会选中的图（按天跑一遍，静默掉它的打印）
    picked = []
    for d in days:
        with contextlib.redirect_stdout(io.StringIO()):
            refs = _auto_refs(subject, d.get("events", []))
        for r in refs:
            for slug, meta in idx.items():
                for it in (meta or {}).get("items", []):
                    if (ROOT / it.get("file", "")).resolve() == Path(r).resolve():
                        picked.append(max(_score_item(it, _keywords(ev))
                                          for ev in d.get("events", [])))
                        break

    return {"subject": subject, "topics": len(idx), "n": len(all_scores),
            "missing": missing, "scores": all_scores, "topic_best": per_topic_best,
            "picked": picked}


def main():
    subjects = sys.argv[1:]
    if not subjects:
        subjects = [p.parent.name for p in (ROOT / "assets").glob("*/_refs.json")]

    for subj in subjects:
        if not (ROOT / "assets" / subj / "_refs.json").exists():
            print(f"\n【{subj}】没有 _refs.json，跳过")
            continue
        a = audit(subj)
        s = a["scores"]
        print(f"\n【{subj}】题材 {a['topics']} 个，可用图 {a['n']} 张"
              + (f"，缺文件 {len(a['missing'])} 个" if a["missing"] else ""))
        if not s:
            continue
        dist = "  ".join(f"{label}:{sum(1 for x in s if f(x))}" for label, f in BINS)
        print(f"  分布  {dist}")
        print(f"  最低 {min(s):.1f}   P25 {pct(s,25):.1f}   中位 {pct(s,50):.1f}   "
              f"P75 {pct(s,75):.1f}   最高 {max(s):.1f}   均值 {statistics.mean(s):.1f}")
        weak = sorted(a["topic_best"].items(), key=lambda kv: kv[1])[:5]
        print("  最弱的题材（该题材最高分）：" + "、".join(f"{k} {v:.1f}" for k, v in weak))
        if a["picked"]:
            p = a["picked"]
            print(f"  实际会被选中 {len(p)} 张：中位 {pct(p,50):.1f}，最低 {min(p):.1f}，"
                  f"低于 4 分的 {sum(1 for x in p if x < 4)} 张")


if __name__ == "__main__":
    main()
