"""模块 5：克隆（复制-粘贴）检测

原理：把图分成重叠小块，提取 DCT 特征，字典序排序后找特征几乎相同
但位置相距较远的块对——这是经典的复制-粘贴篡改取证方法。
输出匹配区域的可视化叠加图。
"""
import cv2
import numpy as np

from .common import finding, module_result, resize_for_analysis

BLOCK = 24
STRIDE = 12
MIN_SHIFT = 36        # 匹配块之间的最小空间距离（像素）
MAX_MATCH_PAIRS = 2000
MIN_CLUSTER = 8       # 聚成一处证据所需的最少匹配块数
MIN_RATIO = 0.01      # 匹配区域至少覆盖的画面比例
MAX_RATIO = 0.60      # 超过此比例视为同质纹理（整图相似），不作克隆结论
MAX_GROUP = 100       # 特征组超过此大小视为常见纹理，跳过


def _block_features(gray):
    """返回 (特征矩阵, 位置列表)：归一化 DCT 低频系数，供排序+容差匹配。"""
    h, w = gray.shape
    feats, positions = [], []
    for y in range(0, h - BLOCK + 1, STRIDE):
        for x in range(0, w - BLOCK + 1, STRIDE):
            blk = gray[y:y + BLOCK, x:x + BLOCK].astype(np.float32)
            if blk.std() < 6:   # 跳过纯色块（大量误报来源）
                continue
            dct = cv2.dct(blk)
            scale = np.abs(dct).std() + 1e-6
            q = np.round(dct[:4, :4] / scale * 2) / 2   # 轻度量化
            feats.append(q.ravel())
            positions.append((x, y))
    return np.array(feats, dtype=np.float32), positions


def analyze(path, pil, arr, config=None):
    findings, artifacts, metrics = [], {}, {}
    small, _ = resize_for_analysis(arr, 800)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    if h < 64 or w < 64:
        return module_result("clone", status="skipped",
                             findings=[finding("info", "CLONE_SKIPPED", "图片太小")],
                             note="图片过小，跳过克隆检测")

    feats, positions = _block_features(gray)
    if len(feats) < 50:
        return module_result("clone", status="skipped",
                             findings=[finding("info", "CLONE_SKIPPED", "有效纹理块不足")])

    # 字典序排序后，对每个块与排序位置相邻的若干块做容差匹配
    order = np.lexsort(feats.T[::-1])
    sf = feats[order]
    matched = np.zeros((h, w), dtype=np.float32)
    pair_count = 0
    WINDOW, TOL = 25, 0.6
    seen = set()
    for i in range(len(order)):
        upper = min(i + WINDOW, len(order))
        for j in range(i + 1, upper):
            if np.abs(sf[i] - sf[j]).max() > TOL:
                break   # 排序首维已超差，后续更远
            a, b = order[i], order[j]
            key = (a, b)
            if key in seen:
                continue
            seen.add(key)
            (x1, y1), (x2, y2) = positions[a], positions[b]
            if abs(x1 - x2) + abs(y1 - y2) < MIN_SHIFT:
                continue
            cv2.rectangle(matched, (x1, y1), (x1 + BLOCK, y1 + BLOCK), 1.0, -1)
            cv2.rectangle(matched, (x2, y2), (x2 + BLOCK, y2 + BLOCK), 1.0, -1)
            pair_count += 1
            if pair_count > MAX_MATCH_PAIRS:
                break

    matched_ratio = float((matched > 0).mean())
    metrics["match_pairs"] = pair_count
    metrics["matched_ratio"] = round(matched_ratio, 4)

    if matched_ratio > MAX_RATIO:
        findings.append(finding(
            "info", "CLONE_INCONCLUSIVE",
            f"相似块覆盖面积过大（{matched_ratio:.0%}），画面纹理高度同质，克隆检测无法给出可靠结论"))
        return module_result("clone", findings=findings, artifacts=artifacts, metrics=metrics)

    if pair_count >= MIN_CLUSTER and matched_ratio > MIN_RATIO:
        vis = small.copy()
        vis[matched > 0] = (0.45 * vis[matched > 0] + 0.55 * np.array([255, 60, 60])).astype(np.uint8)
        artifacts["clone_map"] = vis
        findings.append(finding(
            "medium", "CLONE_REGIONS",
            f"检测到 {pair_count} 组内容高度一致的相似块（覆盖 {matched_ratio:.1%} 面积），"
            "可能存在图内复制-粘贴（红色区域），请结合可视化图人工确认",
            metrics))
    else:
        findings.append(finding("info", "CLONE_NONE", "未发现明显的复制-粘贴区域"))

    return module_result("clone", findings=findings, artifacts=artifacts, metrics=metrics)
