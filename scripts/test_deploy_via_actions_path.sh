#!/usr/bin/env bash
# deploy_docs_via_actions.sh 在 **cron 的 PATH** 下必須找得到 gh(2026-08-16)。
#
# 為什麼要有這支:cron 的 PATH 不含 ~/.local/bin,而 gh 就裝在那裡 ⇒ 本機 wrangler 那條腿
# 死掉、退到備援腿的那一刻,備援腿一律停在「gh 未安裝」exit 5,連 dispatch 都沒試過。
# 這種壞法最陰險:平常沒人跑備援腿,所以它壞著也沒有症狀;等到真的需要它,才第一次
# 發現它也是壞的,而那時本機腿已經死了。⭐ 守衛/備援的執行環境 ≠ 我的互動 shell。
set -u
S="${S:-$HOME/Delvin-agent/scripts/deploy_docs_via_actions.sh}"
CRON_PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad() { FAIL=$((FAIL+1)); echo "  ✗ $1"; }

WD=$(mktemp -d); trap 'rm -rf "$WD"' EXIT

run_cron() {   # 用 cron 的 PATH 跑,回傳輸出(不看 exit code,只看走到哪一步)
  env -i HOME="$HOME" PATH="$CRON_PATH" DEPLOY_ALLOW_DRIFT=1 GH_BIN="${1:-gh}" \
    timeout 90 bash "$S" "自測:cron PATH 探測" 2>&1
}

echo "== deploy_docs_via_actions 的 gh 解析 =="

out=$(run_cron)
# ⭐ 正向斷言:必須**走到 dispatch 那一步**。只斷言「沒有出現 gh 未安裝」是不夠的——
#    腳本在更早的地方 exit(例如 cd 失敗)同樣不會印那句話,那是恆真的空斷言。
case "$out" in
  *"dispatch pages_deploy.yml"*) ok "cron PATH 下有走到 dispatch(gh 已解析出絕對路徑)" ;;
  *) bad "cron PATH 下沒走到 dispatch;輸出:$(printf '%s' "$out" | tail -2 | tr '\n' ' ')" ;;
esac
case "$out" in
  *"gh 未安裝"*) bad "cron PATH 下仍回報『gh 未安裝』" ;;
  *) ok "不再誤報 gh 未安裝" ;;
esac

# 反向對照:真的沒有 gh 時**必須**回報找不到並 exit 5——不可為了通過上面那條而變成 fail-open
mkdir -p "$WD/empty"
# ⚠️ PATH 不能清空:清掉 /usr/bin 連 timeout/git 都不見了,腳本會以 127 死在別的地方,
#    這條斷言就變成「測到別的東西」。留下 /usr/bin:/bin(gh 不在那裡)+ 空的 HOME
#    (讓 ~/.local/bin 那個候選也落空)才是乾淨的「只有 gh 不見」。
out2=$(env -i HOME="$WD/empty" PATH=/usr/bin:/bin MD_REPO="$HOME/Delvin-agent" DEPLOY_ALLOW_DRIFT=1 \
        timeout 60 bash "$S" "自測:無 gh" 2>&1); rc2=$?
case "$out2" in
  *"gh 未安裝"*) ok "反向:真的沒有 gh 時誠實回報" ;;
  *) bad "反向:沒有 gh 卻沒回報(fail-open);輸出:$(printf '%s' "$out2" | tail -2 | tr '\n' ' ')" ;;
esac
[ "$rc2" -eq 5 ] && ok "反向:exit code 仍是 5(前置條件不足)" || bad "反向:exit code $rc2 ≠ 5"

echo "── $PASS✓ $FAIL✗"
[ "$FAIL" -eq 0 ]
