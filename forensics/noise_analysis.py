"""模块 4：噪声残差分析

原理：真实相机噪声是"传感器模式噪声"——空间分布与场景亮度相关、
不同区域强度有自然起伏。软件注入的噪声（洗图工具常用手法）通常：
  - 全场强度均匀（与亮度无关）
  - 分布接近完美高斯
输出噪声强度热力图 + 均匀性/亮度相关性指标。
"""
import cv2
import numpy as np
from scipy import stats as sstats

from .common import finding, make_heatmap_overlay, module_result, resize_for_analysis

BLOCK = 24
# 经验阈值（测试集校准后调整）
UNIFORM_CV_THRESH = 0.18      # 块噪声强度的变异系数低于此值 → 异常均匀
LUM_CORR_MIN = 0.05           # 噪声强度与亮度的相关性低于此值 → 与场景无关


def analyze(path, pil, arr, config=None):
    findings, artifacts, metrics = [], {}, {}
    small, _ = resize_for_analysis(arr, 768)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)

    # 估计噪声残差：原图 - 非局部均值去噪（保留纹理的估计较准）
    denoised = cv2.fastNlMeansDenoising(gray.astype(np.uint8), None, 8, 7, 21).astype(np.float32)
    residual = gray - denoised

    h, w = gray.shape
    bh, bw = h // BLOCK, w // BLOCK
    if bh < 4 or bw < 4:
        return module_result("noise", status="skipped",
                             note="图片太小，无法进行噪声分析",
                             findings=[finding("info", "NOISE_SKIPPED", "图片尺寸过小")])
    res_blocks = residual[: bh * BLOCK, : bw * BLOCK].reshape(bh, BLOCK, bw, BLOCK)
    lum_blocks = gray[: bh * BLOCK, : bw * BLOCK].reshape(bh, BLOCK, bw, BLOCK)
    block_std = res_blocks.std(axis=(1, 3))
    block_lum = lum_blocks.mean(axis=(1, 3))
    # 用块内亮度梯度排除强纹理/边缘块（那里残差主要是去噪误差而非噪声）
    gx = np.abs(np.diff(lum_blocks, axis=3)).mean(axis=(1, 2, 3)) \
        + np.abs(np.diff(lum_blocks, axis=2)).mean(axis=(1, 2, 3))
    flat_mask = gx < np.percentile(gx, 50)  # 取较平的一半块

    flat_std = block_std[flat_mask]
    flat_lum = block_lum[flat_mask]
    if flat_std.size < 20:
        return module_result("noise", status="skipped",
                             note="平坦区域不足，噪声分析不可靠",
                             findings=[finding("info", "NOISE_SKIPPED", "平坦区域不足")])

    mean_std = float(flat_std.mean())
    cv_of_std = float(flat_std.std() / max(mean_std, 1e-6))
    lum_corr = float(np.corrcoef(flat_lum, flat_std)[0, 1])
    res_kurt = float(sstats.kurtosis(residual.ravel(), fisher=True))

    # 亮/暗区域噪声强度比：真实传感器噪声随亮度变化明显（比值远离 1）；
    # 叠加均匀注入噪声后，亮暗区域的噪声强度趋同（比值接近 1）
    dark_mask = flat_lum < np.percentile(flat_lum, 30)
    bright_mask = flat_lum > np.percentile(flat_lum, 70)
    std_dark = float(flat_std[dark_mask].mean()) if dark_mask.sum() >= 5 else None
    std_bright = float(flat_std[bright_mask].mean()) if bright_mask.sum() >= 5 else None
    lum_ratio = (std_bright / std_dark) if (std_dark and std_bright) else None

    metrics.update({
        "noise_mean": round(mean_std, 3),
        "uniformity_cv": round(cv_of_std, 3),
        "luminance_corr": round(lum_corr, 3),
        "bright_dark_ratio": round(lum_ratio, 3) if lum_ratio else None,
        "residual_kurtosis": round(res_kurt, 2),
        "flat_blocks": int(flat_std.size),
    })

    # 热力图：块噪声强度
    norm = block_std / max(block_std.max(), 1e-6)
    overlay, _ = make_heatmap_overlay(small, norm)
    artifacts["noise_heatmap"] = overlay

    # 判定：空间均匀 + 亮暗区域噪声趋同 → 疑似人工注入噪声
    # 注意：多次转发/压缩也会抹匀噪声，因此文件质量差时降级为低严重度
    file_quality = (config or {}).get("file_quality", "unknown")
    if file_quality == "phone_original":
        # 手机计算摄影（多帧降噪/HDR 合成）天然会抹匀噪声，属正常修饰，不作为证据
        findings.append(finding(
            "info", "NOISE_PHONE_NORMAL",
            f"噪声分布均匀（CV={cv_of_std:.2f}）符合手机计算摄影（多帧降噪）特征，属正常修饰，不作为处理证据"))
        # 继续输出热力图后直接返回
        norm = block_std / max(block_std.max(), 1e-6)
        overlay, _ = make_heatmap_overlay(small, norm)
        artifacts["noise_heatmap"] = overlay
        return module_result("noise", findings=findings, artifacts=artifacts, metrics=metrics)
    quality_ok = file_quality in ("original", "unknown")
    ratio_flat = lum_ratio is not None and 0.85 < lum_ratio < 1.15
    if cv_of_std < UNIFORM_CV_THRESH and ratio_flat and mean_std > 1.5:
        sev = "medium" if quality_ok else "low"
        suffix = "" if quality_ok else "（但文件经过多次转码，也可能是压缩抹平了噪声，证据强度下调）"
        findings.append(finding(
            sev, "NOISE_UNIFORM",
            f"噪声空间分布异常均匀（变异系数 {cv_of_std:.2f} < {UNIFORM_CV_THRESH}）"
            f"且亮暗区域噪声强度趋同（比值 {lum_ratio:.2f}≈1），"
            "符合软件注入噪声/整图再处理特征，不符合传感器噪声模式" + suffix,
            metrics))
    elif cv_of_std < UNIFORM_CV_THRESH * 0.7 and mean_std > 1.5:
        findings.append(finding(
            "low", "NOISE_VERY_UNIFORM",
            f"噪声分布高度均匀（CV={cv_of_std:.2f}），但绝对强度较低或亮暗差异尚存，"
            "也可能是重度压缩导致，证据强度有限", metrics))
    else:
        ratio_txt = f"，亮暗噪声比={lum_ratio:.2f}" if lum_ratio else ""
        findings.append(finding("info", "NOISE_PLAUSIBLE",
                                f"噪声分布未见明显异常（CV={cv_of_std:.2f}{ratio_txt}）"))

    return module_result("noise", findings=findings, artifacts=artifacts, metrics=metrics)
