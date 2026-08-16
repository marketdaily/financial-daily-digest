#!/usr/bin/env bash
# _cron_export_cf_token 自測(2026-08-16):wrangler 的第三種憑證來源。
# 為什麼要有:08-11 wrangler OAuth 設定檔消失 → 42 個呼叫端同時啞,而唯一復原動作
# 需要瀏覽器 ⇒ 背景 session 修不了。這條無頭路把「只有 Delvin 能修」降級成「貼一行進 .env」。
# 斷言重點是**優先序**與**不誤傷**:既有環境變數必須贏(否則 CI/手動覆寫被 .env 蓋掉),
# 沒設定時必須完全靜默(否則所有 source 這個庫的 cron 會在 set -u 下炸掉)。
set -u
LIB="${LIB:-$HOME/Delvin-agent/scripts/lib_cron_runner.sh}"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
chk()  { [ "$2" = "$3" ] && ok "$1" || bad "$1 (期望 '$3' 得到 '$2')"; }

WD=$(mktemp -d); trap 'rm -rf "$WD"' EXIT

# 在乾淨子 shell 裡 source 一次庫,回印目標變數(CRON_LIB_REPO 指向假 repo)
run() {   # run <fake_repo> <preset_env...> ; 印出 "TOKEN|ACCOUNT"
  local repo="$1"; shift
  env -i HOME="$HOME" PATH="$PATH" CRON_LIB_REPO="$repo" "$@" \
    bash -c 'source "$0" >/dev/null 2>&1; printf "%s|%s\n" "${CLOUDFLARE_API_TOKEN:-}" "${CLOUDFLARE_ACCOUNT_ID:-}"' "$LIB"
}
# ⚠️ 值比對分不出「沒 export」與「export 成空字串」——後者會讓 wrangler 報「認證失敗」
#   而不是「沒憑證」,把真相蓋掉(三態壓成二態)。這支用 ${VAR+SET} 只看**存在性**。
#   突變測試 M3(拿掉空值守衛)在補這支之前是 SURVIVED 的。
present() {   # present <fake_repo> ; 印出 "SET|SET" / "UNSET|UNSET"
  local repo="$1"; shift
  env -i HOME="$HOME" PATH="$PATH" CRON_LIB_REPO="$repo" "$@" \
    bash -c 'source "$0" >/dev/null 2>&1; printf "%s|%s\n" "${CLOUDFLARE_API_TOKEN+SET}${CLOUDFLARE_API_TOKEN-UNSET}" "${CLOUDFLARE_ACCOUNT_ID+SET}${CLOUDFLARE_ACCOUNT_ID-UNSET}"' "$LIB"
}

echo "== _cron_export_cf_token =="

# ① .env 有 token → 進環境
mkdir -p "$WD/a"
printf 'FOO=1\nCLOUDFLARE_API_TOKEN=tok_alpha\nCLOUDFLARE_ACCOUNT_ID=acc_alpha\n' > "$WD/a/.env"
chk ".env 的 token 被 export" "$(run "$WD/a")" "tok_alpha|acc_alpha"

# ② 既有環境變數優先(CI / 手動覆寫不被 .env 蓋掉)
chk "既有環境變數贏過 .env" \
  "$(run "$WD/a" CLOUDFLARE_API_TOKEN=tok_env)" "tok_env|acc_alpha"

# ③ 引號與 CR 被剝掉(.env 常見寫法 / Windows 換行)
mkdir -p "$WD/b"
printf 'CLOUDFLARE_API_TOKEN="tok_quoted"\r\n' > "$WD/b/.env"
chk "雙引號+CR 被剝乾淨" "$(run "$WD/b")" "tok_quoted|"

# ④ .env 沒有這個 key → 完全不動作(維持 OAuth 路徑,不是設成空字串)
mkdir -p "$WD/c"
printf 'OTHER=1\n' > "$WD/c/.env"
chk "沒有 key 時不 export" "$(run "$WD/c")" "|"
chk "沒有 key 時變數維持 unset(不是空字串)" "$(present "$WD/c")" "UNSET|UNSET"

# ⑤ .env 根本不存在 → 靜默,且 source 仍成功(set -u 下不可炸)
mkdir -p "$WD/d"
out=$(run "$WD/d"); rc=$?
chk ".env 不存在也不炸" "$out" "|"
chk ".env 不存在時 source 成功" "$rc" "0"

# ⑥ 值為空 → 不 export(避免 wrangler 拿到空 token 而報「認證失敗」蓋掉「沒設定」的真相)
mkdir -p "$WD/e"
printf 'CLOUDFLARE_API_TOKEN=\n' > "$WD/e/.env"
chk "空值不 export" "$(run "$WD/e")" "|"
chk "空值時變數維持 unset(不是 export 空字串)" "$(present "$WD/e")" "UNSET|UNSET"

# ⑦ 值含 '=' (base64 尾巴)不可被 cut 截斷
mkdir -p "$WD/f"
printf 'CLOUDFLARE_API_TOKEN=abc=def==\n' > "$WD/f/.env"
chk "值含 = 不被截斷" "$(run "$WD/f")" "abc=def==|"

# ⑧ 註解掉的 key 不算數(#CLOUDFLARE_API_TOKEN=...)
mkdir -p "$WD/g"
printf '#CLOUDFLARE_API_TOKEN=tok_commented\n' > "$WD/g/.env"
chk "被註解的 key 不 export" "$(run "$WD/g")" "|"

echo "── $PASS✓ $FAIL✗"
[ "$FAIL" -eq 0 ]
