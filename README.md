# AI 图像取证分析工具

鉴别图片是否被 AI 生成 / AI 局部修改 / 软件再处理的本地优先取证工具。
多模块分析管线输出**证据清单 + 分级结论 + 可视化热力图**，支持单张与批量，可导出自包含 HTML 报告。

- 单机模式：Mac mini / Windows 本地运行，仅本机可用
- 服务器模式：Mac mini 常驻运行，局域网 + Tailscale 随时随地访问（手机也可以）
- 全部取证分析在本地完成；在线 AI 检测接口为可选项（默认关闭密钥即跳过）

> ⚠️ 本工具输出为**取证线索**，不是司法鉴定意见。"未发现痕迹"不等于证明图片真实。

---

## 一、快速开始（Docker，推荐）

### Mac mini（Apple Silicon）

```bash
# 1. 安装 OrbStack（比 Docker Desktop 轻快，个人免费）：https://orbstack.dev
#    安装后在设置里开启"登录时自动启动"
# 2. 克隆本仓库并启动
git clone https://github.com/<你的用户名>/ai-image-forensics.git
cd ai-image-forensics
cp .env.example .env        # 按需编辑配置（也可先不管）
docker compose up -d --build
# 3. 浏览器打开
open http://localhost:8800
```

### Windows

```powershell
# 1. 安装 Docker Desktop（自带 WSL2）：https://www.docker.com/products/docker-desktop/
# 2. 克隆仓库后：
cd ai-image-forensics
copy .env.example .env
docker compose up -d --build
# 3. 浏览器打开 http://localhost:8800
```

### 不用 Docker 的备选方式（裸 Python）

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py     # 打开 http://127.0.0.1:8000
```

## 二、两种部署模式切换

编辑 `.env` 后 `docker compose up -d` 重启即可：

| 模式 | BIND_HOST | 效果 |
|---|---|---|
| 单机（默认） | `127.0.0.1` | 只有本机浏览器能访问 |
| 服务器 | `0.0.0.0` | 局域网设备可访问；配合 Tailscale 可异地访问 |

`docker-compose.yml` 已配置 `restart: always`，配合 OrbStack"登录时自动启动"即为常驻服务。

## 三、远程访问（Tailscale，零基础指引）

Tailscale 在你的设备之间组建加密的私有网络，不需要公网 IP、不暴露端口：

1. Mac mini：App Store 安装 **Tailscale**，或 `brew install --cask tailscale`，打开并登录（可用 GitHub/Google 账号）
2. 手机/Windows：同样安装 Tailscale 客户端并登录**同一账号**
3. 确认 `.env` 中 `BIND_HOST=0.0.0.0` 并重启服务
4. 在 Tailscale 管理页（login.tailscale.com）查看 Mac mini 的 Tailscale IP（形如 `100.x.x.x`）
5. 任何已登录设备上访问 `http://100.x.x.x:8800` 即可——在外用手机也一样

> 安全默认：请勿把路由器端口映射到 8800 暴露公网。如确有公网需求，先加反向代理 + 认证。

## 四、在线 AI 检测层（可选）

取证模块全部本地运行；以下在线接口作为"AI 检测投票"的补充，**不配 Key 就自动跳过**：

| 来源 | 配置项 | 说明 |
|---|---|---|
| HuggingFace 开源模型 | `ENABLE_HF=1`（默认）、可选 `HF_TOKEN` | 免费；**国内网络必须** `HF_ENDPOINT=https://hf-mirror.com` |
| Sightengine | `SIGHTENGINE_USER` / `SIGHTENGINE_SECRET` | 注册有免费额度 |
| Hive Moderation | `HIVE_API_KEY` | 免费试用 |

配置写入 `.env` 后重启服务生效。页面右上角会显示当前检测层状态。

## 五、验证安装（冒烟测试）

```bash
# 在项目目录内（裸 Python 环境或容器内均可）
python tests/run_smoke.py
# 应输出：6/6 模块执行，管线 OK
```

`tests/samples/` 内置了 6 张带已知"答案"的测试图（编辑图、克隆图、噪声注入图等），也可以直接在网页里上传它们，直观感受各模块的表现。

## 六、给 Kimi Code 的落地指引

> 如果你在 Mac mini 上使用 Kimi Code 完成部署，把下面这段直接发给它：

```
请帮我落地当前目录下的 ai-image-forensics 项目：
1. 检查并安装 OrbStack（如未安装，用 brew install --cask orbstack，需要时提醒我输入密码），并开启"登录时自动启动"
2. 复制 .env.example 为 .env
3. 执行 docker compose up -d --build 构建并启动服务（如 8800 端口被占用，帮我改一个）
4. 运行 python3 tests/run_smoke.py 或在浏览器打开 http://localhost:8800 验证
5. 用 tests/samples/ 里的测试图在页面上试跑一张，确认有结果输出
6. 初始化 git 仓库（如尚未初始化），提交全部代码并推送到我的 GitHub 仓库（我会提供仓库地址）
7. 如遇报错，先自行排查修复；涉及付费/账号/密码的操作请先问我
```

## 七、局限性与使用建议

- 结论分级与证据逻辑见 `DESIGN.md`；其中克隆检测与噪声模块的阈值基于合成样本标定，**建议收集你业务场景的真实样本（已知真伪各 20+ 张）复测后再依赖其自动结论**
- 上传**原始文件**效果最佳；截图和多次转发的图会显著削弱像素级取证能力
- 重要结论请结合报告末尾的"人工核查步骤"（SynthID、反向搜图、C2PA 验证）交叉确认
