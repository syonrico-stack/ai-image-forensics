# AI 图像取证分析工具 - 多架构镜像（支持 ARM64 / x86_64）
FROM python:3.12-slim

# OpenCV 运行时需要的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV BIND_HOST=0.0.0.0 \
    PORT=8000 \
    DATA_DIR=/app/data
VOLUME ["/app/data"]
EXPOSE 8000

CMD ["python", "app.py"]
