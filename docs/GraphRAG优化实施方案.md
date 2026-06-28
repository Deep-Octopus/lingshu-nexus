# GraphRAG 优化实施方案

> 基于 2026-06-24 系统现状分析
> 目标：从当前"关键词匹配查询"架构升级为 GraphRAG 分层检索架构

---

## 一、当前系统状态

### 1.1 已具备的能力

| 能力 | 实现位置 | 说明 |
|------|---------|------|
| LLM 实体/关系提取 | `extraction/service.py:99` | CandidateExtractionService 通过 LLM 提取 entities/relations/evidence_assertions |
| 结构化存储 | `persistence/graph.py` | InMemoryGraphRepository + Neo4jGraphRepository |
| 审校流水线 | `review/service.py` | 提取 → 术语标准化 → 人工 approve/reject → 发布 |
| 基础图查询 | `retrieval/service.py:73` | 关键词匹配节点 → 相邻边 → 打分排序 |
| 域路由 | `extraction/prompts.py` | 按 domain_id 加载不同提取提示词 |
| 多格式支持 | `documents/parsers.py` | PDF (pypdf) + Markdown |

### 1.2 当前图谱 Schema

```
GraphNode (概念节点)
  id:     "{domain}:{concept_type}:{text_hash}"
  label:  概念类型 (addictive_disorder, barrier, intervention, ...)
  properties: { text, concept_id, original_text }

GraphRelationship (关系边)
  type:   谓词类型 (treats, associated_with, related_to, ...)
  properties: { assertion_id, release_id, review_status }

EvidenceAssertion (证据断言)
  subject → predicate → object
  source_chunk_ids: ["chunk_0006", "chunk_0010"]
  extraction_confidence: 0.85
```

### 1.3 当前查询流程

```
query → 关键词 tokenize → 匹配节点 text → 找相邻边 → 返回断言列表
```

**缺陷**：
- 无法回答"what is X"定义性问题
- 无全局视野，只能返回匹配到的单个断言
- 论文中大量非断言型内容（背景、讨论、方法细节）无法被检索
- 无社区结构，丢失了跨文献的知识关联

---

## 二、优化目标

对标调研文档中推荐的 **LightRAG + Neo4j** 组合方案，分步实现：

| 目标 | 当前状态 | 目标状态 |
|------|---------|---------|
| 分块策略 | 无大小限制、无重叠 | 按 token 控制 + 重叠 |
| 查询方式 | 关键词匹配 | Local/Global 分层检索 |
| 答案形式 | 断言列表 + 引用 | LLM 合成答案 + 引用 |
| 全局问题 | 不支持 | 社区摘要支持 |
| 文档覆盖 | PDF/MD，表/图丢失 | 多格式 + 表结构保留 |
| 增量更新 | 不支持 | LightRAG 增量索引 |

---

## 三、分步实施方案

### 第 1 步：升级分块策略

**现状问题**：
- `_plain_text_paragraphs()` 仅按空行切分，无大小控制
- 无 chunk overlap，跨段落的语义可能被切断
- 参考文献段无标记，混入正文
- PDF 表格结构完全丢失
- `_build_user_prompt()` 无截断，可能超出 LLM 上下文窗口

**改动方案**：

```python
# parsers.py: 增强分块逻辑
# 1. 按空行切分后，合并相邻短段落直到接近 max_tokens (~2000)
# 2. 相邻 chunk 保持 ~10% 文本重叠
# 3. 检测 "References" / "参考文献" 标题，标记后续 chunk 为引用段
# 4. 对 pypdf 提取的文本做基础清洗（去页眉页脚重复模式）

# service.py: _build_user_prompt 增加 token 预算控制
# 1. 计算总 token 数，若超出限制则按 chunk_index 均匀采样
# 2. 优先保留前 1/3（通常含摘要和引言）+ 均匀采样后 2/3
```

**改动文件**：
- `backend/src/lingshu_nexus/documents/parsers.py` — 分块逻辑
- `backend/src/lingshu_nexus/documents/models.py` — chunk metadata 字段
- `backend/src/lingshu_nexus/extraction/service.py` — `_build_user_prompt` 截断策略

**预估工作量**：1-2 天

---

### 第 2 步：社区检测 + 摘要生成（核心）

**现状问题**：
- 图已构建但仅用于关键词匹配检索
- 没有利用图结构做知识聚合
- 无法回答全局性问题（"这个领域的主要研究方向是什么"）

**改动方案**：

```
现有流程:
  sync_active_release → write_release → 查询用关键词匹配

改为:
  sync_active_release → write_release → Leiden 社区检测
      → 生成社区摘要（LLM）
      → 社区摘要持久化
      → 查询时可检索社区摘要
```

**具体实现**：

1. **社区检测**（在 `graph.py` 或新增 `community.py`）：
   ```python
   # 使用 NetworkX + python-louvain 或 Neo4j GDS
   # 输入：当前 release 的所有节点和边
   # 输出：每个节点的 community_id

   def detect_communities(graph_nodes, graph_relationships):
       G = nx.Graph()
       for node in graph_nodes:
           G.add_node(node.id, **node.properties)
       for rel in graph_relationships:
           G.add_edge(rel.source_id, rel.target_id, type=rel.type)
       partition = community_louvain.best_partition(G)
       return partition  # {node_id: community_id}
   ```

2. **社区摘要生成**（新增 LLM 调用）：
   ```python
   # 对每个 community：
   #   收集该社区内所有断言的 source_chunk 原文
   #   LLM 生成该社区的摘要（主题、关键发现、代表文献）
   #   输出 CommunitySummary 数据结构

   def generate_community_summary(community_id, assertions, source_chunks):
       context = "\n\n".join(chunk.text for chunk in source_chunks)
       prompt = f"""
       以下文本来自一个研究主题社区，请生成一段简洁的摘要（200字以内），
       涵盖：核心概念、主要发现、涉及的研究方法。

       文本：
       {context}
       """
       return llm.complete(prompt)
   ```

3. **持久化**：
   - `CommunitySummary` 存入 `ObjectStore`（layer=COMMUNITY）
   - 图节点增加 `community_id` 属性
   - `GraphRelease` 增加 `community_ids` 字段

**新增数据结构**：

```python
@dataclass(frozen=True)
class CommunitySummary:
    id: str
    domain_id: str
    release_id: str
    community_id: int
    level: int  # 0=叶子社区, 1=中层, 2=根社区（全局摘要）
    title: str  # LLM 生成的社区标题
    summary: str  # LLM 生成的摘要文本
    key_concepts: tuple[str, ...]  # 核心概念术语
    assertion_ids: tuple[str, ...]  # 该社区的断言 ID
    source_document_ids: tuple[str, ...]  # 涉及的文献
```

**改动文件**：
- `backend/src/lingshu_nexus/persistence/graph.py` — 社区检测 + 存储
- `backend/src/lingshu_nexus/retrieval/service.py` — 社区摘要检索
- `packages/lingshu-domain/src/lingshu_domain/evidence.py` — CommunitySummary 类型
- 新增 `backend/src/lingshu_nexus/persistence/community.py` — 社区检测与摘要生成

**预估工作量**：2-3 天

---

### 第 3 步：替换查询引擎为 LightRAG

**现状问题**：
- `RetrievalService.search()` 仅做关键词匹配
- 无分层检索（Local/Global/Drift）
- 无增量索引

**改动方案**：

```
当前:
  query → RetrievalService.search() → 关键词匹配 → 断言列表

改为:
  query → LightRAG 引擎
      ├─ Local Search: 查询特定实体，返回精确断言 + chunk 原文
      ├─ Global Search: 查询社区摘要，回答宏观问题
      └─ Drift Search: 动态选择相关社区，兼顾精度和广度
```

**集成方式**（渐进式，不破坏现有系统）：

```python
# 新增 retrieval/lightrag_adapter.py
class LightRAGAdapter:
    def __init__(self, graph_repository, llm_provider):
        self._graph = graph_repository
        self._llm = llm_provider

    def local_search(self, query, domain_id):
        """检索特定实体的精确证据"""
        # 1. 在图中找到匹配节点
        # 2. 收集邻接断言 + source_chunk 原文
        # 3. LLM 合成答案 + 引用标注

    def global_search(self, query, domain_id):
        """检索社区摘要，回答宏观问题"""
        # 1. 匹配社区摘要中的关键词
        # 2. 收集相关社区的摘要文本
        # 3. LLM 合成答案

    def drift_search(self, query, domain_id):
        """混合检索"""
        # 1. Local Search 找到初始实体
        # 2. 从实体所在社区向外扩展
        # 3. 合并 local + community 结果
```

**Skill 层改动**（`skills/evidence-query/SKILL.md`）：

```markdown
Supported V2 query types:
- evidence_lookup     → Local Search
- parameter_summary   → Local Search
- safety_check        → Local Search
- global_review       → Global Search（新增）
- definition_lookup   → Local + Community Summary（新增）
```

**改动文件**：
- 新增 `backend/src/lingshu_nexus/retrieval/lightrag_adapter.py`
- `backend/src/lingshu_nexus/retrieval/service.py` — 集成 LightRAG
- `backend/src/lingshu_nexus/skills/service.py` — 新增 query type 路由
- `skills/evidence-query/SKILL.md` — 更新技能描述

**预估工作量**：3-5 天

---

### 第 4 步：补文档解析能力（按需）

**现状问题**：
- 仅支持 PDF 和 Markdown
- PDF 图片、表格结构完全丢失
- 与 GraphRAG 的 "原文 → 图 → 摘要" 三层检索不匹配

**改动方案**：

| 内容类型 | 当前 | 改为 | 工具 |
|---------|------|------|------|
| PDF 表格 | 乱码文本 | 结构化提取 | RAG-Anything / MinerU |
| 图片/图表 | 完全丢弃 | 提取为可引用对象 | RAG-Anything 多模态 |
| DOCX | 报错拒绝 | 支持解析 | python-docx / RAG-Anything |
| 参考文献 | 混入正文 | 检测+标记 | 正则匹配 "References" 标题 |

**预估工作量**：2-3 天（取决于选型）

---

## 四、推荐执行顺序与预期收益

```
第1步 分块优化 ──→ 第2步 社区检测+摘要 ──→ 第3步 LightRAG查询 ──→ 第4步 文档解析增强
   │                    │                        │                    │
   ▼                    ▼                        ▼                    ▼
减少LLM截断         解决"找不到证据"        解决"what is X"      解决表格/图片丢失
提升提取质量         覆盖非断言型内容         全局问题可回答        文档格式全覆盖

工作量: 1-2天       工作量: 2-3天            工作量: 3-5天         工作量: 2-3天
收益: ⭐⭐⭐         收益: ⭐⭐⭐⭐⭐          收益: ⭐⭐⭐⭐         收益: ⭐⭐
```

**第 1+2 步完成后，系统即可回答**：
- "what is non-integrated treatment model" → 从社区摘要中找到定义
- "这个领域有哪些主要研究方向" → 从根社区摘要回答
- "哪些因素与 opioid use disorder 治疗偏好相关" → 从相关社区的断言聚合

**第 3 步完成后**：
- 增量索引：新文献提交后自动纳入，无需重建索引
- 分层检索：根据问题类型自动选择 Local/Global 模式
- Token 成本大幅降低（LightRAG 仅为 GraphRAG 的 0.02%）

---

## 五、风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| 社区检测结果碎片化（太多小社区） | 摘要内容空洞 | 设置最小社区大小阈值（≥5 断言），小社区合并到父级 |
| LLM 社区摘要幻觉 | 检索到虚假信息 | 摘要必须关联 source_chunk_ids，查询时展示原文引用 |
| LightRAG 中文 Prompt 效果差 | 答案质量不高 | 参考 OpenTCM 中文模板，自行改写优化 |
| 社区摘要生成 Token 消耗大 | 成本上升 | 仅对活跃社区生成摘要，非活跃社区跳过；使用 DeepSeek 降低成本 |
| 现有系统接口破坏 | 查询不可用 | 所有改动采用 adapter 模式，不删除现有 `RetrievalService` |

---

## 六、可立即开始的工作

```bash
# 第1步 第一个任务：增强分块
# 修改 backend/src/lingshu_nexus/documents/parsers.py
# - 添加 chunk token count 控制
# - 添加 chunk overlap
# - 检测 References 段落

# 第2步 第一个任务：社区检测
# 新增 backend/src/lingshu_nexus/persistence/community.py
# - Leiden 社区检测（NetworkX + python-louvain）
# - 社区摘要生成（LLM 调用）
# - CommunitySummary 持久化
```

---

> **参考**: [GraphRAG与知识图谱技术调研及框架设计.md](./GraphRAG与知识图谱技术调研及框架设计.md)
> **选型**: LightRAG 主引擎 + KAG 逻辑推理 + Neo4j 存储
> **模型**: DeepSeek API（主力）+ GPT-4o（备选）
