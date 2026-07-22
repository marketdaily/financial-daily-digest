#!/bin/bash
# analyst.marketdaily.ai 整合驗收(可重跑):cb_server 的 /cb 前綴剝除、舊網域 301、deskauth SSO。
# 全部打本機 8911、用 Host header 模擬經 cloudflared tunnel 的請求,不依賴外網/DNS。
# 跑:bash verify_analyst_entry.sh    exit 0 = 全過
set -u
BASE=http://127.0.0.1:8911
PASS=0; FAIL=0
ck(){ if [ "$2" = "$3" ]; then echo "[PASS] $1"; PASS=$((PASS+1)); else echo "[FAIL] $1 (want=$2 got=$3)"; FAIL=$((FAIL+1)); fi; }

if ! curl -s -m 5 -o /dev/null "$BASE/"; then
  echo "cb_server(8911)沒在跑,先啟動再驗"; exit 2
fi

# 兩顆 token 都從 ~/Delvin-agent/.env 的 CB_DESK_PASSWORD 推導(與兩個伺服器同一來源)
TOKS=$(python3 - <<'EOF'
import hashlib, hmac, os
pw = ""
try:
    for l in open(os.path.expanduser("~/Delvin-agent/.env")):
        if l.startswith("CB_DESK_PASSWORD=") and l.split("=", 1)[1].strip():
            pw = l.split("=", 1)[1].strip()
            break
except OSError:
    pass
if pw:
    print(hmac.new(pw.encode(), b"cb-desk-dash-v1", hashlib.sha256).hexdigest())
    print(hmac.new(pw.encode(), b"cb-desk-auth-v1", hashlib.sha256).hexdigest())
EOF
)
DESK_TOK=$(echo "$TOKS" | sed -n 1p)
CB_TOK=$(echo "$TOKS" | sed -n 2p)
[ -n "$DESK_TOK" ] || { echo "找不到 CB_DESK_PASSWORD,無法驗 SSO"; exit 2; }

# ── ① /cb 前綴剝除 ──────────────────────────────────────────────
code=$(curl -s -o /tmp/vfy_cb.html -w '%{http_code}' -m 10 -H "Cookie: deskauth=$DESK_TOK" "$BASE/cb/")
ck "/cb/ 帶 deskauth cookie → 200(SSO)" 200 "$code"
grep -q '台股 CB 拆解分析台' /tmp/vfy_cb.html; ck "/cb/ 剝前綴後回 cb_server index" 0 $?
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Cookie: deskauth=$DESK_TOK" "$BASE/cb")
ck "/cb(無斜線)也剝 → 200" 200 "$code"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Cookie: cbauth=$CB_TOK" "$BASE/cb/")
ck "既有 cbauth cookie 照舊可用(向後相容)" 200 "$code"

# ── ② 未登入行為 ────────────────────────────────────────────────
loc=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 "$BASE/cb/")
ck "/cb/ 未登入 → 302 到 /(desk 登入頁)" "302 $BASE/" "$loc"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$BASE/")
ck "根路徑未登入(本機直連)照舊 401 自家登入頁" 401 "$code"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$BASE/cb/api/brief")
ck "/cb/api/* 未登入 → 401 片段(fetch 用,不 302)" 401 "$code"

# ── ③ /cb 邊界(不可誤剝)─────────────────────────────────────
code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Cookie: deskauth=$DESK_TOK" "$BASE/cbx")
ck "/cbx 不剝前綴 → 404" 404 "$code"
# //cb:Python 3.14 http.server 會把開頭多重斜線摺疊成一個(//cb → /cb,實測驗證),
# handler 看不到 //cb,行為等同 /cb(unauth → 302);urlparse 的 netloc 誤判打不進來。
# 經 tunnel 時 //cb 不匹配 ^/cb($|/) 規則,根本進不了 cb_server(去 desk 8913 → 404)。
code=$(curl -s --path-as-is -o /dev/null -w '%{http_code}' -m 10 "$BASE//cb")
ck "//cb 摺疊成 /cb,未登入 → 302(同 /cb)" 302 "$code"
code=$(curl -s --path-as-is -o /dev/null -w '%{http_code}' -m 10 -H "Cookie: deskauth=$DESK_TOK" "$BASE/cb../cb_database.json")
ck "/cb../ 不剝、realpath 擋穿越 → 404" 404 "$code"

# ── ④ 舊網域 301(Host=cb.marketdaily.ai)────────────────────────
loc=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 -H "Host: cb.marketdaily.ai" "$BASE/")
ck "Host=cb.marketdaily.ai / → 301 analyst/cb/" \
   "301 https://analyst.marketdaily.ai/cb/" "$loc"
loc=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' -m 10 -H "Host: cb.marketdaily.ai" "$BASE/api/analyze?code=5289")
ck "301 保留 path+query" "301 https://analyst.marketdaily.ai/cb/api/analyze?code=5289" "$loc"
loc=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -H "Host: analyst.marketdaily.ai" -H "Cookie: deskauth=$DESK_TOK" "$BASE/cb/")
ck "Host=analyst 不 301(無迴圈)" 200 "$loc"

# ── ⑤ 登入 Set-Cookie 安全屬性(審計低風險修正:cbauth 補 Secure,與 deskauth 對齊)──
PW=$(python3 -c "
import os
for l in open(os.path.expanduser('~/Delvin-agent/.env')):
    if l.startswith('CB_DESK_PASSWORD=') and l.split('=',1)[1].strip():
        print(l.split('=',1)[1].strip()); break")
setck=$(curl -s -o /dev/null -D - -m 10 --data-urlencode "password=$PW" "$BASE/login" | grep -i '^Set-Cookie: cbauth=')
echo "$setck" | grep -q 'HttpOnly' && echo "$setck" | grep -q 'SameSite=Lax' \
  && echo "$setck" | grep -q 'Secure' && echo "$setck" | grep -q 'Path=/'
ck "/login cbauth 帶 HttpOnly+SameSite=Lax+Secure+Path=/" 0 $?

# ── ⑥ index 深連結/前綴 JS ──────────────────────────────────────
grep -q "p.get('q')||p.get('code')" /tmp/vfy_cb.html; ck "index 支援 ?code= 深連結" 0 $?
grep -q "API_BASE" /tmp/vfy_cb.html; ck "index API 呼叫帶 /cb 前綴邏輯" 0 $?
grep -q 'class="topnav"' /tmp/vfy_cb.html; ck "index 有統一導覽列" 0 $?

echo
echo "PASS=$PASS FAIL=$FAIL"
[ $FAIL -eq 0 ]
