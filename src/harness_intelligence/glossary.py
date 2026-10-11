"""Query-side zh -> en expansion: the cheap half of the cross-language bridge.

``docs/roadmap.md`` §7 Phase 5. A Chinese-only question shares no literal form
with the English implementation files, so the retriever cannot match them. This
module is a small, hand-maintained, reviewable lexicon that maps Chinese domain
terms to the English words a developer would actually write, so the query can
meet the code.

Three rules keep it honest:

* **Query side only.** Expanding indexed content would be wrong: it would let a
  file match terms it never contained. Only :func:`expand_terms` on the query
  side uses this table.
* **No dependency, no model.** Every entry is a dictionary lookup; an unknown
  term changes nothing, so the lexical baseline still works on its own.
* **No file paths.** Like ``benchmarks/hints.jsonl``, an entry must be a term a
  developer would write, never a repository path -- writing the answer file
  would measure the annotation instead of the retrieval.
"""
from __future__ import annotations

from typing import Sequence

#: Chinese term -> English words / identifier fragments that occur in this kind
#: of repository. Keys are the CJK n-grams ``terms.extract_terms`` actually
#: emits (2 and 3 characters), values are lowercase ASCII.
GLOSSARY: dict[str, tuple[str, ...]] = {
    # indexing and staleness
    "索引": ("index",),
    "陈旧": ("stale", "staleness"),
    "重建": ("rebuild", "build"),
    "刷新": ("refresh",),
    "指纹": ("fingerprint",),
    "文件集": ("fileset",),
    "版本": ("version",),
    "模式": ("pattern", "mode"),
    "迁移": ("migration", "migrate"),
    "符号": ("symbol",),
    "提取": ("extract",),
    "声明": ("declaration", "declare"),
    "语言": ("language",),
    "正则": ("regex",),
    # retrieval and ranking
    "检索": ("retrieval", "retrieve", "search"),
    "排序": ("rank", "score", "sort"),
    "打分": ("score", "scoring"),
    "命中": ("hit", "match"),
    "片段": ("fragment",),
    "窗口": ("window",),
    "预算": ("budget",),
    "权重": ("weight",),
    "上限": ("cap", "limit"),
    "密度": ("density",),
    "路径": ("path",),
    "目录": ("directory",),
    "排除": ("exclude",),
    "忽略": ("ignore",),
    "覆盖": ("coverage", "cover"),
    "召回": ("recall",),
    "精度": ("precision",),
    "语义": ("semantic",),
    "重排": ("rerank",),
    "后端": ("backend",),
    "向量": ("vector",),
    "嵌入": ("embedding",),
    "缓存": ("cache",),
    "开销": ("overhead",),
    "估算": ("estimate",),
    "字符": ("character",),
    "中文": ("chinese",),
    "回退": ("fallback",),
    "降级": ("degrade",),
    # memory
    "记忆": ("memory",),
    "事实": ("fact",),
    "分类": ("category",),
    "校验": ("validate", "validation"),
    "标签": ("tag",),
    "归属": ("project", "source"),
    # tools and integration
    "工具": ("tool",),
    "注册": ("register",),
    "入口": ("entry",),
    "服务": ("server",),
    "客户端": ("client",),
    "启动": ("launch", "start"),
    "配置": ("config",),
    "环境": ("environment",),
    "变量": ("variable",),
    "参数": ("parameter", "argument"),
    "错误": ("error",),
    "异常": ("exception",),
    "退出码": ("exit",),
    "解析": ("parse",),
    "传输": ("transport",),
    # measurement
    "门槛": ("threshold", "gate"),
    "成功率": ("success",),
    "重试": ("retry",),
    "复用": ("reuse",),
    "回执": ("receipt",),
    "基线": ("baseline",),
    "回归": ("regression",),
    "容差": ("tolerance",),
    "测量": ("measure",),
    "测试": ("test",),
    "单元": ("unit",),
    "断言": ("assert",),
    "证据": ("evidence",),
    "触发": ("trigger",),
    # project vocabulary
    "项目": ("project",),
    "仓库": ("repository", "repo"),
    "文档": ("document", "doc"),
    "架构": ("architecture",),
    "决策": ("decision",),
    "缺陷": ("bug",),
    "约定": ("convention",),
    "实验": ("experiment",),
    "任务": ("task",),
    "阶段": ("phase",),
    "边界": ("boundary",),
    "目标": ("target", "goal"),
    "计划": ("plan", "roadmap"),
    "依赖": ("dependency",),
    "性能": ("performance",),
    "延迟": ("latency",),
}


def expand_terms(terms: Sequence[str]) -> list[str]:
    """English terms implied by any Chinese term in ``terms``, deduplicated.

    Returns only the additions; the caller merges them after the original terms
    so an explicit identifier in the query keeps its priority.
    """
    additions: list[str] = []
    for term in terms:
        for english in GLOSSARY.get(term, ()):  # noqa: PERF401 - small, explicit
            if english not in additions:
                additions.append(english)
    return additions
