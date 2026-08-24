import sys
import json

sys.path.insert(0, "/home/userdelvin/Delvin-agent")
import intel.us_8k_events as u8k

noise_result = u8k.classify_items(u8k.parse_items_desc("items 2.02 and 9.01"))
red_result = u8k.classify_items(u8k.parse_items_desc("item 4.01"))

with open("out.json", "w") as f:
    json.dump({
        "noise_result": noise_result,
        "red_level": red_result[0][1] if red_result else None,
    }, f)
