# -*- coding: utf-8 -*-
"""HTTP ヘルパー: curl_cffi + PoW (hikamers.net) + リトライ + ポライトネス"""
import hashlib
import re
import time
import urllib.parse

from curl_cffi import requests as req

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

class Fetcher:
    def __init__(self, delay=0.4, domain_delays=None, proxies=None):
        self.delay = delay
        self.domain_delays = domain_delays or {}
        self.proxies = proxies or {}  # domain -> "socks5h://127.0.0.1:9050"
        self.sessions = {}  # domain -> session
        self.last_hit = {}

    def session_for(self, url):
        domain = urllib.parse.urlparse(url).netloc
        if domain not in self.sessions:
            kw = {"impersonate": "chrome124", "timeout": 60}
            proxy = self.proxies.get(domain)
            if proxy:
                kw["proxies"] = {"http": proxy, "https": proxy}
            self.sessions[domain] = req.Session(**kw)
            self.sessions[domain].headers.update({"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"})
        return self.sessions[domain]

    def polite(self, url):
        domain = urllib.parse.urlparse(url).netloc
        now = time.time()
        last = self.last_hit.get(domain, 0)
        wait = max(self.delay, self.domain_delays.get(domain, 0)) - (now - last)
        if wait > 0:
            time.sleep(wait)
        self.last_hit[domain] = time.time()

    def get_bytes(self, url, retries=4, referer=None):
        last_err = None
        for attempt in range(retries):
            self.polite(url)
            s = self.session_for(url)
            try:
                hdrs = {}
                if referer:
                    hdrs["Referer"] = referer
                r = s.get(url, headers=hdrs)
                if r.status_code in (403, 429) and attempt < retries - 1:
                    time.sleep(2 ** attempt + 1)
                    last_err = f"HTTP {r.status_code}"
                    continue
                if r.status_code >= 400:
                    last_err = f"HTTP {r.status_code}"
                    continue
                return r.content, r
            except Exception as e:
                last_err = str(e)
                time.sleep(2 ** attempt + 1)
        raise RuntimeError(f"fetch failed {url}: {last_err}")

    def get_text(self, url, enc=None, referer=None):
        data, resp = self.get_bytes(url, referer=referer)
        if enc:
            return data.decode(enc, "replace")
        # charset from headers
        ct = resp.headers.get("content-type", "")
        m = re.search(r"charset=([\w-]+)", ct, re.I)
        if m:
            return data.decode(m.group(1), "replace")
        # meta charset
        head = data[:2048].decode("ascii", "ignore")
        m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
        if m:
            return data.decode(m.group(1), "replace")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("euc-jp", "replace")


def solve_hikamers_pow(fetcher):
    """hikamers.net のセキュリティチャレンジ (SHA-256 PoW) を解いてセッションを確立する"""
    s = fetcher.session_for("https://hikamers.net/")
    # まずチャレンジページを取る
    data, resp = fetcher.get_bytes("https://hikamers.net/wiki/")
    html = data.decode("utf-8", "replace")
    m = re.search(r'const NONCE="([^"]+)",EXPIRES="([^"]+)",SIG="([^"]+)",DIFFICULTY=(\d+),RETURN="([^"]+)"', html)
    if not m:
        # 既に認証済み (セッション有効) の可能性
        return
    nonce, expires, sig, diff, ret = m.groups()
    diff = int(diff)
    target = "0" * diff
    i = 0
    while True:
        if hashlib.sha256((nonce + str(i)).encode()).hexdigest().startswith(target):
            break
        i += 1
    form = urllib.parse.urlencode({"nonce": nonce, "expires": expires, "sig": sig,
                                   "solution": str(i), "return": ret}).encode()
    r = s.post("https://hikamers.net/api/auth", data=form)
    if r.status_code >= 400:
        raise RuntimeError(f"PoW auth failed: HTTP {r.status_code}")
    time.sleep(0.5)

def hikamers_get_json(fetcher, params):
    """hikamers API 呼び出し。セキュリティチェックに当たったら PoW を解き直してリトライ"""
    s = fetcher.session_for("https://hikamers.net/")
    for attempt in range(3):
        fetcher.polite("https://hikamers.net/api.php")
        r = s.get("https://hikamers.net/api.php", params=params)
        if r.status_code == 200 and "セキュリティチェック" not in r.text[:500]:
            return r.json()
        # challenge かエラー → PoW を解き直す
        solve_hikamers_pow(fetcher)
        time.sleep(1)
    raise RuntimeError("hikamers api failed after PoW retries")
