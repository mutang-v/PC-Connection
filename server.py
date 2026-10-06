"""电脑伴侣启动入口。"""
from http.server import ThreadingHTTPServer
from companion.config import settings
from companion.http_api import CompanionHandler, local_lan_ip
from companion.qr_text import qr_payload, qr_terminal_text


def main():
    address = (settings.host, settings.port)
    server = ThreadingHTTPServer(address, CompanionHandler)
    print("电脑伴侣模块化版（安全配对试运行）已启动")
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

if __name__ == "__main__":
    main()
