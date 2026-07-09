"""
AI自動添削（Google Apps Script Webアプリ）にStreamlitからiframe埋め込みで
生徒を受け渡すための、署名付きトークンの生成。

student_idをそのままURLパラメータに渡すと、他の生徒になりすましてURLを
書き換えるだけで他人の添削・分析ノートにアクセスできてしまう。これを防ぐため、
有効期限付きのペイロードをHMAC-SHA256で署名したトークンを発行する。
GAS側（Code.gs）は同じ秘密鍵（GAS_HMAC_SECRET）で署名を検証し、改ざん・
期限切れのトークンを拒否する。
"""

import base64
import hashlib
import hmac
import json
import time

DEFAULT_TTL_SECONDS = 600


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_gas_token(student_id, secret, ttl_seconds=DEFAULT_TTL_SECONDS):
    """student_idと有効期限をHMAC-SHA256で署名したトークン文字列を返す。
    形式: base64url(payload_json) + "." + base64url(signature)
    GAS側のverifyToken()と対になる実装（同じsecretを使うこと）。"""
    payload = {"sid": student_id, "exp": int(time.time()) + ttl_seconds}
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"
