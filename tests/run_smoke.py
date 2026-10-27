"""冒烟测试：跑通管线 + 验证已知样本的预期行为。

用法：python tests/run_smoke.py
（在项目根目录执行；无需启动 Web 服务）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ENABLE_HF"] = "0"  # 冒烟测试不依赖网络

from forensics import pipeline

SAMPLES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples")

# (样本文件, 期望命中的模块, 期望的发现代码之一)
EXPECT = [
    ("edited.jpg", "ela", "ELA_STRONG_REGIONS"),            # 局部编辑图 → ELA 应报警
    ("camera_like.jpg", "filemeta", "ENCODER_MISMATCH"),    # 软件编码+相机EXIF → 矛盾
    ("reshared.jpg", "filemeta", "LIBJPEG_TABLES"),         # 转发图 → libjpeg 指纹
    ("ai_gen_cafe.png", "filemeta", "AIGC_LABEL"),          # AI 生成图 → 国标隐式标识
    ("phone_photo.jpg", "filemeta", "PHONE_REENCODE_NORMAL"),  # 手机导出 → 白名单降级
]

# 结论档位断言：手机照片不得被判为 AI 或 PROCESSED
TIER_EXPECT = {
    "ai_gen_cafe.png": {"AI_CONFIRMED"},
    "phone_photo.jpg": {"NO_TRACE", "NORMAL_PROCESSED"},
}

def main():
    if not os.path.isdir(SAMPLES):
        print("未找到测试样本目录 tests/samples/，跳过样本断言，仅做管线自检。")
    passed, failed = 0, 0
    for fn, mod, code in EXPECT:
        path = os.path.join(SAMPLES, fn)
        if not os.path.exists(path):
            print(f"⊘ {fn} 样本不存在，跳过")
            continue
        rep = pipeline.analyze_image(path, keep_artifacts=False)
        module = next((m for m in rep["modules"] if m["module"] == mod), None)
        codes = [f["code"] for f in (module or {}).get("findings", [])]
        errors = [m for m in rep["modules"] if m["status"] == "error"]
        tier = rep["verdict"]["tier"]
        tier_ok = tier in TIER_EXPECT.get(fn, {tier})
        if code in codes and not errors and tier_ok:
            print(f"✓ {fn}: 命中 {mod}/{code}，结论={tier}")
            passed += 1
        else:
            print(f"✗ {fn}: 期望 {mod}/{code}（档位 {TIER_EXPECT.get(fn, '不限')}），"
                  f"实际 codes={codes}，结论={tier}，errors={[m['module'] for m in errors]}")
            failed += 1
    print(f"\n冒烟测试：{passed} 通过，{failed} 失败")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
