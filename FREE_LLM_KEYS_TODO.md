# 免費 LLM 席次 — 你只剩兩家要親手註冊（各 2 分鐘）

系統已預接線：**拿到 key 只要貼進 `~/Delvin-agent/.env`，不用改任何程式，下一班日報就自動多一席。**
這兩家我沒法自動註冊，因為最後一步是「證明你是人類」的驗證碼（OpenRouter 是 Cloudflare Turnstile、Cerebras 是選圖 reCAPTCHA），自動解＝違反對方條款，所以留給你。

---

## 1. Cerebras（推理極快、免費層大方，最推薦先弄這家）

1. 開 https://cloud.cerebras.ai/
2. Email 填 `delvin.12345678@gmail.com` → 過 reCAPTCHA → CONTINUE WITH EMAIL
   （或直接點 **GOOGLE** 用你的 Google 帳號登入，最快）
3. 進控制台後左邊找 **API Keys** → Create Key → 複製
4. 貼進 `.env`：
   ```
   CEREBRAS_API_KEY=csk-你複製的key
   ```

## 2. OpenRouter（一把 key 通上百個模型，含多個 `:free`）

1. 開 https://openrouter.ai/sign-up
2. 用 **Google 登入最省事**（避開 Turnstile）
3. 右上頭像 → **Keys** → Create Key → 複製
4. 貼進 `.env`：
   ```
   OPENROUTER_API_KEY=sk-or-你複製的key
   ```

---

## 貼完怎麼確認生效

在 winrig 跑一次：
```bash
cd ~/Delvin-agent && .venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import analyzer
for n,f in [('openrouter',analyzer._call_openrouter),('cerebras',analyzer._call_cerebras)]:
    try: print(n, '->', f('回OK兩字')[:20])
    except Exception as e: print(n, '->', str(e)[:60])
"
```
看到回 `OK` 就代表那席活了，council 下次自動用它。

---

## 已經幫你接好的（不用動）
- ✅ **Cloudflare Workers AI**（Llama-3.3-70B，免費 10k neurons/日）— 我用你的 CF 帳號自動部署好了，已是 council 第 6 席 + 備援鏈一層
- ✅ **winrig 本地 5080 GPU**（qwen2.5-14B）— 零配額零 429，council 第 5 席 + 備援鏈最後一張網
- ⏳ **OpenAI** — 你的 key 還在，但帳上沒錢；去 platform.openai.com 儲值幾美元就自動復活一席
