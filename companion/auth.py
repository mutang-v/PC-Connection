"""单设备配对与 Bearer Token 认证。仅用于可信私人局域网试运行。"""
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from threading import Lock


class AuthManager:
    def __init__(self, data_dir: Path, pair_code: str | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.token_file = self.data_dir / "device_token.json"
        self.pair_code = pair_code or f"{secrets.randbelow(100_000_000):08d}"
        self.pair_expires = time.time() + 600
        self.failed_attempts = 0
        self.pair_consumed = False
        self._lock = Lock()
        self._token_hash = self._load_token_hash()

    def _load_token_hash(self):
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
            value = data.get("token_sha256", "")
            return value if isinstance(value, str) and len(value) == 64 else None
        except (OSError, ValueError, TypeError):
            return None

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def ensure_pair_code(self):
        """若配对码已过期、且尚未被使用/配对，则滚动生成一个新的 8 位配对码。
        这样电脑端网页二维码不会因 10 分钟过期而变空，无需重启服务。"""
        with self._lock:
            if (not self.pair_consumed and not self._token_hash
                    and time.time() > self.pair_expires):
                self.pair_code = f"{secrets.randbelow(100_000_000):08d}"
                self.pair_expires = time.time() + 600
                self.failed_attempts = 0
            return self.pair_code, self.pair_expires

    def pair(self, supplied_code):
        with self._lock:
            if self.pair_consumed or time.time() > self.pair_expires:
                return None, "配对码已失效，请在电脑服务窗口重启服务后获取新配对码。", 410
            if self.failed_attempts >= 5:
                return None, "配对尝试次数过多，请重启电脑伴侣后再试。", 429
            if not isinstance(supplied_code, str) or not hmac.compare_digest(supplied_code, self.pair_code):
                self.failed_attempts += 1
                return None, "配对码不正确。", 401
            token = secrets.token_urlsafe(32)
            token_hash = self._hash(token)
            tmp = self.token_file.with_suffix(".tmp")
            tmp.write_text(json.dumps({"token_sha256": token_hash}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.token_file)
            self._token_hash = token_hash
            self.pair_consumed = True
            return token, "设备配对成功。", 200

    def is_authorized(self, token):
        if not isinstance(token, str) or not self._token_hash:
            return False
        return hmac.compare_digest(self._hash(token), self._token_hash)
