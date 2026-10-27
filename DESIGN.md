# AI 图像取证分析工具 · 设计文档

> 版本：v1.0（瘦核心版）
> 定位：本地优先的图片真伪初筛与取证辅助工具。输出"证据 + 分级结论"，而非司法鉴定意见。

## 1. 产品形态

- **单一代码库，两种部署模式**（一个配置项切换，无代码差异）：
  - 单机模式：`BIND_HOST=127.0.0.1`，仅本机浏览器可用（Mac mini / Windows 均可）
  - 服务器模式：`BIND_HOST=0.0.0.0`，局域网 + Tailscale 虚拟组网访问（手机/异地可用）
- **Docker 为唯一推荐运行方式**（多架构镜像：ARM64 + x86_64）；裸 Python 运行作为备选
- 后端：FastAPI；前端：无构建依赖的单页 HTML（响应式，手机可用）

## 2. 分析管线（6 模块 + 结论引擎）

| # | 模块 | 文件 | 原理 | 产物 |
|---|------|------|------|------|
| 1 | 文件与元数据 | `forensics/filemeta.py` | EXIF 解析；JPEG 量化表/Huffman 表提取并与 libjpeg 标准表比对（编码器指纹）；内嵌缩略图一致性；C2PA/JUMBF 字节级扫描；生成器字符串匹配（仅元数据文本段，防二进制误报）；文件质量评级（original/transcoded/screenshot_like） | 文本证据 |
| 2 | ELA 误差水平分析 | `forensics/ela.py` | 以 q95 重存后求差，块级（32px）统计，超全局均值+3σ 且比值>1.6 的局部热点报警 | 热力图 |
| 3 | FFT 频谱 | `forensics/fft_analysis.py` | 去趋势后做 FFT；高频能量比（阈值 8%，低严重度）+ 径向剖面孤立亮峰（z>12，提示周期性人工操作） | 频谱图 |
| 4 | 噪声残差 | `forensics/noise_analysis.py` | NLM 去噪取残差；平坦块（24px）噪声强度的空间变异系数（CV<0.18）+ 亮暗区域噪声比（0.85~1.15 为趋同）联合判定"注入噪声"；文件质量差时自动降级 | 热力图 |
| 5 | 克隆检测 | `forensics/clone_detect.py` | 块（24px, stride 12）归一化 DCT 特征 + 字典序排序 + 滑窗容差匹配（Fridrich 经典法变体）；覆盖>60% 判"无法结论"防误报 | 标记图 |
| 6 | 在线检测层 | `forensics/online_detectors.py` | 可插拔：HuggingFace Inference API（开源模型投票，支持 hf-mirror 镜像）/ Sightengine / Hive；全部配 Key 才启用，失败优雅降级；含**变换稳定性测试**（重压缩+缩放后重跑，结果翻转→疑似对抗扰动） | 投票结果 |

**结论引擎**（`forensics/verdict.py`）：不打总分，按证据性质分四档——
`AI_TRACE`（检出 AI 痕迹）/ `REPROCESS`（疑似再处理，有反取证可能）/ `REPROCESS_WEAK`（少量痕迹）/ `CLEAN`（未发现痕迹，≠证明为真）。
文件质量评级会影响措辞与部分模块的置信度。

## 3. 已知局限与待校准项（重要）

1. **克隆检测与噪声模块的阈值目前用合成测试图标定**。合成图的纹理分布与真实照片有系统性差异，上线后应收集 20~50 张真实场景样本（含已知真图/已知篡改图）复测并调整阈值（模块文件顶部常量）。
2. ELA 对"最终保存质量与原始质量接近"的编辑敏感度有限；对 PNG/截图基本无效（已有低信号提示）。
3. 在线检测层依赖第三方服务的可用性与配额；国内网络必须配置 `HF_ENDPOINT=https://hf-mirror.com`。
4. 本工具不覆盖：SynthID 检测（无公开接口）、反向搜图（无免费 API）——已作为人工核查清单嵌入报告。

## 4. V2 路线（预留）

- 本地检测模型层：HuggingFace 开源检测器（ViT 类，单模型 ~400MB）+ TruFor 篡改定位模型，走 Apple Silicon MPS 加速；启用后"变换稳定性测试"改由本地模型执行
- 批量任务队列 + SQLite 历史库 + 报告归档检索
- 配置文件 Web 化（在页面里改配置而非编辑 .env）

## 5. 目录结构

```
ai-image-forensics/
├── app.py                  # FastAPI 后端 + 静态服务入口
├── forensics/              # 分析管线包
│   ├── pipeline.py         # 编排 + 批量汇总 + 工具指纹聚类
│   ├── verdict.py          # 结论引擎
│   ├── filemeta.py / ela.py / fft_analysis.py
│   ├── noise_analysis.py / clone_detect.py / online_detectors.py
│   ├── report.py           # JSON + 自包含 HTML 报告
│   └── common.py           # 公共工具
├── static/index.html       # 前端单页
├── tests/                  # 测试样本生成 + 冒烟测试
├── Dockerfile / docker-compose.yml / .env.example
└── data/                   # 运行数据（报告、上传），git 忽略
```
