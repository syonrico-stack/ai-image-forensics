"""公共工具：图像加载、可视化、编码等。"""
import base64
import io
import os

import cv2
import numpy as np
from PIL import Image

# 分析时统一的最大边长（控制计算量）
MAX_ANALYSIS_DIM = 1600


def load_image(path):
    """加载图片为 RGB numpy 数组，并做 EXIF 方向校正。返回 (rgb_array, pil_image)。"""
    pil = Image.open(path)
    try:
        from PIL import ImageOps
        pil = ImageOps.exif_transpose(pil)
    except Exception:
        pass
    pil = pil.convert("RGB")
    arr = np.array(pil)
    return arr, pil


def resize_for_analysis(arr, max_dim=MAX_ANALYSIS_DIM):
    """等比缩小到分析尺寸，返回 (缩小后的图, 缩放比例)。"""
    h, w = arr.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return arr, scale


def img_to_base64(arr_or_pil, fmt="PNG", quality=88):
    """图像转 base64 data URL，用于网页展示。"""
    if isinstance(arr_or_pil, np.ndarray):
        pil = Image.fromarray(arr_or_pil)
    else:
        pil = arr_or_pil
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        pil.save(buf, format="JPEG", quality=quality)
        mime = "image/jpeg"
    else:
        pil.save(buf, format="PNG")
        mime = "image/png"
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def make_heatmap_overlay(gray_img_rgb, score_map, colormap=cv2.COLORMAP_JET, alpha=0.55):
    """把 0~1 的分数图以伪彩色叠加到原图上。score_map 可为任意尺寸，内部会缩放对齐。"""
    h, w = gray_img_rgb.shape[:2]
    sm = cv2.resize(score_map.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
    sm = np.clip(sm, 0, 1)
    heat = cv2.applyColorMap((sm * 255).astype(np.uint8), colormap)
    heat = cv2.cvtColor(heat, cv2.COLOR_BGR2RGB)
    overlay = cv2.addWeighted(gray_img_rgb, 1 - alpha, heat, alpha, 0)
    return overlay, sm


def gray_residual_stats(residual, block=32):
    """把残差图分块，返回每块均值图与标准差图（用于均匀性分析和热力图）。"""
    h, w = residual.shape[:2]
    bh, bw = h // block, w // block
    if bh < 2 or bw < 2:
        return None, None
    cropped = residual[: bh * block, : bw * block]
    blocks = cropped.reshape(bh, block, bw, block)
    means = blocks.mean(axis=(1, 3))
    stds = blocks.std(axis=(1, 3))
    return means, stds


def finding(severity, code, message, detail=None):
    return {"severity": severity, "code": code, "message": message, "detail": detail or {}}


def module_result(name, status="ok", findings=None, artifacts=None, metrics=None, note=None):
    return {
        "module": name,
        "status": status,
        "findings": findings or [],
        "artifacts": artifacts or {},
        "metrics": metrics or {},
        "note": note,
    }
