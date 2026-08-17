import sys
sys.path.insert(0, "/home/userdelvin/autonomous/capabilities/edge_validator")

from logic import load_jsonl, assess

LEDGER = "/home/userdelvin/Delvin-agent/scripts/personal_ledger.jsonl"

records = load_jsonl(LEDGER)
records = [r for r in records if r.get("type") == "A" and r.get("label") in ("win", "loss")]

result = assess(records)

with open("verdict.txt", "w") as f:
    f.write(str(result["verdict_honest"]))

with open("overstated.txt", "w") as f:
    f.write(str(result["naive_overstated_confidence"]))

print(result)
