"""HTTP 路由层：认证、协议和静态文件服务。"""
import base64
import io
import json
import socket
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from .actions import perform_action, set_volume, get_volume
from .metrics import MetricsCollector
from .auth import AuthManager
from .p9_controller import P9Controller
from .system_tools import read_clipboard, write_clipboard, kill_process, notify

BASE_DIR = Path(__file__).resolve().parent.parent

# 二维码编码串前缀（App 扫码依据此前缀识别）
QR_PREFIX = "PCCONN:1|"


def local_lan_ip() -> str:
    """返回本机在局域网内的 IPv4 地址（用于二维码/二维码 host）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP 不真正发包，仅利用 connect 让系统选择出口网卡地址
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:  # noqa: BLE001
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def make_pair_qr_png(payload: str, box_size: int = 8, border: int = 2) -> bytes:
    """用 qrcode 生成二维码 PNG 字节。"""
    import qrcode
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=border)
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

class CompanionHandler(SimpleHTTPRequestHandler):
    collector = MetricsCollector()
    auth = AuthManager(BASE_DIR / "data")
    p9 = P9Controller()
    web_root = BASE_DIR / "web"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(self.web_root), **kwargs)

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return self.auth.is_authorized(header[7:].strip())

    def _token_from_header(self):
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return ""
        return header[7:].strip()

    def do_GET(self):
        route = self.path.split("?", 1)[0]
        if route.startswith("/api/"):
            if route == "/api/paircode":
                self.auth.ensure_pair_code()  # 过期则滚动刷新，避免二维码变空
                remaining = max(0, int(self.auth.pair_expires - time.time()))
                authorized = self.auth.is_authorized(self._token_from_header())
                return self._json({
                    "ok": True,
                    "paired": authorized,
                    "pair_consumed": self.auth.pair_consumed,
                    "pair_code": None if (authorized or self.auth.pair_consumed or remaining <= 0) else self.auth.pair_code,
                    "expires_in": remaining if not authorized else -1,
                })
            if route == "/api/pair/qr":
                # 返回供手机扫码的配对二维码（无需 token，用于配对阶段）
                self.auth.ensure_pair_code()  # 过期则滚动刷新，避免二维码变空
                authorized = self.auth.is_authorized(self._token_from_header())
                remaining = max(0, int(self.auth.pair_expires - time.time()))
                code = None if (authorized or self.auth.pair_consumed or remaining <= 0) else self.auth.pair_code
                host = local_lan_ip()
                payload = f"{QR_PREFIX}host={host}&code={code or ''}" if code else ""
                try:
                    png = make_pair_qr_png(payload) if payload else b""
                    return self._json({
                        "ok": True,
                        "paired": authorized,
                        "pair_consumed": self.auth.pair_consumed,
                        "host": host,
                        "code": code,
                        "payload": payload,
                        "expires_in": remaining if not authorized else -1,
                        "png_b64": base64.b64encode(png).decode("ascii") if png else "",
                    })
                except Exception as exc:  # noqa: BLE001
                    return self._json({"ok": False, "message": f"生成二维码失败：{exc}"}, 500)
            if not self._authorized():
                return self._json({"ok": False, "error": "auth_required", "message": "请先配对可信设备。"}, 401)
            if route == "/api/stats":
                return self._json(self.collector.stats())
            if route == "/api/processes":
                return self._json({"processes": self.collector.top_processes()})
            if route == "/api/processes/cpu":
                return self._json({"processes": self.collector.cpu_processes()})
            if route == "/api/disk":
                return self._json({"partitions": self.collector.disk_partitions()})
            if route == "/api/volume":
                return self._json({"ok": True, "volume": get_volume()})
            if route == "/api/alerts":
                return self._json(self.collector.alerts())
            if route == "/api/clipboard":
                return self._json(read_clipboard())
            if route == "/api/actions":
                # 返回电脑端可用操作白名单，便于客户端动态渲染入口
                from .actions import ALLOWED_ACTIONS
                return self._json({"ok": True, "actions": sorted(ALLOWED_ACTIONS)})
            if route == "/api/p9/screenshot":
                try:
                    data = self.p9.screenshot()
                    return self._json(data, 200 if data.get("ok") else 502)
                except Exception as exc:  # noqa: BLE001
                    return self._json({"ok": False, "message": f"截图失败：{exc}"}, 500)
            if route == "/api/p9/status":
                try:
                    return self._json(self.p9.status())
                except Exception as exc:  # noqa: BLE001
                    return self._json({"ok": False, "message": f"读取 P9 状态失败：{exc}"}, 500)
            return self._json({"ok": False, "message": "不支持的接口"}, 404)
        return super().do_GET()

    def do_POST(self):
        route = self.path.split("?", 1)[0]
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 2048:
                return self._json({"ok": False, "message": "请求内容无效"}, 400)
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("payload must be an object")
        except Exception:
            return self._json({"ok": False, "message": "无法读取请求内容"}, 400)

        if route == "/api/pair":
            token, message, status = self.auth.pair(payload.get("code"))
            response = {"ok": status == 200, "message": message}
            if token:
                response["token"] = token
            return self._json(response, status)

        if route.startswith("/api/") and not self._authorized():
            return self._json({"ok": False, "error": "auth_required", "message": "请先配对可信设备。"}, 401)

        if route == "/api/p9/action":
            data, status = self.p9.perform_action(payload.get("action"))
            return self._json(data, status)

        if route == "/api/clipboard":
            return self._json(write_clipboard(payload.get("text", "")))

        if route == "/api/processes/kill":
            data, status = kill_process(
                pid=payload.get("pid"),
                name=payload.get("name"),
                confirm=bool(payload.get("confirm", False)),
            )
            return self._json(data, status)

        if route == "/api/notify":
            return self._json(notify(payload.get("title"), payload.get("message")))

        if route != "/api/action":
            return self._json({"ok": False, "message": "不支持的操作"}, 404)
        action = payload.get("action")
        if action == "volume_set":
            data, status = set_volume(level=payload.get("level"), delta=payload.get("delta"))
            return self._json(data, status)
        data, status = perform_action(action, confirm=bool(payload.get("confirm", False)))
        return self._json(data, status)

    def log_message(self, fmt, *args):
        if self.path.split("?", 1)[0] not in ("/api/stats", "/api/processes", "/api/processes/cpu", "/api/disk", "/api/actions", "/api/action", "/api/pair", "/api/pair/qr", "/api/p9/status", "/api/p9/action", "/api/p9/screenshot", "/api/paircode", "/api/volume", "/api/alerts", "/api/clipboard", "/api/processes/kill", "/api/notify"):
            super().log_message(fmt, *args)
