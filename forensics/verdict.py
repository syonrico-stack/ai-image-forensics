"""结论引擎：把各模块的发现项汇成三档分级结论，不做伪精确总分。

分级：
  AI_TRACE    - 检出 AI 相关痕迹（有直接证据，如 C2PA AI 声明 / 在线检测器高分）
  REPROCESS   - 疑似反取证/再处理（发现软件再编码、噪声注入、频域伪装等处理痕迹）
  CLEAN       - 未发现明显痕迹（注意：不等于"证明为真"，只代表当前手段未发现证据）
"""

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1, "info": 0}

# 哪些发现代码直接指向 AI
AI_DIRECT_CODES = {
    "C2PA_AI_CLAIM", "ONLINE_DETECTOR_HIGH", "ONLINE_CONSENSUS_AI",
}
# 指向"再处理/反取证"的发现代码
REPROCESS_CODES = {
    "ENCODER_MISMATCH", "DQT_HUFFMAN_MISMATCH", "METADATA_STRIPPED_SUSPICIOUS",
    "NOISE_UNIFORM", "NOISE_INJECTION_SPECTRUM", "FFT_SPECTRAL_PEAKS",
    "FFT_HF_ANOMALY", "ELA_STRONG_REGIONS", "CLONE_REGIONS",
    "THUMBNAIL_INCONSISTENT", "STABILITY_FLIP", "DOUBLE_COMPRESSION",
}


def grade(results, file_quality):
    """results: 各模块结果列表；file_quality: 文件质量评级 dict。
    返回结论 dict。
    """
    ai_evidence, reprocess_evidence, info_evidence = [], [], []
    for res in results:
        if res.get("status") != "ok":
            continue
        for f in res.get("findings", []):
            sev = f.get("severity", "info")
            if sev == "info":
                info_evidence.append(f)
                continue
            code = f.get("code", "")
            entry = {"module": res["module"], **f}
            if code in AI_DIRECT_CODES:
                ai_evidence.append(entry)
            elif code in REPROCESS_CODES:
                reprocess_evidence.append(entry)
            else:
                # 未归类的中高危发现，按再处理证据保守处理
                if sev in ("high", "medium"):
                    reprocess_evidence.append(entry)

    ai_score = sum(SEVERITY_WEIGHT[f["severity"]] for f in ai_evidence)
    rp_score = sum(SEVERITY_WEIGHT[f["severity"]] for f in reprocess_evidence)

    # 文件质量影响结论措辞
    quality = file_quality.get("grade", "unknown")
    quality_note = {
        "original": "文件较原始，取证痕迹可信度高。",
        "transcoded": "文件经过转码/重保存，部分取证痕迹（ELA、噪声）可信度下降。",
        "screenshot_like": "文件疑似截图或经过多次转发，像素级取证结论仅供参考。",
        "unknown": "文件质量未知。",
    }.get(quality, "")

    if ai_score >= 3:
        tier = "AI_TRACE"
        title = "检出 AI 相关痕迹"
        summary = "发现直接指向 AI 生成/编辑的证据。"
    elif rp_score >= 4:
        tier = "REPROCESS"
        title = "疑似经过再处理（存在反取证可能）"
        summary = "发现多项软件再处理痕迹，不排除有人为掩盖来源的操作。"
    elif rp_score >= 2:
        tier = "REPROCESS_WEAK"
        title = "发现少量再处理痕迹"
        summary = "发现个别再处理迹象，证据强度有限，建议结合人工复核。"
    else:
        tier = "CLEAN"
        title = "未发现明显痕迹"
        summary = ("当前手段未发现 AI 或再处理证据。"
                   "注意：这不等于证明图片为真实拍摄——经过专业洗图或全新生成的图片可能不留可检测痕迹。")

    return {
        "tier": tier,
        "title": title,
        "summary": summary + " " + quality_note,
        "ai_evidence": ai_evidence,
        "reprocess_evidence": reprocess_evidence,
        "info": info_evidence,
        "ai_score": ai_score,
        "reprocess_score": rp_score,
    }
