"""检查 APK 里的 classes.dex 是否满足 Android 12+ 的安装要求。

不用外部库，直接解析 zip 的中央目录（EOCD → 中央目录 → 本地文件头）。

判据：
  1 classes.dex 条目必须存在
  2 compress_type == 0（STORE，即不压缩）
  3 本地文件头里的数据起始偏移 % 4 == 0

不满足第 2、3 条时 Android 12+（API 31）会报
INSTALL_PARSE_FAILED_NOT_APK，且报错文案完全不提 dex —— 只会说
「软件包似乎无效」，非常难查，所以这里单独立一个可复现断言。
"""
import struct
import sys
import zipfile


def find_dex_offset(path):
    """返回 classes.dex 数据区的绝对偏移（从本地文件头算）。"""
    with zipfile.ZipFile(path) as z:
        info = None
        for i in z.infolist():
            if i.filename == "classes.dex":
                info = i
                break
        if info is None:
            return None, None, None
        # 本地文件头比中央目录多出「文件名 + extra」长度，且两者 extra 长度可能不同，
        # 因此必须在本地头里重读一遍。
        with open(path, "rb") as f:
            f.seek(info.header_offset)
            hdr = f.read(30)
            if len(hdr) < 30 or hdr[:4] != b"PK\x03\x04":
                return info, None, None
            name_len = struct.unpack("<H", hdr[26:28])[0]
            extra_len = struct.unpack("<H", hdr[28:30])[0]
            data_off = info.header_offset + 30 + name_len + extra_len
        return info, data_off, data_off % 4


def main(argv):
    if len(argv) < 2:
        print("用法: _check_apk_dex.py <apk>")
        return 2
    path = argv[1]
    info, offset, mod = find_dex_offset(path)
    if info is None:
        print("FAIL 找不到 classes.dex")
        return 1

    method = info.compress_type
    method_name = {0: "STORE", 8: "DEFLATE"}.get(method, str(method))
    print("classes.dex: comp=%d(%s) size=%d offset=%d offset%%4=%d"
          % (method, method_name, info.file_size, offset or -1, mod if mod is not None else -1))

    ok = True
    if method != 0:
        print("FAIL compress_type 必须是 0(STORE)，实际 %d(%s)" % (method, method_name))
        ok = False
    if offset is None:
        print("FAIL 读不到本地文件头")
        ok = False
    elif mod != 0:
        print("FAIL 数据偏移 %d 未 4 字节对齐（%%4=%d）" % (offset, mod))
        ok = False

    if ok:
        print("DEX_OK")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
