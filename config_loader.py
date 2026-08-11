import requests
from config import US_STOCKS as _DEFAULT_US, TW_STOCKS as _DEFAULT_TW

WORKER_URL = "https://marketdaily-webhook.delvin-12345678.workers.dev"
ADMIN_EMAIL = "delvin.12345678@gmail.com"

_cache = None

def get_global_config() -> dict:
    """Fetch admin config from Cloudflare KV. Caches in-process. Falls back to config.py."""
    global _cache
    if _cache is not None:
        return _cache
    try:
        resp = requests.post(
            f"{WORKER_URL}/admin/get-config",
            json={"email": ADMIN_EMAIL},
            timeout=5,
        )
        if resp.ok:
            data = resp.json()
            remote = data.get("config")
            if remote:
                _cache = remote
                return _cache
    except Exception:
        pass
    _cache = {
        "us_stocks": [s if isinstance(s, str) else s for s in _DEFAULT_US],
        "tw_stocks": _DEFAULT_TW,
        "us_feeds":  [],
        "tw_feeds":  [],
        "domains":   [],
    }
    return _cache


def get_us_stocks() -> list:
    return get_global_config().get("us_stocks", _DEFAULT_US)


def get_tw_stocks() -> list:
    return get_global_config().get("tw_stocks", _DEFAULT_TW)


def get_us_feeds() -> list:
    """Returns [(domain, url), ...] for enabled US RSS feeds, or None to use defaults."""
    feeds = get_global_config().get("us_feeds")
    if not feeds:
        return None
    return [(f["domain"], f["url"]) for f in feeds if f.get("on", True) and str(f.get("url", "")).startswith("https://")]  # SECURITY(2026-08-11): 只放行 https,擋 file:// 與內網 SSRF


def get_tw_feeds() -> list:
    feeds = get_global_config().get("tw_feeds")
    if not feeds:
        return None
    return [(f["domain"], f["url"]) for f in feeds if f.get("on", True) and str(f.get("url", "")).startswith("https://")]  # SECURITY(2026-08-11): 只放行 https,擋 file:// 與內網 SSRF


def get_domains() -> list:
    domains = get_global_config().get("domains")
    return domains if domains else None
