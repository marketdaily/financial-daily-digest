#!/usr/bin/env python3
"""印出 delvin@quietfix.studio 的 Google 兩步驟驗證碼。

背景(2026-08-24):08-09 那次是用 headless TOTP 幫他開通 2SV,金鑰留在 winrig,
Delvin 自己的驗證器裡從來沒有這一把 —— 這就是他登入永遠卡第二關的原因(open #196)。
Google 因此把一般帳號復原壓了 30 天冷卻(open #535)。有了這支,那一關就過得去。

用法:python3 scripts/qf_totp.py          印當下與下一組
      python3 scripts/qf_totp.py --watch  每 5 秒更新(復原流程來回操作時用)
"""
import base64, hashlib, hmac, pathlib, struct, sys, time

SECRET_FILE = pathlib.Path.home() / ".marketdaily-secrets/quietfix_workspace_totp.txt"


def code(at=None):
    raw = "".join(SECRET_FILE.read_text().split()).upper().rstrip("=")
    key = base64.b32decode(raw + "=" * (-len(raw) % 8))
    t = int(at or time.time()) // 30
    h = hmac.new(key, struct.pack(">Q", t), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return f"{(struct.unpack('>I', h[o:o+4])[0] & 0x7FFFFFFF) % 1000000:06d}"


def main():
    if not SECRET_FILE.exists():
        sys.exit(f"❌ 找不到金鑰:{SECRET_FILE}")
    watch = "--watch" in sys.argv
    while True:
        now = time.time()
        left = 30 - int(now) % 30
        # 剩不到 5 秒就別給了,他還沒打完就過期,只會以為碼是錯的
        if left < 5:
            print(f"  ⏳ 這組只剩 {left} 秒,等下一組…", flush=True)
            time.sleep(left + 1)
            continue
        print(f"  delvin@quietfix.studio 2FA:  {code(now)}   (剩 {left} 秒) | 下一組 {code(now+30)}",
              flush=True)
        if not watch:
            return 0
        time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())
