"""
RAG 知识检索模块

支持两种后端:
- ChromaDB (向量语义检索, 推荐)
- 内置 TF-IDF (零依赖降级, 适合快速启动)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

KB_DIR = Path(__file__).resolve().parents[2] / "data" / "knowledge_docs"


# ============================================================
# 文档切片
# ============================================================

def split_text(text: str, chunk_size: int = 400, overlap: int = 60) -> list[str]:
    """中文文本智能切片: 段落优先 → 句边界 → 重叠衔接"""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) <= chunk_size:
            buf += ("\n" + para) if buf else para
        else:
            if buf:
                chunks.append(buf)
            # 超长段落按句切
            if len(para) > chunk_size:
                sents = re.split(r"(?<=[。！？.!?])", para)
                buf = ""
                for s in sents:
                    if len(buf) + len(s) <= chunk_size:
                        buf += s
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = s
            else:
                buf = para
    if buf:
        chunks.append(buf)

    # 重叠
    if overlap and len(chunks) > 1:
        overlapped = [chunks[0]]
        for i in range(1, len(chunks)):
            overlapped.append(chunks[i - 1][-overlap:] + "\n" + chunks[i])
        return overlapped
    return chunks


# ============================================================
# 知识库检索器
# ============================================================

class KnowledgeRetriever:
    """足球战术知识检索器

    自动选择最优后端:
    1. ChromaDB (pip install chromadb) → 向量语义搜索
    2. TF-IDF 关键词匹配 → 零依赖降级
    """

    def __init__(self) -> None:
        self._chroma = None
        self._tfidf = None
        self._docs: list[dict] = []  # [{"content": ..., "meta": ...}, ...]
        self._initialized = False

    # ---- 文档加载 ----

    def load_documents(self, directory: str | Path | None = None) -> int:
        """从目录加载所有 .txt/.md 文档并索引"""
        directory = Path(directory or KB_DIR)
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            self._create_sample_docs(directory)

        raw_docs = []
        for f in sorted(directory.glob("*.txt")) + sorted(directory.glob("*.md")):
            text = f.read_text(encoding="utf-8")
            # 解析简易 YAML 头部 (---\nkey: value\n---)
            meta = _parse_frontmatter(text)
            chunks = split_text(meta["body"])
            for i, chunk in enumerate(chunks):
                raw_docs.append({
                    "content": chunk,
                    "meta": {**meta["meta"], "source": f.name, "chunk": i},
                })

        self._docs = raw_docs
        self._index(raw_docs)
        self._initialized = True
        logger.info(f"知识库就绪: {len(raw_docs)} 个片段")
        return len(raw_docs)

    def _index(self, docs: list[dict]) -> None:
        """构建索引"""
        # 尝试 Chroma
        try:
            import chromadb
            from chromadb.config import Settings
            persist = str(Path(__file__).resolve().parents[2] / "data" / "chroma_db")
            client = chromadb.PersistentClient(
                path=persist,
                settings=Settings(anonymized_telemetry=False),
            )
            col = client.get_or_create_collection(
                "tactics", metadata={"hnsw:space": "cosine"}
            )
            # 增量加入新文档
            existing = set(col.get()["ids"]) if col.count() > 0 else set()
            new_ids, new_docs, new_metas = [], [], []
            for i, d in enumerate(docs):
                cid = f"doc_{i}"
                if cid not in existing:
                    new_ids.append(cid)
                    new_docs.append(d["content"])
                    new_metas.append(d["meta"])
            if new_ids:
                col.add(ids=new_ids, documents=new_docs, metadatas=new_metas)
            self._chroma = col
            logger.info(f"索引后端: ChromaDB ({col.count()} 文档)")
        except ImportError:
            # 降级 TF-IDF
            self._build_tfidf(docs)
            logger.info("索引后端: TF-IDF (pip install chromadb 可启用语义搜索)")

    def _build_tfidf(self, docs: list[dict]) -> None:
        """构建轻量 TF-IDF 索引"""
        from collections import Counter
        import math

        corpus = [d["content"] for d in docs]
        # 分词 (简单 unigram + bigram)
        tokenized = [_tokenize(c) for c in corpus]
        df = Counter()
        for tokens in tokenized:
            df.update(set(tokens))
        N = len(corpus)

        self._tfidf = {
            "docs": docs,
            "tokenized": tokenized,
            "idf": {t: math.log((N + 1) / (df[t] + 1)) + 1 for t in df},
            "N": N,
        }

    # ---- 检索 ----

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """语义检索，返回相关文档片段及来源"""
        if not self._initialized:
            self.load_documents()

        if self._chroma:
            return self._search_chroma(query, top_k)
        return self._search_tfidf(query, top_k)

    def _search_chroma(self, query: str, top_k: int) -> list[dict]:
        results = self._chroma.query(query_texts=[query], n_results=top_k)
        docs = []
        if results.get("documents") and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                d = results["distances"][0][i] if results.get("distances") else 1.0
                m = results["metadatas"][0][i] if results.get("metadatas") else {}
                docs.append({
                    "content": doc,
                    "relevance": round(1.0 - min(d, 1.0), 4),
                    "source": m.get("source", "unknown"),
                    "author": m.get("author", ""),
                    "date": m.get("date", ""),
                    "category": m.get("category", ""),
                    "tags": m.get("tags", ""),
                })
        return docs

    def _search_tfidf(self, query: str, top_k: int) -> list[dict]:
        import math
        from collections import Counter

        if not self._tfidf:
            return []

        q_tokens = _tokenize(query)
        q_tf = Counter(q_tokens)
        idf = self._tfidf["idf"]
        q_vec = {t: (q_tf[t] / max(len(q_tokens), 1)) * idf.get(t, 0)
                  for t in q_tokens}

        scores = []
        for i, tokens in enumerate(self._tfidf["tokenized"]):
            d_tf = Counter(tokens)
            score = 0.0
            for t, w in q_vec.items():
                if t in d_tf:
                    score += w * (d_tf[t] / max(len(tokens), 1)) * idf.get(t, 0)
            # 归一化
            q_norm = math.sqrt(sum(v ** 2 for v in q_vec.values()))
            d_tf_vals = {t: d_tf[t] / max(len(tokens), 1) * idf.get(t, 0)
                         for t in d_tf}
            d_norm = math.sqrt(sum(v ** 2 for v in d_tf_vals.values()))
            if q_norm > 0 and d_norm > 0:
                score /= (q_norm * d_norm)
            scores.append((i, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [
            {
                "content": self._tfidf["docs"][idx]["content"],
                "relevance": round(score, 4),
                "source": self._tfidf["docs"][idx]["meta"].get("source", "unknown"),
                "author": self._tfidf["docs"][idx]["meta"].get("author", ""),
                "date": self._tfidf["docs"][idx]["meta"].get("date", ""),
                "category": self._tfidf["docs"][idx]["meta"].get("category", ""),
                "tags": self._tfidf["docs"][idx]["meta"].get("tags", ""),
            }
            for idx, score in scores[:top_k]
            if score > 0.01
        ]

    # ---- 示例文档 ----

    def _create_sample_docs(self, directory: Path) -> None:
        """首次运行时创建内置示例文档"""
        samples = {
            "曼城边后卫内收战术.txt": """---
author: 战术分析专栏
date: 2024-03
category: 战术体系
tags: 曼城, 瓜迪奥拉, 边后卫, 内收, build-up
---

# 曼城边后卫内收战术深度解析

## 什么是边后卫内收 (Inverted Full-Back)

边后卫内收是瓜迪奥拉战术体系的核心创新之一。与传统的边后卫套边传中不同，
内收边后卫在球队控球时会向中场移动，站位在双后腰之间或侧前方，形成 3-2 的出球结构。

## 战术目的

1. **创造人数优势**: 在后场 build-up 阶段，边后卫内收形成 3v2 或 4v3 的中路人数优势，
   破解对方高位逼抢。

2. **释放中场创造力**: 边后卫内收后，原本的后腰可以前提到更靠前的位置参与进攻，
   德布劳内和 B席因此获得更多前场自由度。

3. **保护转换阶段**: 内收边后卫靠近中路，能在丢球后第一时间形成反抢阵型，
   这解释了为什么曼城的 PPDA (对手每次防守动作的传球数) 数据常年联赛最低。

## 典型人员配置

- 凯尔·沃克 → 右后卫内收为第三中卫
- 斯通斯 / 阿坎吉 → 中卫前提为后腰 (Stones 的 "双角色")
- 罗德里 → 单后腰拖后，提供传导支点

## 弱点与破解

当对方边锋保持宽度并快速转移时，曼城边路会出现短暂真空。
2023-24 赛季阿森纳主场 1-0 曼城的比赛中，马丁内利利用沃克内收后的边路空间完成了多次冲击。
""",

            "高位逼抢体系.txt": """---
author: 战术分析专栏
date: 2024-01
category: 战术体系
tags: 高位逼抢, gegenpressing, 利物浦, 克洛普, 反抢
---

# 现代足球高位逼抢体系全解析

## Gegenpressing 的起源

高位逼抢 (Gegenpressing) 由德国教练推广，克洛普将其发扬光大。
核心原则: 失球后 5 秒内立即反抢，利用对方由守转攻的阵型混乱期创造得分机会。

## 三种逼抢模式

### 1. 人盯人逼抢 (Man-Oriented Press)
- 代表: 贝尔萨的利兹联
- 特点: 每个球员锁定一个对手，全场跟踪
- 优点: 压迫强度极高
- 缺点: 体能消耗大，一旦被突破形成 1v1 空档

### 2. 区域逼抢 (Zonal Press)
- 代表: 克洛普的利物浦
- 特点: 球员负责特定区域，当球进入该区域时集体围抢
- 触发点: 对方回传、背身接球、边线附近

### 3. 混合逼抢 (Hybrid Press)
- 代表: 瓜迪奥拉的曼城
- 特点: 前场人盯人 + 中场区域封锁
- 关键是边后卫内收人数优势配合前场逼抢

## 数据指标

评估逼抢效率的关键数据:
- PPDA: 对手每次防守动作的传球数 (< 8 为优秀)
- High Turnovers: 前场 40 米内抢回球权次数
- Press Success Rate: 逼抢后 5 秒内抢回球权的比率
""",

            "定位球攻防.txt": """---
author: 数据足球
date: 2024-06
category: 定位球
tags: 定位球, 角球, 任意球, xG, 阿森纳
---

# 定位球: 现代足球的第四进攻阶段

## 定位球的重要性

2023-24 赛季英超，定位球进球占总进球的 29%。
阿森纳是联赛定位球进球最多的球队 (22球)，这与他们聘请专职定位球教练 Nicolas Jover 直接相关。

## 角球进攻模式

### 阿森纳: 集群冲击
- 4-5 名球员从不后点冲刺到前点
- 制造混乱后由加布里埃尔/Saliba 利用身高优势终结
- 2023-24 赛季角球 xG 联赛第一

### 曼城: 短角球变阵
- 常用短角球后重新组织
- 利用技术优势在小范围内制造传中角度
- 角球转化为射门的比率联赛最高

## 防守定位球的要点

1. 区域 + 人盯人混合防守优于纯区域防守
2. 近门柱保护者 (Near-Post Defender) 的选位决定 60% 的防守成功率
3. 快速反击: 定位球被解围后 10 秒内的反击进球效率极高
""",

            "xG预期进球完全指南.txt": """---
author: StatsBomb 翻译整理
date: 2024-02
category: 数据分析
tags: xG, 预期进球, 射门质量, 数据模型
---

# xG (预期进球) 完全指南

## xG 是什么

xG (Expected Goals) 衡量一次射门的进球概率 (0~1)。
模型综合考虑: 射门位置、角度、身体部位、防守压力、传球类型、比赛状态。

## xG 的计算维度

1. **射门距离**: 距离越近，xG 越高 (6码区内可达 0.6+)
2. **射门角度**: 正对球门 > 侧翼角度
3. **身体部位**: 脚内侧 > 脚背 > 头球 (同位置头球 xG 约为脚射的 60%)
4. **防守压力**: 有无后卫贴身干扰
5. **助攻类型**: 横传 (Cutback) > 直塞 > 传中 > 定位球

## 如何解读 xG 数据

- **xG > 实际进球**: 终结效率低于预期，可能存在终结能力问题
- **xG < 实际进球**: 终结效率高于预期，可能是顶级射手或存在运气成分
- **xG 差值持续为正**: 通常表明球队体系创造了高质量机会
- **场次 xG**: 单场 xG > 2.0 为优秀的进攻表现

## 局限性

xG 不看球员身份——梅西和普通球员在同样的位置射门，xG 相同。
因此需要结合 Post-Shot xG (PSxG) 来评估射门质量。
""",
        }

        for filename, content in samples.items():
            path = directory / filename
            if not path.exists():
                path.write_text(content, encoding="utf-8")
        logger.info(f"已创建 {len(samples)} 篇示例战术文档 → {directory}")


def _parse_frontmatter(text: str) -> dict:
    """解析 YAML 式头部元数据"""
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2].strip()
    return {"meta": meta, "body": body}


def _tokenize(text: str) -> list[str]:
    """中文简易分词: 提取 2-gram + 单字关键词"""
    # 清理
    text = re.sub(r"[^一-龥a-zA-Z0-9]", " ", text.lower())
    words = []
    # 英文单词
    words.extend(re.findall(r"[a-z]{3,}", text))
    # 中文 2-gram
    chinese = re.findall(r"[一-龥]", text)
    for i in range(len(chinese) - 1):
        words.append(chinese[i] + chinese[i + 1])
    # 单字也加进去
    words.extend(chinese)
    return words


# ============================================================
# 全局单例
# ============================================================

_retriever: KnowledgeRetriever | None = None


def get_retriever() -> KnowledgeRetriever:
    global _retriever
    if _retriever is None:
        _retriever = KnowledgeRetriever()
        _retriever.load_documents()
    return _retriever
