"""
Accuracy test for the AI-visibility analyser.

Asserts per-answer mention/citation detection against the planted ground truth
in fixture/ai_truth.json, and reports precision/recall separately — because the
failure that matters here is a FALSE POSITIVE. Over-reporting visibility tells a
client they're fine when they are not.
"""
import json, sys
sys.path.insert(0, ".")
from engine.aivis import ClientProfile, build_panel, run_replay
from engine.aivis.analyze import brand_patterns, detect_mention

corpus = json.load(open("fixture/ai_corpus.json"))
gt = json.load(open("fixture/ai_truth.json"))
profile = ClientProfile(**gt["profile"])
truth = gt["truth"]

queries = build_panel(profile)
out = run_replay(profile, corpus, queries=queries, repeats=1)

tp = fp = tn = fn = 0
ctp = cfp = ctn = cfn = 0
misses = []
for r in out["results"]:
    exp = truth[r["platform"]][r["query_id"]]
    got_m, exp_m = bool(r["mentioned"]), bool(exp["mentioned"])
    got_c, exp_c = bool(r["cited"]), bool(exp["cited"])
    if   got_m and exp_m: tp += 1
    elif got_m and not exp_m: fp += 1; misses.append(("MENTION-FP", r, exp))
    elif not got_m and exp_m: fn += 1; misses.append(("MENTION-FN", r, exp))
    else: tn += 1
    if   got_c and exp_c: ctp += 1
    elif got_c and not exp_c: cfp += 1; misses.append(("CITE-FP", r, exp))
    elif not got_c and exp_c: cfn += 1; misses.append(("CITE-FN", r, exp))
    else: ctn += 1

def pr(tp, fp, fn):
    p = tp/(tp+fp) if tp+fp else 1.0
    r = tp/(tp+fn) if tp+fn else 1.0
    return p, r

mp, mr = pr(tp, fp, fn); cp, cr_ = pr(ctp, cfp, cfn)
n = len(out["results"])
print(f"\n{n} answers analyzed\n")
print(f"  MENTION   precision {mp*100:5.1f}%   recall {mr*100:5.1f}%   "
      f"(tp={tp} fp={fp} fn={fn} tn={tn})")
print(f"  CITATION  precision {cp*100:5.1f}%   recall {cr_*100:5.1f}%   "
      f"(tp={ctp} fp={cfp} fn={cfn} tn={ctn})")

if misses:
    print(f"\n  {len(misses)} mismatches:")
    for kind, r, exp in misses[:15]:
        print(f"    {kind:11} {r['platform']:12} {exp['note']}")
else:
    print("\n  No mismatches — every trap case correctly rejected.")

agg = out["aggregate"]
print(f"\n  headline: {out['headline']}")
print(f"\n  top cited domains:")
for s in agg["share_of_voice"][:6]:
    print(f"    {'*' if s['is_client'] else ' '} {s['domain']:32} "
          f"{s['citations']:3} citations  {s['share']:5.1f}%")
sys.exit(0 if not misses else 1)
