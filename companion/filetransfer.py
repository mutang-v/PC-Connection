"""文件互传：手机 ↔ 电脑 双向收发（局域网）。

安全设计：
- 只允许读写固定的 share/ 接收目录，杜绝路径穿越。
- 文件名做白名单净化（仅保留安全字符）。
- 仅接受 base64 文本载荷，上传体有大小上限。
- 所有操作都要鉴权（由路由层统一校验）。
"""
import base64
import os
import re
import time
from pathlib import Path

# 接收目录（项目根 / share）
BASE_DIR = Path(__file__).resolve().parent.parent
SHARE_DIR = BASE_DIR / "share"

# 单文件上限：20MB（base64 后约 27MB）
MAX_FILE_BYTES = 20 * 1024 * 1024
# 允许提交的文件数量上限
MAX_FILES_PER_POST = 20

# 文件名安全字符（中文、字母数字、-_. 空格、括号）
_NAME_RE = re.compile(r"[^\w\-. ()（）\[\]【】]+", re.UNICODE)


def _safe_name(raw: str) -> str:
    """净化文件名，只保留安全字符，并防止路径穿越。"""
    if not raw:
        return "unnamed"
    name = os.path.basename(raw.replace("\\", "/")).strip()
    name = _NAME_RE.sub("_", name)
    name = name.strip(" .")
    if len(name) > 120:
        stem, ext = os.path.splitext(name)
        name = stem[:110] + ext
    return name or "unnamed"


def ensure_share_dir() -> None:
    SHARE_DIR.mkdir(parents=True, exist_ok=True)


def list_files() -> dict:
    """列出 share/ 目录下的可下载文件。"""
    ensure_share_dir()
    items = []
    for p in sorted(SHARE_DIR.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file():
            st = p.stat()
            items.append({
                "name": p.name,
                "size": st.st_size,
                "size_kb": round(st.st_size / 1024, 1),
                "mtime": int(st.st_mtime),
                "mtime_str": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            })
    return {"ok": True, "path": str(SHARE_DIR), "files": items}


def upload_base64(files) -> dict:
    """接收并保存文件。files 形如：[{name:..., size:..., b64:...}, ...]"""
    ensure_share_dir()
    if not isinstance(files, list):
        return {"ok": False, "message": "files 必须为列表"}
    if len(files) > MAX_FILES_PER_POST:
        return {"ok": False, "message": f"一次最多 {MAX_FILES_PER_POST} 个文件"}
    saved = []
    errors = []
    for f in files:
        if not isinstance(f, dict):
            errors.append("条目无效")
            continue
        raw_name = f.get("name", "unnamed")
        b64 = f.get("b64", "")
        name = _safe_name(raw_name)
        if not b64:
            errors.append(f"{name}: 缺少内容")
            continue
        try:
            raw = base64.b64decode(b64, validate=True)
        except Exception:
            errors.append(f"{name}: 内容不是有效 base64")
            continue
        if len(raw) > MAX_FILE_BYTES:
            errors.append(f"{name}: 超过 {MAX_FILE_BYTES // (1024 * 1024)}MB 上限")
            continue
        # 防重名：若已存在则追加时间戳
        final_name = name
        if (SHARE_DIR / final_name).exists():
            stem, ext = os.path.splitext(name)
            final_name = f"{stem}_{int(time.time())}{ext}"
        try:
            (SHARE_DIR / final_name).write_bytes(raw)
            saved.append(final_name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: 写入失败 {exc}")
    msg = f"已保存 {len(saved)} 个文件" if saved else "未保存任何文件"
    if errors:
        msg += "；" + "；".join(errors[:3])
        if len(errors) > 3:
            msg += f" 等共 {len(errors)} 项失败"
    return {"ok": bool(saved), "message": msg, "saved": saved, "errors": errors}


def download_file(name: str):
    """下载 share/ 内的文件。返回 (bytes, filename) 或抛异常/None。"""
    if not name:
        return None
    target = (SHARE_DIR / _safe_name(name)).resolve()
    # 必须落在 share 目录内
    if not str(target).startswith(str(SHARE_DIR.resolve())):
        return None
    if not target.is_file():
        return None
    return target.read_bytes(), target.name
