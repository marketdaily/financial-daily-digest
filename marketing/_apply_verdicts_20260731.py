import json, sys, io

PATH = "/home/userdelvin/Delvin-agent/marketing/ad_creative_drafts.json"
VERDICTS_PATH = "/home/userdelvin/Delvin-agent/marketing/_verdicts_20260731.json"

verdicts = json.load(open(VERDICTS_PATH, encoding="utf-8"))
data = json.load(open(PATH, encoding="utf-8"))
drafts = data["drafts"]
by_id = {d["id"]: d for d in drafts}

target_ids = [v["id"] for v in verdicts]
missing = [i for i in target_ids if i not in by_id]
if missing:
    sys.exit("missing ids: %s" % missing)

before_len = len(drafts)

for v in verdicts:
    d = by_id[v["id"]]
    act = v["action"]
    if act == "approve":
        if "fixed_caption_zh" in v:
            d["caption_zh"] = v["fixed_caption_zh"]
        if "fixed_caption_en" in v:
            d["caption_en"] = v["fixed_caption_en"]
        d["status"] = "approved"
        if "verifier_edits" in v:
            d["verifier_edits"] = v["verifier_edits"]
    elif act == "reject":
        d["status"] = "rejected"
        d["reject_reason"] = v["reject_reason"]
        if "verifier_edits" in v:
            d["verifier_edits"] = v["verifier_edits"]
    else:
        sys.exit("unknown action %s" % act)

assert len(data["drafts"]) == before_len

with io.open(PATH, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")

# verify by re-reading
data2 = json.load(open(PATH, encoding="utf-8"))
d2 = {d["id"]: d for d in data2["drafts"]}
pending = [d["id"] for d in data2["drafts"] if d.get("status") == "pending_review"]
approved = [i for i in target_ids if d2[i]["status"] == "approved"]
rejected = [i for i in target_ids if d2[i]["status"] == "rejected"]
print("total drafts:", len(data2["drafts"]))
print("pending_review remaining:", pending)
print("approved(%d): %s" % (len(approved), approved))
print("rejected(%d): %s" % (len(rejected), rejected))
for v in verdicts:
    i = v["id"]
    ok_zh = ("fixed_caption_zh" not in v) or d2[i]["caption_zh"] == v["fixed_caption_zh"]
    ok_en = ("fixed_caption_en" not in v) or d2[i]["caption_en"] == v["fixed_caption_en"]
    ok_re = (v["action"] != "reject") or d2[i].get("reject_reason") == v["reject_reason"]
    ok_ve = ("verifier_edits" not in v) or d2[i].get("verifier_edits") == v["verifier_edits"]
    print(i, d2[i]["status"], "caption_zh_ok=%s caption_en_ok=%s reason_ok=%s edits_ok=%s" % (ok_zh, ok_en, ok_re, ok_ve))
