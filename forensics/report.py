"""报告导出：JSON + 自包含 HTML（可直接打开/转发/存档）。"""
import html
import json
import os

TIER_LABEL = {
    "AI_CONFIRMED": ("检出 AI 生成标识", "#c92f2f"),
    "AI_SUSPECTED": ("疑似 AI 生成或加工", "#e08a2e"),
    "PROCESSED": ("检出明显软件处理痕迹", "#d9b23a"),
    "NORMAL_PROCESSED": ("正常修饰痕迹", "#7a9a4e"),
    "NO_TRACE": ("未发现明显痕迹", "#3f9e5f"),
}
MODULE_LABEL = {
    "filemeta": "文件与元数据（含 AIGC 标识）", "watermark": "角标水印 OCR",
    "ela": "ELA 误差水平分析",
    "fft": "FFT 频谱分析", "noise": "噪声残差分析",
    "clone": "克隆（复制粘贴）检测", "online": "在线 AI 检测 + 稳定性测试",
}
SEV_LABEL = {"high": "高", "medium": "中", "low": "低", "info": "信息"}


def save_json(report, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    slim = {k: v for k, v in report.items() if k != "artifacts"}
    path = os.path.join(out_dir, f"report_{report['id']}.json")
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(slim, fp, ensure_ascii=False, indent=2)
    return path


def render_html(report):
    v = report["verdict"]
    label, color = TIER_LABEL.get(v["tier"], (v["title"], "#888"))
    esc = html.escape

    def finding_li(f):
        return (f"<li class='sev-{f['severity']}'><b>[{SEV_LABEL.get(f['severity'], f['severity'])}]</b> "
                f"{esc(f['message'])}</li>")

    sections = []
    for m in report["modules"]:
        name = MODULE_LABEL.get(m["module"], m["module"])
        status = {"ok": "✓ 完成", "skipped": "⊘ 跳过", "error": "✗ 异常"}.get(m["status"], m["status"])
        items = "".join(finding_li(f) for f in m.get("findings", []))
        note = f"<p class='note'>{esc(m['note'])}</p>" if m.get("note") else ""
        sections.append(
            f"<section><h3>{esc(name)} <span class='status'>{status}</span></h3><ul>{items}</ul>{note}</section>")

    imgs = []
    art_labels = {"ela_heatmap": "ELA 热力图", "fft_spectrum": "FFT 频谱",
                  "noise_heatmap": "噪声强度热力图", "clone_map": "克隆区域标记",
                  "original": "原图"}
    for k, url in report.get("artifacts", {}).items():
        imgs.append(f"<figure><img src='{url}'><figcaption>{esc(art_labels.get(k, k))}</figcaption></figure>")

    checklist = "".join(f"<li>{esc(x)}</li>" for x in report.get("manual_checklist", []))

    return f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>取证分析报告 - {esc(report['file'])}</title>
<style>
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:900px;margin:24px auto;padding:0 16px;color:#222}}
.banner{{background:{color};color:#fff;padding:18px 22px;border-radius:10px}}
.banner h1{{margin:0;font-size:22px}} .banner p{{margin:8px 0 0}}
.meta{{color:#666;font-size:13px;margin:12px 0}}
section{{margin:18px 0;padding:14px 18px;background:#f7f7f9;border-radius:10px}}
h3{{margin-top:0}} .status{{font-size:12px;color:#888;font-weight:normal}}
.sev-high{{color:#c0392b}} .sev-medium{{color:#d68910}} .sev-low{{color:#7d6608}} .sev-info{{color:#555}}
.note{{color:#888;font-size:13px}}
figure{{display:inline-block;margin:8px}} img{{max-width:260px;border-radius:8px;border:1px solid #ddd}}
figcaption{{font-size:12px;color:#777;text-align:center}}
footer{{color:#999;font-size:12px;margin:24px 0}}
</style></head><body>
<div class="banner"><h1>{esc(label)}</h1><p>{esc(v['summary'])}</p></div>
<p class="meta">文件：{esc(report['file'])} ｜ 尺寸：{report['size']['width']}×{report['size']['height']} ｜
分析时间：{esc(report['time'])}<br>SHA-256：{report['sha256']} ｜ 文件质量评级：{esc(report['file_quality']['grade'])}</p>
<h2>可视化证据</h2><div>{''.join(imgs)}</div>
<h2>模块详情</h2>{''.join(sections)}
<section><h3>建议的人工核查步骤</h3><ul>{checklist}</ul></section>
<footer>本报告由 AI 图像取证分析工具自动生成。工具结论为证据线索而非司法鉴定意见；
"未发现痕迹"不等于证明图片为真实拍摄。</footer>
</body></html>"""


def save_html(report, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"report_{report['id']}.html")
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(render_html(report))
    return path
