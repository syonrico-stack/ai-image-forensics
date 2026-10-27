"""管线编排：按序执行各取证模块，汇总结论，生成报告。

每个模块独立隔离：单个模块异常只标记 error，绝不中断整体分析。
"""
import datetime
import hashlib
import os
import traceback
import uuid

from . import (clone_detect, ela, fft_analysis, filemeta, noise_analysis,
               online_detectors, watermark)
from .common import img_to_base64, load_image, module_result
from .verdict import grade

MODULES = [
    ("filemeta", filemeta.analyze),
    ("watermark", watermark.analyze),
    ("ela", ela.analyze),
    ("fft", fft_analysis.analyze),
    ("noise", noise_analysis.analyze),
    ("clone", clone_detect.analyze),
    ("online", online_detectors.analyze),
]

MANUAL_CHECKLIST = [
    "用 Google SynthID Detector / Gemini 应用检查 Google 系模型水印（仅覆盖 Google 系）",
    "用 Google Lens / TinEye 反向搜图，寻找更早的原始出处",
    "若检出 C2PA 凭证，到 contentcredentials.org/verify 验证签名与编辑历史",
    "重要结论请保留原图与本报告，必要时送人工专家复核",
]


def analyze_image(path, config=None, keep_artifacts=True):
    """分析单张图片，返回完整报告 dict。"""
    report_id = uuid.uuid4().hex[:12]
    with open(path, "rb") as fp:
        sha256 = hashlib.sha256(fp.read()).hexdigest()

    arr, pil = load_image(path)
    file_quality = {"grade": "unknown"}
    results = []
    for name, fn in MODULES:
        # 把文件质量评级传给后续模块（噪声等模块据此调整置信度）
        ctx = dict(config or {})
        ctx["file_quality"] = file_quality.get("grade", "unknown")
        try:
            out = fn(path, pil, arr, ctx)
            if isinstance(out, tuple):  # filemeta 额外返回文件质量评级
                out, file_quality = out
            results.append(out)
        except Exception as e:
            results.append(module_result(
                name, status="error",
                note=f"模块执行异常：{e.__class__.__name__}: {e}",
                metrics={"traceback": traceback.format_exc()[-500:]}))

    verdict = grade(results, file_quality)

    # 收集可视化产物（转 base64 供前端展示），并从模块结果中移除原始数组以便 JSON 序列化
    artifacts = {}
    for res in results:
        raw = res.get("artifacts", {})
        for k, v in raw.items():
            if keep_artifacts:
                artifacts[k] = img_to_base64(v, "JPEG")
        res["artifacts"] = list(raw.keys())   # 只保留键名
    if keep_artifacts:
        artifacts = {"original": img_to_base64(arr, "JPEG"), **artifacts}

    return {
        "id": report_id,
        "file": os.path.basename(path),
        "sha256": sha256,
        "size": {"width": int(arr.shape[1]), "height": int(arr.shape[0])},
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "file_quality": file_quality,
        "verdict": verdict,
        "modules": results,
        "artifacts": artifacts,
        "manual_checklist": MANUAL_CHECKLIST,
    }


def summarize_batch(reports):
    """批量汇总 + 工具指纹聚类：同一批图里共享可疑编码指纹的标记出来。"""
    rows = []
    fingerprint_groups = {}
    for r in reports:
        meta = next((m for m in r["modules"] if m["module"] == "filemeta"), {})
        fm = meta.get("metrics", {})
        enc = fm.get("encoder", {})
        fp_key = None
        if enc.get("style") == "libjpeg_standard":
            fp_key = f"libjpeg_q{enc.get('est_quality')}"
        elif enc.get("style") == "custom":
            fp_key = "custom_tables"
        if fp_key:
            fingerprint_groups.setdefault(fp_key, []).append(r["file"])
        rows.append({
            "file": r["file"],
            "tier": r["verdict"]["tier"],
            "title": r["verdict"]["title"],
            "ai_score": r["verdict"]["ai_score"],
            "reprocess_score": r["verdict"]["reprocess_score"],
            "quality": r["file_quality"]["grade"],
            "encoder": fp_key,
        })
    clusters = {k: v for k, v in fingerprint_groups.items()
                if len(v) >= 2 and k != "custom_tables"}
    return {"rows": rows, "fingerprint_clusters": clusters}
