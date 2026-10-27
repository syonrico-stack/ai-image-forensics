"""模块 3：FFT 频谱分析

- 高频能量比（HF ratio）：人工加噪、AI 放大、过度锐化会显著抬高
- 孤立亮峰检测：周期性人工操作（重采样网格、频域伪装）会在频谱留下尖峰
- 输出对数频谱可视化图
"""
import cv2
import numpy as np

from .common import finding, module_result, resize_for_analysis

# 经验阈值（基于 512px 灰度图，后续按测试集校准）
HF_RATIO_SUSPICIOUS = 0.080   # 高频能量占比明显偏高（保守阈值，避免噪声图误报）
PEAK_Z_THRESH = 12.0          # 径向剖面上的孤立峰 z-score 阈值


def analyze(path, pil, arr, config=None):
    findings, artifacts, metrics = [], {}, {}
    small, _ = resize_for_analysis(arr, 768)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # 去趋势：减去高斯模糊背景，避免内容边缘主导频谱
    trend = cv2.GaussianBlur(gray, (0, 0), 8)
    resid = gray - trend

    f = np.fft.fftshift(np.fft.fft2(resid))
    mag = np.abs(f)
    log_mag = np.log1p(mag)
    artifacts["fft_spectrum"] = cv2.normalize(log_mag, None, 0, 255,
                                              cv2.NORM_MINMAX).astype(np.uint8)

    h, w = mag.shape
    cy, cx = h // 2, w // 2
    y, x = np.indices(mag.shape)
    r = np.sqrt((y - cy) ** 2 + (x - cx) ** 2)
    r_max = min(cy, cx)

    # 高频能量比：r > 0.7*r_max 的能量 / 总能量
    hf_mask = r > 0.7 * r_max
    hf_ratio = float(mag[hf_mask].sum() / max(mag.sum(), 1e-9))
    metrics["hf_ratio"] = round(hf_ratio, 5)

    # 径向剖面孤立峰
    ring = r.astype(int)
    ring = np.clip(ring, 0, int(r.max()))
    radial_sum = np.bincount(ring.ravel(), mag.ravel())
    radial_cnt = np.bincount(ring.ravel())
    radial_mean = radial_sum / np.maximum(radial_cnt, 1)
    # 中值滤波作为局部基线，找突起的尖峰
    from scipy.ndimage import median_filter
    baseline = median_filter(radial_mean, size=9)
    resid_profile = radial_mean - baseline
    sigma = resid_profile.std() or 1e-9
    z = resid_profile / sigma
    peak_idx = np.where((z > PEAK_Z_THRESH) &
                        (np.arange(len(z)) > 10) &
                        (np.arange(len(z)) < r_max))[0]
    # 排除 DC 附近与奈奎斯特边缘
    peak_count = int(len(peak_idx))
    metrics["spectral_peaks"] = peak_count
    metrics["peak_max_z"] = round(float(z.max()), 2)

    if hf_ratio > HF_RATIO_SUSPICIOUS:
        findings.append(finding(
            "low", "FFT_HF_ANOMALY",
            f"频谱高频能量占比偏高（{hf_ratio:.2%}），可能指向人工加噪、AI 放大或过度锐化"
            "（强噪声的真实照片也会偏高，需结合噪声分析模块交叉判断）",
            {"hf_ratio": round(hf_ratio, 5)}))
    if peak_count >= 2:
        findings.append(finding(
            "medium", "FFT_SPECTRAL_PEAKS",
            f"频谱径向剖面发现 {peak_count} 个孤立亮峰（z>{PEAK_Z_THRESH:.0f}），"
            "提示存在周期性人工操作（重采样/频域处理）",
            {"peaks": peak_count, "max_z": round(float(z.max()), 1)}))
    if not findings:
        findings.append(finding("info", "FFT_NORMAL", "频谱未见明显异常"))

    return module_result("fft", findings=findings, artifacts=artifacts, metrics=metrics)
