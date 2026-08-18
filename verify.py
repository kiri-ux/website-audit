import json
gt = json.load(open("fixture/GROUND_TRUTH.json"))
F  = json.load(open("out/findings.json"))["findings"]
passes=fails=0; rows=[]
for cid, exp in sorted(gt.items()):
    f = F.get(cid)
    if not f:
        rows.append(("MISS", cid, "checker not registered", exp["note"])); fails+=1; continue
    ok = f["status"] == exp["expect"]
    detail = f"status={f['status']}"
    v = f.get("value") or {}
    if ok and "count" in exp:
        got = v.get("count", v.get("pages_affected"))
        ok = got == exp["count"]; detail += f" count={got} (expected {exp['count']})"
    if ok and "min_count" in exp:
        got = v.get("count", 0)
        ok = got >= exp["min_count"]; detail += f" count={got} (expected >={exp['min_count']})"
    if ok and "pages_affected" in exp:
        got = v.get("pages_affected")
        ok = got == exp["pages_affected"]; detail += f" pages={got} (expected {exp['pages_affected']})"
    if ok and "blocked" in exp:
        got = v.get("blocked", [])
        ok = set(got) == set(exp["blocked"]); detail += f" blocked={got}"
    rows.append(("PASS" if ok else "FAIL", cid, detail, exp["note"]))
    passes += ok; fails += (not ok)
print(f"{'':4} {'ID':<11}{'DETAIL':<52}GROUND TRUTH")
print("-"*128)
for r in rows: print(f"{r[0]:4} {r[1]:<11}{r[2][:50]:<52}{r[3]}")
print("-"*128)
print(f"\n  {passes}/{len(gt)} ground-truth assertions detected correctly  ({100*passes//len(gt)}%)")
if fails: print(f"  {fails} mismatches — see FAIL/MISS rows above")
