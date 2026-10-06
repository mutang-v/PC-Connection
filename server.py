"""电脑伴侣启动入口。

用法：
    python server.py             # 默认：打开图形控制面板（Tkinter + 系统托盘）
    python server.py --gui       # 强制图形控制面板
    python server.py --console   # 传统命令行黑窗口模式（保留）

图形面板可在托盘持续后台运行，并提供二维码/配对码/网页控制台入口。
"""
import argparse
import sys

from http.server import ThreadingHTTPServer

from companion.config import settings
from companion.http_api import CompanionHandler, local_lan_ip
from companion.qr_text import qr_payload, qr_terminal_text


def run_console() -> None:
    """传统命令行模式：打印信息并在前台 serve_forever。"""
    address = (settings.host, settings.port)
    server = ThreadingHTTPServer(address, CompanionHandler)
    print("电脑伴侣 已启动（命令行模式）")
    print(f"本机访问：http://127.0.0.1:{settings.port}")
    ip = local_lan_ip()
    print(f"手机访问：http://{ip}:{settings.port}  (电脑的 WLAN IPv4 地址)")
    code = CompanionHandler.auth.pair_code
    print(f"当前配对码（10 分钟内有效，过期自动刷新）：{code}")
    payload = qr_payload(host=ip, code=code)
    print("请用手机电脑伴侣 App 扫描下方二维码自动配对：")
    print("─" * 40)
    print(qr_terminal_text(payload))
    print("─" * 40)
    print("请只在可信的私人热点/局域网使用，并仅允许 Windows 专用网络通过防火墙。")
    print("不要将端口映射到公网；当前 HTTP 局域网通信未加密。")
    print("保持此窗口运行；停止时按 Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("正在停止电脑伴侣……")
    finally:
        server.server_close()


def run_gui() -> None:
    """图形控制面板模式（Tkinter + 系统托盘）。服务在前台面板线程内运行。"""
    from companion.gui import main as gui_main
    raise SystemExit(gui_main())


def main() -> None:
    parser = argparse.ArgumentParser(description="电脑伴侣 · 电脑端入口")
    parser.add_argument(
        "--console", action="store_true",
        help="使用传统命令行黑窗口模式（默认是图形面板）",
    )
    parser.add_argument(
        "--gui", action="store_true",
        help="强制使用图形控制面板模式",
    )
    args = parser.parse_args()

    use_gui = args.gui or not args.console
    if use_gui:
        run_gui()
    else:
        run_console()


if __name__ == "__main__":
    main()
