"""模块 1：文件结构与元数据取证

- EXIF 全量解析（相机信息、软件标签、时间）
- JPEG 量化表（DQT）/ Huffman 表提取与编码器指纹判断
- 内嵌缩略图一致性检查
- C2PA / JUMBF 凭证扫描（原始字节级，无需官方 SDK）
- 文件质量评级（original / transcoded / screenshot_like）
"""
import hashlib
import io
import os
import re
import struct

import numpy as np
from PIL import Image

from .common import finding, module_result

# libjpeg 标准亮度/色度基础量化表（质量 50）
_LUMA_BASE = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
]
_CHROMA_BASE = [
    17, 18, 24, 47, 99, 99, 99, 99,
    18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
]


def _libjpeg_table(base, quality):
    quality = max(1, min(100, quality))
    scale = 5000 // quality if quality < 50 else 200 - quality * 2
    return [max(1, min(255, (b * scale + 50) // 100)) for b in base]


def _zigzag_to_natural(tbl):
    order = [0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5,
             12, 19, 26, 33, 40, 48, 41, 34, 27, 20, 13, 6, 7, 14, 21, 28,
             35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51,
             58, 59, 52, 45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63]
    out = [0] * 64
    for i, v in enumerate(tbl[:64]):
        out[order[i]] = v
    return out


def _parse_jpeg(path):
    """遍历 JPEG 段，提取量化表、Huffman 表、APP 段信息。"""
    with open(path, "rb") as fp:
        data = fp.read()
    info = {"quant_tables": [], "huffman_tables": 0, "app_markers": {},
            "comment": None, "size": len(data), "raw": data[:0]}
    if not data[:2] == b"\xff\xd8":
        return None
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xDA:  # SOS：之后是压缩数据，停止解析
            break
        if marker == 0xD9:
            break
        seglen = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        seg = data[pos + 4:pos + 2 + seglen]
        if marker == 0xDB:  # DQT
            off = 0
            while off < len(seg):
                pq_tq = seg[off]
                pq, _tq = pq_tq >> 4, pq_tq & 0x0F
                off += 1
                n = 128 if pq else 64
                vals = list(seg[off:off + n])
                if pq:
                    vals = [struct.unpack(">H", bytes(vals[i:i + 2]))[0]
                            for i in range(0, len(vals) - 1, 2)]
                off += n
                info["quant_tables"].append(_zigzag_to_natural(vals[:64]))
        elif marker == 0xC4:  # DHT
            info["huffman_tables"] += 1
        elif marker == 0xFE:  # COM
            try:
                info["comment"] = seg.decode("utf-8", "ignore").strip("\x00 ")
            except Exception:
                pass
        elif 0xE0 <= marker <= 0xEF:  # APPn
            name = f"APP{marker - 0xE0}"
            head = seg[:32]
            info["app_markers"].setdefault(name, [])
            info["app_markers"][name].append(head)
        pos += 2 + seglen
    return info


def _fingerprint_encoder(quant_tables):
    """把量化表与 libjpeg 标准表比对，判断编码器风格与估计质量。"""
    if not quant_tables:
        return {"style": "unknown", "est_quality": None}
    luma = quant_tables[0]
    best_q, best_diff = None, 1 << 60
    for q in range(50, 101):
        std = _libjpeg_table(_LUMA_BASE, q)
        diff = sum((a - b) ** 2 for a, b in zip(luma, std))
        if diff < best_diff:
            best_diff, best_q = diff, q
    if best_diff == 0:
        return {"style": "libjpeg_standard", "est_quality": best_q}
    # Photoshop 等知名软件有自己的表，这里统一归为 custom
    return {"style": "custom", "est_quality": None,
            "closest_libjpeg_q": best_q, "table_distance": int(best_diff)}


def _extract_metadata_text(path):
    """只提取元数据区域的文本（EXIF/XMP/PNG文本块/JPEG APP与COM段），
    避免在压缩图像数据里误匹配关键词。"""
    texts = []
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fp:
        data = fp.read()
    if ext in (".jpg", ".jpeg") and data[:2] == b"\xff\xd8":
        pos = 2
        while pos + 4 <= len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pos += 2
                continue
            if marker in (0xDA, 0xD9):
                break
            seglen = struct.unpack(">H", data[pos + 2:pos + 4])[0]
            seg = data[pos + 4:pos + 2 + seglen]
            if 0xE0 <= marker <= 0xEF or marker == 0xFE:  # APPn / COM
                texts.append(seg.decode("latin-1", "ignore"))
            pos += 2 + seglen
    elif ext == ".png":
        pos = 8
        while pos + 12 <= len(data):
            length = struct.unpack(">I", data[pos:pos + 4])[0]
            ctype = data[pos + 4:pos + 8]
            chunk = data[pos + 8:pos + 8 + length]
            if ctype in (b"tEXt", b"iTXt", b"zTXt"):
                texts.append(chunk.decode("latin-1", "ignore"))
            pos += 12 + length
            if ctype == b"IEND":
                break
    return "\n".join(texts)


def _scan_c2pa(path):
    """字节级扫描 C2PA/JUMBF 凭证；生成器字符串只在元数据文本中匹配。"""
    with open(path, "rb") as fp:
        data = fp.read()
    hits = {"c2pa_manifest": False, "generator_strings": [], "xmp_hints": []}
    if b"jumbf" in data or b"c2pa.manifest" in data or b"urn:c2pa" in data:
        hits["c2pa_manifest"] = True
    text = _extract_metadata_text(path)
    if not text.strip():
        return hits
    for pat in [r"Adobe Firefly", r"DALL[·\u00b7-]?E[\s\-]?[23]?", r"\bMidjourney\b",
                r"Stable[ \-]?Diffusion", r"GPT-4o", r"\bImagen\b", r"\bcomfyui\b",
                r"\bnovelai\b", r"\bdiffusion\b"]:
        for m in re.finditer(pat, text, re.IGNORECASE):
            s = m.group(0)
            if s not in hits["generator_strings"]:
                hits["generator_strings"].append(s)
    for pat in [r"photoshop", r"\bGIMP\b", r"Lightroom", r"Topaz", r"Canva"]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            hits["xmp_hints"].append(m.group(0))
    return hits


def _exif_summary(pil):
    out = {"make": None, "model": None, "software": None, "datetime": None,
           "lens": None, "has_gps": False, "tags_count": 0}
    try:
        exif = pil.getexif()
        out["tags_count"] = len(exif)
        if not exif:
            return out
        out["make"] = exif.get(271)
        out["model"] = exif.get(272)
        out["software"] = exif.get(305)
        out["datetime"] = exif.get(306) or exif.get(36867)
        try:
            ifd = exif.get_ifd(0x8769)
            out["datetime"] = out["datetime"] or ifd.get(36867)
            out["lens"] = ifd.get(42036)
        except Exception:
            pass
        try:
            out["has_gps"] = bool(exif.get_ifd(0x8825))
        except Exception:
            pass
    except Exception:
        pass
    return out


def _thumbnail_check(pil):
    """EXIF 内嵌缩略图与主图大致比对（均值色差异）。"""
    try:
        exif = pil.getexif()
        thumb = exif.get_thumbnail()
        if thumb is None or thumb[0] is None:
            return {"present": False}
        t = Image.open(io.BytesIO(thumb[1])).convert("RGB").resize((64, 64))
        main = pil.convert("RGB").resize((64, 64))
        diff = float(np.abs(np.array(t, float) - np.array(main, float)).mean())
        return {"present": True, "mean_diff": round(diff, 2)}
    except Exception:
        return {"present": False}


def analyze(path, pil, arr, config=None):
    findings, metrics = [], {}
    ext = os.path.splitext(path)[1].lower()
    exif = _exif_summary(pil)
    metrics["exif"] = exif

    # ---- 相机信息 ----
    has_camera = bool(exif["make"] or exif["model"])
    if has_camera:
        findings.append(finding("info", "CAMERA_INFO",
                                f"含相机信息：{exif['make'] or ''} {exif['model'] or ''}".strip()))
    else:
        findings.append(finding("low", "NO_CAMERA_EXIF",
                                "无相机 EXIF 信息（截图、AI 图或转发图常见，单独不能定论）"))

    if exif["software"]:
        sw = str(exif["software"])
        findings.append(finding("medium", "SOFTWARE_TAG",
                                f"EXIF 含软件处理标签：{sw}",
                                {"software": sw}))

    # ---- JPEG 专项 ----
    fp_style = {"style": "n/a"}
    if ext in (".jpg", ".jpeg"):
        jpeg = _parse_jpeg(path)
        if jpeg:
            fp_style = _fingerprint_encoder(jpeg["quant_tables"])
            metrics["encoder"] = fp_style
            metrics["quant_table_count"] = len(jpeg["quant_tables"])
            if jpeg["comment"]:
                findings.append(finding("info", "JPEG_COMMENT",
                                        f"JPEG Comment 字段：{jpeg['comment'][:120]}"))
            if fp_style["style"] == "libjpeg_standard":
                msg = (f"量化表为标准 libjpeg 风格（估计质量 q≈{fp_style['est_quality']}），"
                       "典型于软件重新编码/转发保存")
                if has_camera:
                    # 声称相机拍摄但量化表是软件风格 → 矛盾
                    findings.append(finding("high", "ENCODER_MISMATCH", msg + 
                                            "，与 EXIF 中的相机信息矛盾——文件被软件重新编码过",
                                            fp_style))
                else:
                    findings.append(finding("low", "LIBJPEG_TABLES", msg, fp_style))
            elif fp_style["style"] == "custom":
                findings.append(finding("info", "CUSTOM_TABLES",
                                        "量化表为非标自定义风格（相机直出或专用编码器常见）"))

            thumb = _thumbnail_check(pil)
            metrics["thumbnail"] = thumb
            if thumb.get("present") and thumb.get("mean_diff", 0) > 12:
                findings.append(finding("medium", "THUMBNAIL_INCONSISTENT",
                                        f"EXIF 内嵌缩略图与主图差异明显（均值差 {thumb['mean_diff']}），"
                                        "可能只更新了主图未更新缩略图", thumb))

    elif ext == ".png":
        findings.append(finding("info", "PNG_FORMAT",
                                "PNG 格式无 JPEG 编码指纹可查（截图与 AI 导出常用 PNG）"))

    # ---- C2PA / 生成器字符串 ----
    c2pa = _scan_c2pa(path)
    metrics["c2pa"] = {"manifest": c2pa["c2pa_manifest"],
                       "generators": c2pa["generator_strings"]}
    if c2pa["c2pa_manifest"]:
        findings.append(finding("high", "C2PA_MANIFEST",
                                "检测到 C2PA 内容凭证清单，建议用 contentcredentials.org/verify 查验签名与编辑历史"))
    if c2pa["generator_strings"]:
        gens = ", ".join(c2pa["generator_strings"])
        code = "C2PA_AI_CLAIM" if c2pa["c2pa_manifest"] else "GENERATOR_STRING"
        sev = "high" if c2pa["c2pa_manifest"] else "medium"
        findings.append(finding(sev, code,
                                f"文件内发现 AI 生成器相关字符串：{gens}",
                                {"strings": c2pa["generator_strings"]}))

    # ---- 文件质量评级 ----
    if has_camera and fp_style.get("style") == "custom":
        grade = "original"
    elif has_camera and fp_style.get("style") == "libjpeg_standard":
        grade = "transcoded"
    elif not has_camera and (ext == ".png" or fp_style.get("style") == "libjpeg_standard"):
        grade = "screenshot_like"
    else:
        grade = "unknown"
    quality = {"grade": grade, "detail": {
        "has_camera_exif": has_camera, "encoder_style": fp_style.get("style"),
        "software": exif["software"], "ext": ext}}
    metrics["file_quality"] = quality

    return module_result("filemeta", findings=findings, metrics=metrics), quality
