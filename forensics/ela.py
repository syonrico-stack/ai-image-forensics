"""模块 2：ELA 误差水平分析

原理：把图片以固定 JPEG 质量重新保存，比较与原图的差异。
被二次编辑/合成的区域，其重压缩误差水平与周围不一致。
注意：对 PNG、截图、多次转码图可信度下降（结论引擎会结合文件质量评级）。
"""
import io

import numpy as np
from PIL import Image

from .common import (finding, make_heatmap_overlay, module_result,
                     resize_for_analysis)

BLOCK = 32


def _ela_map(pil, quality):
    buf = io.BytesIO()
    pil.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    resaved = np.array(Image.open(buf).convert("RGB"), dtype=np.float32)
    orig = np.array(pil.convert("RGB"), dtype=np.float32)
    diff = np.abs(orig - resaved).max(axis=2)
    return diff


def analyze(path, pil, arr, config=None):
    findings, artifacts, metrics = [], {}, {}
    small, scale = resize_for_analysis(arr)
    pil_small = Image.fromarray(small)

    # 经典做法：以高质量（95）重存，差异揭示原图的压缩历史
    diff = _ela_map(pil_small, quality=95)
    h, w = diff.shape
    bh, bw = max(1, h // BLOCK), max(1, w // BLOCK)
    blocks = diff[: bh * BLOCK, : bw * BLOCK].reshape(bh, BLOCK, bw, BLOCK)
    block_mean = blocks.mean(axis=(1, 3))

    global_mean = float(block_mean.mean())
    global_std = float(block_mean.std())
    hot_mask = block_mean > (global_mean + 3 * max(global_std, 0.15))
    hot_ratio = float(hot_mask.mean())
    max_block = float(block_mean.max())

    metrics.update({
        "global_mean": round(global_mean, 3),
        "block_std": round(global_std, 3),
        "max_block_mean": round(max_block, 3),
        "hot_block_ratio": round(hot_ratio, 4),
    })

    # 归一化热力图（0~1）
    denom = max(max_block - global_mean, 1e-6)
    score_map = np.clip((block_mean - global_mean) / denom, 0, 1)
    overlay, _ = make_heatmap_overlay(small, score_map)
    artifacts["ela_heatmap"] = overlay

    # 判定：存在显著局部高误差区（排除整图均匀偏高，那只是质量差）
    significant_hot = int(hot_mask.sum())
    if (significant_hot >= 2 and hot_ratio < 0.25
            and max_block > max(global_mean * 1.6, 1.0)):
        # 找出热点位置描述
        ys, xs = np.where(hot_mask)
        pos = f"约 ({int(xs.mean() / bw * 100)}%, {int(ys.mean() / bh * 100)}%) 区域（宽高百分比）"
        findings.append(finding(
            "medium", "ELA_STRONG_REGIONS",
            f"ELA 发现 {significant_hot} 个局部高误差区块（集中于{pos}），"
            "与全图背景水平差异显著，可能存在局部编辑/合成",
            {"hot_blocks": significant_hot, "position": pos,
             "global_mean": round(global_mean, 2), "max_block": round(max_block, 2)}))
    elif global_mean < 0.8:
        findings.append(finding("info", "ELA_LOW_SIGNAL",
                                "ELA 全图信号极低——该图可能不是 JPEG 直出（PNG 或多次压缩），ELA 结论参考价值低"))
    else:
        findings.append(finding("info", "ELA_NORMAL",
                                "ELA 未发现异常局部高误差区域"))

    return module_result("ela", findings=findings, artifacts=artifacts, metrics=metrics)
