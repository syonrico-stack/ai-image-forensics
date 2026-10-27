"""模块 6：在线检测接口层 + 变换稳定性测试

设计原则：
- 全部可插拔：配置了哪个 Key 就启用哪个；全部不可用则整体跳过，不影响其他模块
- 优雅降级：网络失败/限流只记 note，绝不中断分析
- 稳定性测试：对图片做重压缩+缩放变换后重跑检测器，结果剧烈翻转 → 疑似对抗扰动

支持来源：
- HuggingFace Inference API（开源模型，免费额度，可用 HF_TOKEN 提额；
  国内网络可通过环境变量 HF_ENDPOINT=https://hf-mirror.com 走镜像）
- Sightengine（api_user/api_secret，免费额度）
- Hive Moderation（api_key，免费试用）
"""
import base64
import io
import json
import os
import urllib.request
import urllib.error

import numpy as np
from PIL import Image

from .common import finding, module_result

TIMEOUT = 30

DEFAULT_HF_MODELS = [
    "Organika/sdxl-detector",
    "umm-maybe/AI-image-detector",
]

# 各来源返回中"表示 AI"的标签关键词
AI_LABEL_HINTS = ("ai", "artificial", "fake", "generated", "sdxl", "deepfake")
REAL_LABEL_HINTS = ("real", "human", "natural", "authentic", "original")


def _post(url, data=None, headers=None, json_body=None, files=None, fields=None):
    req_headers = headers or {}
    body = None
    if files or fields:
        boundary = "----forensicsboundary"
        parts = []
        for k, v in (fields or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        for k, (fname, blob, mime) in (files or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fname}\"\r\nContent-Type: {mime}\r\n\r\n".encode()
                         + blob + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        req_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif json_body is not None:
        body = json.dumps(json_body).encode()
        req_headers["Content-Type"] = "application/json"
    elif data is not None:
        body = data
        req_headers.setdefault("Content-Type", "application/octet-stream")
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def _jpeg_bytes(pil, quality=92):
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _hf_detect(img_bytes, model, endpoint, token):
    url = f"{endpoint.rstrip('/')}/models/{model}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    res = _post(url, data=img_bytes, headers=headers)
    if isinstance(res, dict) and res.get("error"):
        raise RuntimeError(str(res["error"])[:120])
    # 返回 [{label, score}, ...]
    best = max(res, key=lambda r: r.get("score", 0))
    label, score = str(best.get("label", "")).lower(), float(best.get("score", 0))
    if any(h in label for h in AI_LABEL_HINTS):
        ai_prob = score
    elif any(h in label for h in REAL_LABEL_HINTS):
        ai_prob = 1 - score
    else:
        ai_prob = score if score > 0.5 else None
    return ai_prob, f"{model.split('/')[-1]}: {best.get('label')} {score:.2f}"


def _sightengine_detect(img_bytes, user, secret):
    res = _post("https://api.sightengine.com/1.0/check.json",
                files={"media": ("image.jpg", img_bytes, "image/jpeg")},
                fields={"models": "genai", "api_user": user, "api_secret": secret})
    if res.get("status") != "success":
        raise RuntimeError(str(res.get("error"))[:120])
    ai_prob = float(res["type"]["ai_generated"])
    return ai_prob, f"sightengine: ai_generated={ai_prob:.2f}"


def _hive_detect(img_bytes, api_key):
    res = _post("https://api.thehive.ai/api/v2/task/sync",
                headers={"Authorization": f"token {api_key}"},
                json_body={"media": f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode()}"})
    classes = res["status"][0]["response"]["output"][0]["classes"]
    ai_prob = 0.0
    for c in classes:
        name = str(c.get("class", "")).lower()
        if any(h in name for h in AI_LABEL_HINTS):
            ai_prob = max(ai_prob, float(c.get("score", 0)))
    return ai_prob, f"hive: ai={ai_prob:.2f}"


def _run_all_detectors(img_bytes, cfg):
    """跑所有已配置的检测器，返回 [(source, ai_prob, desc, error), ...]"""
    results = []
    token = cfg.get("HF_TOKEN") or ""
    endpoint = cfg.get("HF_ENDPOINT") or "https://api-inference.huggingface.co"
    models = cfg.get("HF_MODELS") or DEFAULT_HF_MODELS
    if cfg.get("ENABLE_HF", "1") == "1":
        for m in models:
            try:
                p, d = _hf_detect(img_bytes, m, endpoint, token)
                results.append(("hf", p, d, None))
            except Exception as e:
                results.append(("hf", None, m, str(e)[:100]))
    if cfg.get("SIGHTENGINE_USER") and cfg.get("SIGHTENGINE_SECRET"):
        try:
            p, d = _sightengine_detect(img_bytes, cfg["SIGHTENGINE_USER"], cfg["SIGHTENGINE_SECRET"])
            results.append(("sightengine", p, d, None))
        except Exception as e:
            results.append(("sightengine", None, "sightengine", str(e)[:100]))
    if cfg.get("HIVE_API_KEY"):
        try:
            p, d = _hive_detect(img_bytes, cfg["HIVE_API_KEY"])
            results.append(("hive", p, d, None))
        except Exception as e:
            results.append(("hive", None, "hive", str(e)[:100]))
    return results


def _vote(results, thresh=0.7):
    valid = [(s, p, d) for s, p, d, e in results if p is not None]
    if not valid:
        return None, valid
    votes_ai = sum(1 for _, p, _ in valid if p >= thresh)
    avg = float(np.mean([p for _, p, _ in valid]))
    return {"votes_ai": votes_ai, "votes_total": len(valid), "avg_ai_prob": round(avg, 3)}, valid


def _transform(pil):
    """稳定性测试用的温和变换：JPEG q85 重压缩 + 缩放到 90% 再还原。"""
    w, h = pil.size
    small = pil.resize((int(w * 0.9), int(h * 0.9)), Image.LANCZOS)
    buf = io.BytesIO()
    small.convert("RGB").save(buf, "JPEG", quality=85)
    buf.seek(0)
    out = Image.open(buf).convert("RGB").resize((w, h), Image.LANCZOS)
    return out


def analyze(path, pil, arr, config=None):
    cfg = {**{k: v for k, v in os.environ.items()},
           **(config or {})}
    findings, metrics = [], {}
    img_bytes = _jpeg_bytes(pil)

    results = _run_all_detectors(img_bytes, cfg)
    errors = [f"{src}: {err}" for src, _, _, err in results if err]
    vote, valid = _vote(results)
    metrics["detectors"] = [{"source": s, "desc": d, "error": e}
                            for s, _, d, e in results]

    if not valid:
        note = "未配置任何可用的在线检测器，或全部请求失败。"
        if errors:
            note += " 失败详情：" + "；".join(errors)
        note += "（可在 .env 中配置 HF_TOKEN / Sightengine / Hive 后启用；国内网络建议设置 HF_ENDPOINT=https://hf-mirror.com）"
        return module_result("online", status="skipped", note=note,
                             findings=[finding("info", "ONLINE_SKIPPED", "在线检测层未启用")],
                             metrics=metrics)

    metrics["vote"] = vote
    descs = "；".join(d for _, _, d in valid)
    if vote["votes_ai"] >= 2 or (vote["votes_total"] == 1 and vote["avg_ai_prob"] >= 0.9):
        findings.append(finding(
            "high", "ONLINE_CONSENSUS_AI",
            f"在线检测器投票判定为 AI 生成（{vote['votes_ai']}/{vote['votes_total']} 票，"
            f"平均 AI 概率 {vote['avg_ai_prob']:.0%}）。明细：{descs}",
            vote))
    elif vote["avg_ai_prob"] >= 0.7:
        findings.append(finding(
            "medium", "ONLINE_DETECTOR_HIGH",
            f"在线检测器倾向 AI（平均概率 {vote['avg_ai_prob']:.0%}，未达多数票）。明细：{descs}",
            vote))
    else:
        findings.append(finding(
            "info", "ONLINE_LEAN_REAL",
            f"在线检测器倾向真实（平均 AI 概率 {vote['avg_ai_prob']:.0%}）。明细：{descs}"))

    # ---- 变换稳定性测试（至少 1 个检测器可用才做）----
    t_bytes = _jpeg_bytes(_transform(pil))
    t_results = _run_all_detectors(t_bytes, cfg)
    t_valid = [(s, p) for s, p, d, e in t_results if p is not None]
    base_map = {s: p for s, p, _ in valid}
    flips = []
    for s, p2 in t_valid:
        p1 = base_map.get(s)
        if p1 is None:
            continue
        if (p1 >= 0.7) != (p2 >= 0.7) and abs(p1 - p2) > 0.35:
            flips.append({"source": s, "before": round(p1, 3), "after": round(p2, 3)})
    metrics["stability"] = {"flips": flips}
    if flips:
        findings.append(finding(
            "high", "STABILITY_FLIP",
            f"图片经温和变换（重压缩+缩放）后，{len(flips)} 个检测器的结果发生剧烈翻转"
            f"（{json.dumps(flips, ensure_ascii=False)}），疑似存在对抗扰动（反取证特征）",
            {"flips": flips}))
    else:
        findings.append(finding("info", "STABILITY_OK", "变换前后检测结果稳定"))

    if errors:
        metrics["errors"] = errors
    return module_result("online", findings=findings, metrics=metrics)
