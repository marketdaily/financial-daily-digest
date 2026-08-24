"""Demo:用 6 期全未開信的 send_history 呼叫 churn_sniper 的 score_contact()/draft_winback(),
把產生的中文挽回信草稿寫進目前工作目錄的 result.txt。

不重新設計判斷邏輯,純粹組出 score_contact() 期待的 history 格式後呼叫既有連接器。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from churn_sniper import score_contact, draft_winback

now = datetime.now(timezone.utc)

send_history = []
for i in range(6):
    delivered_at = (now - timedelta(days=i)).isoformat()
    send_history.append({
        "message_id": f"demo-msg-{i}",
        "requested_at": delivered_at,
        "delivered_at": delivered_at,
        "blocked": False,
        "opened": False,
        "opened_at": None,
        "subject": "MarketDaily 財經日報",
    })

score = score_contact(send_history)
draft = draft_winback("demo@example.com", score)

result_path = Path.cwd() / "result.txt"
result_path.write_text(draft["draft_body_zh"])

print(f"score = {score}")
print(f"→ 已寫入 {result_path}")
