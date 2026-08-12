"""備援防雙發閘 ①(daily_digest.yml 起跑閘)的契約與語義迴歸。

事故形狀(2026-08-12 查獲,沒有造成雙寄但每天白燒一輪雲端生成):
  wrangler 憑證死掉 → `wrangler pages deploy` 全斷 → 公版存檔停止上線 → watchdog 每班判
  「存檔缺席」派雲端備援。備援的起跑閘本該立刻退場,結果**跑滿 51m47s**才在寄出前的第③層
  退場。查下去發現起跑閘壞在兩處,兩處都是「同一個判準被寫了第二份」的後果:

  D1 死碼:`curl -s`(不跟隨重導)比對 200。但 `digest_<date>.html` 線上是 **308** 導到
          無副檔名版 ⇒ `= "200"` 永遠不成立,這道閘自上線起從未射出過。
          權威判準 `_archive_online` 用 urlopen(預設跟隨)所以是對的 —— 兩份實作,一份是啞的。
  D2 訊號較弱:只查網站。權威判準是「網站 OR origin」(2026-08-02 雙寄根因補的快訊號),
          而 08-12 那天正是靠 origin 那半才認出 winrig 已交付。

修法不是把 bash 那份補好(那是第三次重寫同一個判準),是讓閘門**呼叫生產判準本人**。
本測試守的就是「不准再長出第二份」以及那條讓 D1 成立的語義。

零外部網路:308 語義用本機 http server 驗(main.ARCHIVE_BASE 指過去);契約部分純文字解析。
跑法:python3 scripts/test_failover_gate_contract.py
"""
import http.server
import os
import re
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import main  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW = os.path.join(REPO, ".github", "workflows", "daily_digest.yml")
FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got={got!r} want={want!r}")
        print(f"  ✗ {name}: got={got!r} want={want!r}")
    else:
        print(f"  ✓ {name}")


def ok(name, cond, why=""):
    check(name if not why else f"{name}({why})", bool(cond), True)


# ── 段一:308 語義(D1 的迴歸) ────────────────────────────────────────────────
# 線上真實形狀:/output/digest_<d>.html → 308 → /output/digest_<d> → 200。
# 「已交付」必須在跟隨重導之後判斷;不跟隨的實作會看到 308 而誤判成「未交付」。
DELIVERED_DATE = "2026-08-12"
MISSING_DATE = "1999-01-01"
DIRECT_DATE = "2026-08-11"


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == f"/output/digest_{DELIVERED_DATE}.html":
            self.send_response(308)
            self.send_header("Location", f"/output/digest_{DELIVERED_DATE}")
            self.end_headers()
        elif self.path == f"/output/digest_{DELIVERED_DATE}":
            self._body(200)
        elif self.path == f"/output/digest_{DIRECT_DATE}.html":
            self._body(200)
        else:
            self.send_response(404)
            self.end_headers()

    def _body(self, code):
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html>digest</html>")

    def log_message(self, *a):
        pass


def _naive_probe(url):
    """複刻舊版 bash 閘的行為(`curl -s` 不跟隨重導)——只為了證明兩份實作真的會分歧。"""
    import urllib.request

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(url, timeout=5) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_address[1]}"
saved_base = main.ARCHIVE_BASE
main.ARCHIVE_BASE = base
try:
    print("\n── 308 語義(存檔活著時線上回 308,跟隨後才是 200) ──")
    check("308→200 的存檔 → 已交付(True)",
          main._archive_online("tw", DELIVERED_DATE), True)
    check("直接 200 的存檔 → 已交付(True)",
          main._archive_online("tw", DIRECT_DATE), True)
    check("404 → 未交付(False,查不到一律照寄)",
          main._archive_online("tw", MISSING_DATE), False)

    # 這條是 D1 的核心證據:舊寫法在「存檔明明活著」時看到的是 308,不是 200。
    naive = _naive_probe(f"{base}/output/digest_{DELIVERED_DATE}.html")
    check("舊寫法(不跟隨重導)在存檔活著時看到 308 而非 200", naive, 308)
    ok("兩份實作確實分歧 ⇒ 不得再寫第二份",
       (naive == 200) != main._archive_online("tw", DELIVERED_DATE))
finally:
    main.ARCHIVE_BASE = saved_base
    srv.shutdown()

# ── 段二:workflow 契約(不准再長出第二份判準) ──────────────────────────────
print("\n── daily_digest.yml 起跑閘契約 ──")
raw = open(WORKFLOW, encoding="utf-8").read()

step_re = re.compile(r"^      - name: (.+)$", re.M)
names = [m.group(1).strip() for m in step_re.finditer(raw)]
spans = [m.start() for m in step_re.finditer(raw)] + [len(raw)]


def step_body(title):
    for i, n in enumerate(names):
        if n == title:
            return raw[spans[i]:spans[i + 1]]
    return None


GUARD = "Failover double-send guard"
body = step_body(GUARD)
ok(f"步驟「{GUARD}」存在", body is not None)

if body:
    ok("閘門呼叫生產判準 main._archive_delivered",
       "main._archive_delivered" in body)
    # D1/D2 的復發形狀:在閘門裡自己拿 curl 探存檔。
    ok("閘門沒有自己 curl 探存檔(重寫第二份判準)",
       not re.search(r"curl[^\n]*digest_", body) and "http_code" not in body)
    # fail-open:判不出來一律照寄,死線是絕不缺信。
    ok("fail-open:閘門不會自己 exit 1 把整輪卡掉",
       not re.search(r"^\s*exit 1\s*$", body, re.M))
    ok("判不出來時有 ::warning:: 讓「閘門啞了」看得見",
       "::warning::" in body)

    # 位置:必須在裝依賴之後(import main 才成立)、生成之前(省下的就是那 ~50 分鐘)。
    idx = {n: i for i, n in enumerate(names)}
    ok("閘門在「Install dependencies」之後(import main 才成立)",
       idx.get(GUARD, -1) > idx.get("Install dependencies", 10 ** 6))
    ok("閘門在「Run daily digest」之前(才省得到生成成本)",
       idx.get(GUARD, 10 ** 6) < idx.get("Run daily digest", -1))

# 生成步驟仍必須受 SKIP_SEND 節制,否則閘門判「已交付」也照樣寄。
run_body = step_body("Run daily digest") or ""
ok("「Run daily digest」仍受 SKIP_SEND 節制", "env.SKIP_SEND != '1'" in run_body)

print()
if FAILS:
    print(f"FAIL {len(FAILS)} 項:")
    for f in FAILS:
        print(f"  - {f}")
    sys.exit(1)
print("PASS 備援防雙發閘① 契約與 308 語義全過")
