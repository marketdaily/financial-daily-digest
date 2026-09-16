#!/usr/bin/env bash
# 憑證分盒(2026-09-16)。腦與手分開,手上只拿這次任務需要的那幾把鑰匙。
#
# 問題:.env 有約 115 個 secret(LinkedIn 密碼、10 個目錄站帳密、皇海 Seednet 網域帳密、
# 郵件密碼、PyPI token、永豐下單金鑰…)。任何 source lib_cron_runner.sh 的 cron,
# 以及它 spawn 的每一個 `claude -p` 子行程,**整份繼承**。一個只負責讀 LINE 截圖產內部
# 摘要的 agent,手上同時握著能對全體訂閱者群發信、能改 DNS、能下單的鑰匙。
#
# 來源:Anthropic「Ship your first Managed Agent」(Isabella He, Code w/ Claude London)
# 07:35「The brain left the box」——agent loop 與工具執行拆開,憑證放 vault,
# agent 拿不到檔案系統裡的憑證。我們自己的版本:08-16 已經查到
# 「憑證有兩半:收斂了『自己讀』,沒收斂『交給子行程』」,這支補的就是後面那半。
#
# 為什麼用剝除(env -u)而不是 env -i:env -i 會連 PATH/HOME/LANG/NVM 一起清掉,
# 生產上會炸一票東西。這裡只剝 .env 裡出現過的 key,其餘環境原封不動 —— 風險最小、
# 效果相同(子行程確實看不到不該看的 secret)。
#
# 用法:
#   source "$HOME/Delvin-agent/scripts/scoped_env.sh"
#   env_scope llm,alert -- claude $(claude_model light) -p "..."
#   env_scope none -- python3 some_pure_text_tool.py
#
# scope 可用逗號組合。`all` 是明示的逃生口(要在呼叫處寫清楚為什麼需要全部)。

SCOPED_ENV_REPO="${SCOPED_ENV_REPO:-$HOME/Delvin-agent}"

# md scope 的允許清單 = .env 全部 key 扣掉「其他事業線」前綴。
# 扣掉的是:皇海(KINGCONN_)、明欣(MINGXIN_)、QuietFix storefront(STOREFRONT_)、
# B2B 目錄站(DIR_/TAIWANTRADE_/EUROPAGES_/GLOBALSOURCES_/WIKIDATA_QFX_)、
# 個人帳號(DELVIN_LINKEDIN_/HN_)、下單(SINOPAC_)、發佈(PYPI_)、
# 各家 AI 服務的「網站登入密碼」(…_ACCOUNT_PASS/PW,那是控制台密碼,不是 API key)、
# 以及 CB_DESK_PASSWORD。
env_scope_md_keys() {
  local envf="$SCOPED_ENV_REPO/.env"
  [ -f "$envf" ] || return 0
  grep -oE '^[A-Z_][A-Z0-9_]*' "$envf" | sort -u | grep -vE \
    '^(KINGCONN_|MINGXIN_|STOREFRONT_|DIR_|TAIWANTRADE_|EUROPAGES_|GLOBALSOURCES_|WIKIDATA_QFX_|DELVIN_LINKEDIN_|HN_|SINOPAC_|PYPI_|CB_DESK_)' \
    | grep -vE '_(ACCOUNT_PASS|ACCOUNT_PW)$' | tr '\n' ' '
}

# scope → 允許帶進子行程的 key(空白分隔)。新增 scope 請一併更新 tests/。
env_scope_keys() {
  local out=""
  local IFS=','
  for s in $1; do
    case "$s" in
      none) : ;;
      llm)  out="$out GROQ_API_KEY GEMINI_API_KEY GEMINI_API_KEY_2 CEREBRAS_API_KEY
                     OPENROUTER_API_KEY MISTRAL_API_KEY CF_AI_PROXY_TOKEN CF_AI_PROXY_URL
                     VOYAGE_API_KEY EXA_API_KEY TAVILY_API_KEY FAL_KEY" ;;
      alert) out="$out MARKETDAILY_ALERT_TOKEN MARKETDAILY_INTERNAL_TOKEN" ;;
      deploy) out="$out CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID" ;;
      dns)   out="$out CLOUDFLARE_DNS_TOKEN CLOUDFLARE_ZONE_TOKEN" ;;
      mail)  out="$out BREVO_API_KEY BREVO_SMTP_KEY SENDER_EMAIL SENDER_NAME
                       GMAIL_USER GMAIL_APP_PASSWORD" ;;
      market) out="$out FINMIND_TOKEN FINMIND_USER FINMIND_PASSWORD FMP_API_KEY
                        MARKETDATA_API_TOKEN ALPHAVANTAGE_API_KEY FRED_API_KEY
                        NEWS_API_KEY QUOTE_BRIDGE_TOKEN" ;;
      trade) out="$out SINOPAC_API_KEY SINOPAC_SECRET_KEY SINOPAC_SIMULATION" ;;
      # md = MarketDaily 作業面:保留本業需要的一切,只砍掉「別的事業線」的憑證。
      # 為什麼先做這一刀而不是一步到位的精確白名單:digest 自癒/站台自修是生產關鍵路徑,
      # 白名單漏一把就會在半夜壞掉。先砍爆炸半徑(皇海網域帳密、10 個目錄站、LinkedIn、
      # 下單金鑰、PyPI…)——這些對 MarketDaily 的程式碼路徑零影響,砍了不可能壞。
      # 清單從 .env 現況推導,新增的同前綴 key 自動一起砍。
      md)    out="$out $(env_scope_md_keys)" ;;
      all)   out="$out __ALL__" ;;
      *) echo "env_scope: 未知 scope「$s」" >&2; return 2 ;;
    esac
  done
  echo $out
}

# env_scope <scope[,scope...]> -- <cmd> [args...]
env_scope() {
  local scope="$1"; shift
  [ "${1:-}" = "--" ] && shift
  local allow; allow="$(env_scope_keys "$scope")" || return 2
  case " $allow " in *" __ALL__ "*) "$@"; return $? ;; esac

  local envf="$SCOPED_ENV_REPO/.env" k
  local -a drop=()
  if [ -f "$envf" ]; then
    while read -r k; do
      [ -n "$k" ] || continue
      case " $allow " in *" $k "*) continue ;; esac
      drop+=("-u" "$k")
    done < <(grep -oE '^[A-Z_][A-Z0-9_]*' "$envf" | sort -u)
  fi
  env "${drop[@]}" "$@"
}

# env_scope_cmd <scope> —— 印出 `env -u K1 -u K2 …` 前綴。
# 給「只能收 argv、不能呼叫 shell function」的地方用(例如 cron_run_and_alert 的 "$@")。
# 與 env_scope 共用 env_scope_keys,不是第二份實作。
env_scope_cmd() {
  local allow; allow="$(env_scope_keys "$1")" || return 2
  case " $allow " in *" __ALL__ "*) echo "env"; return 0 ;; esac
  local envf="$SCOPED_ENV_REPO/.env" k out="env"
  if [ -f "$envf" ]; then
    while read -r k; do
      [ -n "$k" ] || continue
      case " $allow " in *" $k "*) continue ;; esac
      out="$out -u $k"
    done < <(grep -oE '^[A-Z_][A-Z0-9_]*' "$envf" | sort -u)
  fi
  echo "$out"
}
