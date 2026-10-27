"""AI 图像取证分析工具 - 后端服务（FastAPI）

启动：python app.py
配置：通过环境变量或 .env 文件（见 .env.example）
"""
import os
import tempfile
import uuid

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from forensics import pipeline, report as report_mod

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
REPORT_DIR = os.path.join(DATA_DIR, "reports")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# .env 简易加载（不依赖第三方库）
env_path = os.path.join(BASE_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

app = FastAPI(title="AI 图像取证分析工具", docs_url=None, redoc_url=None)

# 内存中保存最近一次分析结果（供导出报告）
LAST_REPORTS = {}


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(BASE_DIR, "static", "index.html"), encoding="utf-8") as fp:
        return fp.read()


@app.post("/api/analyze")
async def analyze(files: list[UploadFile] = File(...)):
    reports = []
    for f in files:
        suffix = os.path.splitext(f.filename or "")[1].lower() or ".jpg"
        if suffix not in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"):
            reports.append({"file": f.filename, "error": f"不支持的格式 {suffix}"})
            continue
        tmp = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}{suffix}")
        with open(tmp, "wb") as out:
            out.write(await f.read())
        try:
            rep = pipeline.analyze_image(tmp)
            rep["file"] = f.filename  # 恢复原始文件名
            report_mod.save_json(rep, REPORT_DIR)
            LAST_REPORTS[rep["id"]] = rep
            reports.append(rep)
        except Exception as e:
            reports.append({"file": f.filename, "error": f"分析失败：{e}"})
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
    summary = pipeline.summarize_batch([r for r in reports if "verdict" in r]) if len(reports) > 1 else None
    return JSONResponse({"reports": reports, "batch_summary": summary})


@app.get("/api/report/{report_id}/html")
def export_html(report_id: str):
    rep = LAST_REPORTS.get(report_id)
    if not rep:
        return JSONResponse({"error": "报告不存在或服务已重启，请重新分析"}, status_code=404)
    path = report_mod.save_html(rep, REPORT_DIR)
    return FileResponse(path, filename=f"取证报告_{rep['file']}.html")


@app.get("/api/config-status")
def config_status():
    """告诉前端在线检测层配置了哪些（不回传密钥本身）。"""
    return {
        "hf_enabled": os.environ.get("ENABLE_HF", "1") == "1",
        "hf_has_token": bool(os.environ.get("HF_TOKEN")),
        "sightengine": bool(os.environ.get("SIGHTENGINE_USER") and os.environ.get("SIGHTENGINE_SECRET")),
        "hive": bool(os.environ.get("HIVE_API_KEY")),
    }


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    print(f"AI 图像取证分析工具已启动: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
