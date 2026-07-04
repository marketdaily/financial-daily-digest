"""雲端 Worker 回寫:把本地 commit 的 agent_team/ 變更 POST 到寫入代理。

雲端 CCR 環境封鎖 git push,改走這條 HTTP 路 —— 由 agent-relay Worker 代為
commit 到 GitHub 並寄通知信。純 stdlib,雲端環境可直接跑。

用法:
  python3 agent_team/relay_push.py [<任務檔路徑,用來建通知信>]
需環境變數:RELAY_URL、RELAY_SECRET
"""
import sys
import os
import json
import urllib.request
import urllib.error

DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(DIR)


def git(*args):
    import subprocess
    return subprocess.run(["git", "-C", ROOT, *args],
                          capture_output=True, text=True).stdout.strip()


def changed_files():
    """origin/main..HEAD 之間 agent_team/ 底下的檔案變更。"""
    out = git("diff", "--name-status", "origin/main", "HEAD", "--", "agent_team/")
    files = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if status == "D":
            files.append({"path": path, "delete": True})
        else:
            full = os.path.join(ROOT, path)
            if os.path.exists(full):
                files.append({"path": path,
                              "content": open(full, encoding="utf-8").read()})
    return files


def main():
    relay_url = os.getenv("RELAY_URL")
    relay_secret = os.getenv("RELAY_SECRET")
    if not relay_url or not relay_secret:
        print("❌ 缺 RELAY_URL / RELAY_SECRET 環境變數")
        sys.exit(1)

    files = changed_files()
    if not files:
        print("沒有 agent_team/ 變更可回寫")
        return
    msgs = git("log", "origin/main..HEAD", "--format=%s", "--reverse").splitlines()
    message = msgs[-1] if msgs else "🤖 [agent-team] 雲端 Worker 更新"

    payload = {"message": message, "files": files}

    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        try:
            sys.path.insert(0, DIR)
            import notify
            subject, html = notify.build_instant(sys.argv[1])
            payload["email"] = {"subject": subject, "html": html}
        except Exception as e:
            print(f"⚠️ 建通知信失敗,略過寄信:{e}")

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(relay_url, data=data, method="POST",
        headers={"X-Relay-Secret": relay_secret, "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (compatible; MarketDaily-Agent/1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.load(r)
        print(f"✅ 已透過代理回寫:commit={str(resp.get('commit',''))[:8]} "
              f"emailed={resp.get('emailed')} files={len(files)}")
    except urllib.error.HTTPError as e:
        print(f"❌ 代理回寫失敗 {e.code}:{e.read().decode('utf-8','ignore')}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 代理回寫失敗:{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
