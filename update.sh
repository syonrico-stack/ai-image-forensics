#!/bin/bash
# AI 图像取证分析工具 · 一键更新脚本
# 用法：bash update.sh
set -e
cd "$(dirname "$0")"

echo "==> 1/4 拉取最新代码..."
git pull --ff-only

echo "==> 2/4 重建 Docker 镜像并重启服务..."
docker compose up -d --build

echo "==> 3/4 等待服务启动..."
for i in $(seq 1 20); do
  if curl -sf http://127.0.0.1:8800/api/config-status > /dev/null 2>&1; then
    echo "    服务已就绪 ✓"
    break
  fi
  sleep 2
done

echo "==> 4/4 冒烟测试..."
if docker compose exec -T forensics python tests/run_smoke.py 2>/dev/null; then
  echo "    冒烟测试通过 ✓"
else
  echo "    （容器内测试跳过或未通过，可打开 http://localhost:8800 用 tests/samples/ 手动验证）"
fi

echo ""
echo "更新完成！访问 http://localhost:8800"
