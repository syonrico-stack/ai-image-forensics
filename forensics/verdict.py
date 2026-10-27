"""结论引擎（v1.1）：以"是否 AI 产出"为主轴的四档分级。

档位（按证据强度从高到低）：
  AI_CONFIRMED     - 明确 AI 标识：国标 AIGC 元数据 / C2PA AI 声明 / 生成器字符串 / 角标水印
  AI_SUSPECTED     - 疑似 AI：在线检测器多数票 / 对抗扰动翻转等统计证据
  PROCESSED        - 检出明显软件处理痕迹（但无 AI 证据）
  NORMAL_PROCESSED - 轻微痕迹或手机正常修饰（计算摄影、导出重编码等）
  NO_TRACE         - 未发现明显痕迹（≠ 证明真实）
"""

SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1, "info": 0}

# 确定性 AI 证据（标识类，查到即实锤）
AI_HARD_CODES = {"AIGC_LABEL", "C2PA_AI_CLAIM", "GENERATOR_STRING", "WATERMARK_AI_LABEL"}
# 统计性 AI 证据
AI_SOFT_CODES = {"ONLINE_CONSENSUS_AI", "ONLINE_DETECTOR_HIGH", "STABILITY_FLIP"}
# 一般软件处理痕迹（手机正常修饰已在模块层降级，不会进入这里的高危档）
REPROCESS_CODES = {
    "ENCODER_MISMATCH", "DQT_HUFFMAN_MISMATCH", "METADATA_STRIPPED_SUSPICIOUS",
    "NOISE_UNIFORM", "FFT_SPECTRAL_PEAKS", "FFT_HF_ANOMALY",
    "ELA_STRONG_REGIONS", "CLONE_REGIONS", "THUMBNAIL_INCONSISTENT",
    "EDITOR_STRING", "SOFTWARE_TAG",
}


def grade(results, file_quality):
    ai_hard, ai_soft, reprocess, info_evidence = [], [], [], []
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
            if code in AI_HARD_CODES:
                ai_hard.append(entry)
            elif code in AI_SOFT_CODES:
                ai_soft.append(entry)
            else:
                reprocess.append(entry)

    hard_score = sum(SEVERITY_WEIGHT[f["severity"]] for f in ai_hard)
    soft_score = sum(SEVERITY_WEIGHT[f["severity"]] for f in ai_soft)
    rp_score = sum(SEVERITY_WEIGHT[f["severity"]] for f in reprocess)

    quality = file_quality.get("grade", "unknown")
    quality_note = {
        "phone_original": "文件为手机直出，其计算摄影（降噪/锐化/HDR）痕迹已按正常修饰处理。",
        "original": "文件较原始，取证痕迹可信度高。",
        "transcoded": "文件经过转码/重保存，部分像素级取证结论可信度下降。",
        "screenshot_like": "文件疑似截图或经过多次转发，像素级取证结论仅供参考。",
        "unknown": "文件质量未知。",
    }.get(quality, "")

    if hard_score >= 3:
        tier = "AI_CONFIRMED"
        title = "检出 AI 生成标识"
        summary = "文件携带 AI 生成/合成的确定性标识（元数据或角标），可认定为 AI 产出。"
    elif soft_score >= 3:
        tier = "AI_SUSPECTED"
        title = "疑似 AI 生成或加工"
        summary = "统计检测器给出 AI 倾向的多重信号，但未发现确定性标识，建议结合人工核查确认。"
    elif rp_score >= 4:
        tier = "PROCESSED"
        title = "检出明显软件处理痕迹"
        summary = "发现多项软件编辑/再处理痕迹，但未发现 AI 相关证据。"
    elif rp_score >= 2:
        tier = "NORMAL_PROCESSED"
        title = "正常修饰痕迹"
        summary = "仅发现轻微处理痕迹，符合日常修图/传输重编码特征，未见 AI 相关证据。"
    else:
        tier = "NO_TRACE"
        title = "未发现明显痕迹"
        summary = ("当前手段未发现 AI 或处理痕迹。"
                   "注意：这不等于证明图片为真实拍摄——剥离标识的 AI 图或全新生成的图片可能不留可检测痕迹，"
                   "重要结论请结合人工核查步骤。")

    return {
        "tier": tier,
        "title": title,
        "summary": summary + " " + quality_note,
        "ai_evidence": ai_hard + ai_soft,
        "reprocess_evidence": reprocess,
        "info": info_evidence,
        "ai_score": hard_score + soft_score,
        "reprocess_score": rp_score,
    }
