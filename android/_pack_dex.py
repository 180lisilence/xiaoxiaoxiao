"""把 classes.dex 以 STORE 方式追加进 APK，并保证数据区 4 字节对齐。

为什么不直接用 zip 工具：
  · `aapt add` 一律 DEFLATE，压不了 STORE；
  · `zipalign` 只调偏移不改压缩方式；
  · 本机 Git Bash 没带 zip。
Android 12+（API 31）要求 classes.dex 存 STORE 且 offset%4==0，否则
INSTALL_PARSE_FAILED_NOT_APK（报错文案只说「软件包似乎无效」，压根不提 dex）。

核心思路：**不碰原 APK 的任何已有字节**。
  1. 读原 APK 的全部原始字节；
  2. 找到 EOCD（中央目录尾部记录），取出中央目录起点与所有中央目录记录；
  3. 逐条解析中央目录记录，得到每个条目的本地头偏移、名字、CRC、大小、
     压缩方式 —— 这些原样保留；
  4. 在文件末尾（中央目录之前的位置）追加 classes.dex 的本地头+数据；
  5. 拼上「原有中央目录记录 + 新的一条 classes.dex 记录」；
  6. 写新的 EOCD。

这样资源条目一个字节都不动，只有两端新增内容，签名前的 APK 结构完全合法。
"""
import struct
import sys
import zlib

SIG_EOCD = 0x06054B50
SIG_CEN = 0x02014B50
SIG_LOC = 0x04034B50


def read_entries(buf):
    """返回 (eocd_offset, cd_offset, cd_size, [raw_central_records])."""
    # 从尾部向前找 EOCD（可能带注释，最多 65535 字节）
    n = len(buf)
    start = max(0, n - (22 + 65535))
    eocd = -1
    for i in range(n - 22, start - 1, -1):
        if struct.unpack("<I", buf[i:i + 4])[0] == SIG_EOCD:
            eocd = i
            break
    if eocd < 0:
        raise SystemExit("找不到 EOCD")
    (_, disk, cd_disk, n_here, n_total,
     cd_size, cd_off, clen) = struct.unpack("<IHHHHIIH", buf[eocd:eocd + 22])
    if cd_off == 0xFFFFFFFF or n_total == 0xFFFF:
        raise SystemExit("不支持 ZIP64")

    recs = []
    p = cd_off
    for _ in range(n_total):
        if struct.unpack("<I", buf[p:p + 4])[0] != SIG_CEN:
            raise SystemExit("中央目录损坏 @%d" % p)
        (_, vmade, vneed, flags, method, mtime, mdate, crc,
         csize, usize, nlen, elen, clen2, dstart,
         iattr, eattr, lho) = struct.unpack("<IHHHHHHIIIHHHHHII", buf[p:p + 46])
        name = buf[p + 46:p + 46 + nlen].decode("utf-8", "replace")
        total = 46 + nlen + elen + clen2
        recs.append({
            "raw": buf[p:p + total],
            "name": name,
            "method": method,
            "flags": flags,
            "crc": crc,
            "csize": csize,
            "usize": usize,
            "eattr": eattr,
            "lho": lho,
            "mtime": mtime,
            "mdate": mdate,
            "vneed": vneed,
        })
        p += total
    return eocd, cd_off, cd_size, recs


def repack(src_apk, dex_path, out_apk):
    with open(dex_path, "rb") as f:
        dex = f.read()
    if dex[:4] != b"dex\n":
        raise SystemExit("不是合法 dex")
    with open(src_apk, "rb") as f:
        buf = bytearray(f.read())

    eocd, cd_off, cd_size, recs = read_entries(buf)
    if any(r["name"] == "classes.dex" for r in recs):
        raise SystemExit("源 APK 已含 classes.dex，逻辑不对")

    # 原文件「中央目录之前」的部分原样保留
    out = bytearray(buf[:cd_off])

    # 追加 classes.dex 本地头 + 数据（STORE），extra 用于对齐
    name = b"classes.dex"
    lho = len(out)
    for pad in range(0, 5):
        extra = struct.pack("<HH", 0xD935, pad) + b"\x00" * pad if pad else b""
        data_off = lho + 30 + len(name) + len(extra)
        if data_off % 4 == 0:
            break
    else:
        raise SystemExit("对齐失败")

    crc = zlib.crc32(dex) & 0xFFFFFFFF
    out += struct.pack(
        "<IHHHHHIIIHH",
        SIG_LOC, 20, 0, 0, 0, 0x0021,
        crc, len(dex), len(dex), len(name), len(extra),
    )
    out += name + extra
    out += dex

    # 新中央目录 = 原记录 + 新记录
    new_cd_off = len(out)
    for r in recs:
        out += r["raw"]
    extra_len = len(extra)
    rec = struct.pack(
        "<IHHHHHHIIIHHHHHII",
        SIG_CEN, 20, 20, 0, 0, 0, 0x0021,
        crc, len(dex), len(dex),
        len(name), extra_len, 0, 0, 0, 0o644 << 16, lho,
    ) + name + extra
    out += rec
    new_cd_size = len(out) - new_cd_off

    out += struct.pack(
        "<IHHHHIIH",
        SIG_EOCD, 0, 0,
        len(recs) + 1, len(recs) + 1,
        new_cd_size, new_cd_off, 0,
    )

    with open(out_apk, "wb") as f:
        f.write(bytes(out))
    return data_off


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    off = repack(argv[1], argv[2], argv[3])
    print("REPACK_OK dex_data_offset=%d  %%4=%d" % (off, off % 4))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
