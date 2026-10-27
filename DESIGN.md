# AI 图像取证分析工具 · 设计文档

> 版本：v1.1（AI 来源识别聚焦版）
> 定位：本地优先的图片真伪初筛与取证辅助工具。**主问题：这张图是不是 AI（豆包/Kimi/Midjourney 等）产出？** 手机正常修饰（计算摄影、调色美颜、导出重编码）视为正常。输出"证据 + 分级结论"，而非司法鉴定意见。

## v1.1 变更摘要

1. **结论主轴改为 AI 来源识别**：手机 ISP 处理、日常修图降级为"正常修饰"，不再误报
2. **新增国标 AIGC 隐式标识解析**（`{"AIGC":{"Label":"1",...}}`，确定性证据）——合规要求下国产 AI 工具产出图均应携带
3. **新增角标水印 OCR 模块**：抓"豆包AI生成"等显式标识（四角裁剪 + OCR + 关键词匹配，命中即提前退出）
4. **手机白名单**：EXIF 为手机设备且无电脑软件标签 → `phone_original`，编码矛盾/噪声均匀等信号降级为正常
5. 生成器指纹库扩充：豆包/即梦/Seedream/混元/通义万相/文心/可灵/Kimi + Midjourney/DALL-E/Firefly/Flux 等

## 1. 产品形态

- **单一代码库，两种部署模式**（一个配置项切换，无代码差异）：
  - 单机模式：`BIND_HOST=127.0.0.1`，仅本机浏览器可用（Mac mini / Windows 均可）
  - 服务器模式：`BIND_HOST=0.0.0.0`，局域网 + Tailscale 虚拟组网访问（手机/异地可用）
- **Docker 为唯一推荐运行方式**（多架构镜像：ARM64 + x86_64）；裸 Python 运行作为备选
- 后端：FastAPI；前端：无构建依赖的单页 HTML（响应式，手机可用）

## 2. 分析管线（7 模块 + 结论引擎）

| # | 模块 | 文件 | 原理 | 产物 |
|---|------|------|------|------|
| 1 | 文件与元数据 | `forensics/filemeta.py` | EXIF 解析；**国标 AIGC 隐式标识解析（确定性 AI 证据）**；JPEG 量化表编码器指纹；缩略图一致性；C2PA/JUMBF 扫描；生成器字符串（国产+西方，仅元数据文本段）；手机白名单；文件质量评级（phone_original/original/transcoded/screenshot_like） | 文本证据 |
| 2 | 角标水印 OCR | `forensics/watermark.py` | 四角裁剪放大 + 预处理 + tesseract OCR，匹配 AI 显式标识关键词（"AI生成"/豆包/即梦等）；置信度过滤防纹理误读；命中即退出 | 文本证据 |
| 3 | ELA 误差水平分析 | `forensics/ela.py` | 以 q95 重存后求差，块级（32px）统计，超全局均值+3σ 且比值>1.6 的局部热点报警 | 热力图 |
| 4 | FFT 频谱 | `forensics/fft_analysis.py` | 去趋势后做 FFT；高频能量比（阈值 8%，低严重度）+ 径向剖面孤立亮峰（z>12） | 频谱图 |
| 5 | 噪声残差 | `forensics/noise_analysis.py` | NLM 去噪取残差；平坦块噪声强度变异系数 + 亮暗噪声比联合判定"注入噪声"；**手机直出直接归为计算摄影正常现象** | 热力图 |
| 6 | 克隆检测 | `forensics/clone_detect.py` | 块归一化 DCT 特征 + 字典序排序 + 滑窗容差匹配；覆盖>60% 判"无法结论"防误报 | 标记图 |
| 7 | 在线检测层 | `forensics/online_detectors.py` | 可插拔：HF 开源模型投票（支持 hf-mirror）/ Sightengine / Hive；失败优雅降级；含变换稳定性测试（结果翻转→疑似对抗扰动） | 投票结果 |

**结论引擎**（`forensics/verdict.py`）：五档——
`AI_CONFIRMED`（确定性标识：AIGC 元数据/C2PA AI 声明/生成器字符串/角标水印）/
`AI_SUSPECTED`（统计证据：在线投票多数、对抗翻转）/
`PROCESSED`（明显软件处理痕迹，无 AI 证据）/
`NORMAL_PROCESSED`（轻微痕迹/手机正常修饰）/
`NO_TRACE`（未发现痕迹，≠证明为真）。

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
