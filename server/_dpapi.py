"""Windows DPAPI 加解密（当前用户作用域）。

用途：把本机会话私钥加密后存到 server.json 旁边。
  · 明文不落盘 —— 磁盘上只有密文；
  · 只有「同一台机器 + 同一个 Windows 用户」能解开（CryptProtectData 默认
    绑定当前用户 SID + 机器），拷到别的机器或别的账户解出来是乱码；
  · 所以启动器重启、工作台单独启动时，后端都能自己把私钥取回来，
    页面照常拿到 key，不会因为「内存里那份没了」就全部 401。

为什么不是「直接存明文」：那等于把私钥写在硬盘上，任何能读到程序数据目录
的程序都能拿走，跟原来「明文未落盘」的承诺正相反。

为什么不是「只存 sha256」：哈希不可逆，后端没法把私钥交还给页面，
工作台就永远拿不到 key —— 这是 4.0.2 改造后暴露的真实矛盾。

非 Windows 平台（本项目不会跑到）退化为返回空，调用方按「没有可用私钥」处理。
"""
import base64
import os

_IS_WIN = os.name == "nt"


def _dpapi(data: bytes, protect: bool) -> bytes:
    """调用 CryptProtectData / CryptUnprotectData。"""
    if not _IS_WIN:
        return b""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    def _blob(raw: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(raw, len(raw))
        return DATA_BLOB(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _take(blob):
        n = blob.cbData
        p = blob.pbData
        out = ctypes.string_at(p, n)
        ctypes.windll.kernel32.LocalFree(p)
        return out

    crypt32 = ctypes.windll.crypt32
    src = _blob(data)
    dst = DATA_BLOB()
    # 描述文字留空；CRYPTPROTECT_UI_FORBIDDEN=0x1 避免弹框
    flags = 0x1
    ok = (crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData)(
        ctypes.byref(src), None, None, None, None, flags, ctypes.byref(dst)
    )
    if not ok:
        return b""
    return _take(dst)


def seal(plain: str) -> str:
    """明文 -> base64 密文。失败返回空串。"""
    raw = str(plain or "").strip()
    if not raw:
        return ""
    try:
        blob = _dpapi(raw.encode("utf-8"), protect=True)
    except Exception:  # noqa: BLE001
        return ""
    if not blob:
        return ""
    return base64.b64encode(blob).decode("ascii")


def unseal(cipher_b64: str) -> str:
    """base64 密文 -> 明文。失败返回空串。"""
    text = str(cipher_b64 or "").strip()
    if not text:
        return ""
    try:
        blob = base64.b64decode(text)
    except Exception:  # noqa: BLE001
        return ""
    try:
        raw = _dpapi(blob, protect=False)
    except Exception:  # noqa: BLE001
        return ""
    if not raw:
        return ""
    try:
        return raw.decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""
