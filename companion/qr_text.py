"""把配对信息渲染成可在终端显示的二维码文本（兼容 Windows 终端 UTF-8）。"""
import qrcode

# 半块字符：▀=上黑下白 ▄=上白下黑 █=全黑 空格=全白
_BLOCK_BOTH = "█"
_BLOCK_TOP = "▀"
_BLOCK_BOT = "▄"
_BLOCK_NONE = " "


def qr_payload(host: str, code: str, prefix: str = "PCCONN:1|") -> str:
    return f"{prefix}host={host}&code={code}"


def qr_terminal_text(payload: str) -> str:
    """生成终端可显示的二维码（矩阵 + 半块字符，垂直两像素合并为一行）。"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    matrix = qr.get_matrix()  # list of list[bool]
    n = len(matrix)
    lines = []
    # 每两行矩阵合并为一行半块字符
    for y in range(0, n, 2):
        row = []
        for x in range(n):
            top = matrix[y][x]
            bottom = matrix[y + 1][x] if y + 1 < n else False
            if top and bottom:
                row.append(_BLOCK_BOTH)
            elif top:
                row.append(_BLOCK_TOP)
            elif bottom:
                row.append(_BLOCK_BOT)
            else:
                row.append(_BLOCK_NONE)
        lines.append("".join(row))
    return "\n".join(lines)
