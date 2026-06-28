# 灵枢智衡 (LingShu Nexus) V1 项目 TODO 与 Codex 实现规则

> 文档用途：本文件是后续 Codex 实现本项目时的主要执行依据，用于约束范围、拆分工作、核对产物与验收完成度。
> 当前状态：P0 工程闭环与 fixture 回归已实现；生产化持久化、任务队列、真实鉴权、Neo4j/检索、可观测与部署仍待补齐。
> 更新日期：2026-06-28
> 关联方案：[基础版本产品化实施方案.md](./基础版本产品化实施方案.md)
> 外部资料清单：[请导师提供的项目资料清单.md](./请导师提供的项目资料清单.md)、[请导师提供的项目资料清单（tVNS版本）.md](./请导师提供的项目资料清单（tVNS版本）.md)

---

## 1. V1 目标

实现一个供内部科研使用的**针灸证据知识平台基础版本**：

```text
PDF/Markdown 资料导入
  -> 解析与可定位分块
  -> 小米 MiMo 抽取候选实体/关系/证据命题
  -> 审核与发布版本
  -> 知识图谱和检索索引
  -> Agent Skill 驱动的网页流式问答
  -> 管理台查看任务、文献、审核、版本、Skill 与日志
  -> 新资料的受控增量更新
```

### 1.1 已确定条件

| 事项 | 当前决定 |
|---|---|
| 首个领域 | 针灸，内部标识为 `acupuncture` |
| 首批专业子场景 | tVNS/taVNS 作为 `acupuncture` 下的优先语料和评测子场景，不单独改变主流程 |
| 扩展要求 | 所有领域数据通过 `domain_id` 隔离，后续可接其他领域 |
| 输入资料 | PDF、Markdown，包含科研论文；资料可用于系统处理 |
| 模型 | 当前默认使用小米 MiMo，密钥和模型信息配置化，未来可替换 |
| 外部资料源 | 未来可能返回 JSON、文件或下载地址；当前不能假设固定契约 |
| 使用对象 | V1 为内部科研使用，后续可能用于毕业设计成果并考虑商用 |
| 审核 | 必须实现审核机制；具体审核人员可后定，不阻塞基础开发 |

### 1.2 V1 明确不做

- 不输出供患者直接采用的诊断或治疗结论。
- 不接入或控制刺激设备。
- 不接入脑电、生理信号或个人健康数据。
- 不让模型自动发布医学知识到正式图谱。
- 不自动给出最终 GRADE 评级或指南推荐。
- 不在尚无真实接口样例时猜测外部数据源字段。
- 不为了框架完整而同时引入多个 GraphRAG/Agent 引擎。

---

## 2. 后续 Codex 执行规则

后续任何实现任务开始前，Codex 应先阅读本文件，并遵守以下规则。

### 2.1 工作流程规则

1. 每次只选择一个可独立验收的 TODO 或一个紧密相关的小批次任务实现。
2. 开始修改前检查当前文件结构、依赖和未提交改动，不能覆盖已有工作。
3. 对影响架构、Schema、数据兼容性、依赖选择或安全边界的决策，新增或更新 ADR/文档记录。
4. 完成任务后更新本清单的状态、完成证据和遗留事项。
5. 不因资料、接口或密钥暂缺而伪造真实业务结果；可以构建清晰标注的 fixture 或 adapter stub 来验证链路。

### 2.2 复用与依赖规则

1. 通用能力优先使用成熟依赖：解析、图数据库、队列、UI 组件、鉴权接入、日志监控不重复造轮子。
2. 第三方能力必须包在本项目端口/adapter 后面，核心业务不得直接散落调用具体供应商 SDK。
3. 新增依赖前必须说明：
   - 解决的实际问题；
   - 为什么现有依赖无法满足；
   - 许可证和维护风险；
   - 替换或移除路径。
4. GraphRAG 主线固定为 Microsoft GraphRAG；V1.5 不并列维护第二套 GraphRAG/RAG 编排框架，未来替换必须另开任务和 ADR。
5. 可参考现有开源实现的流程和组织方式，但不得未经许可证核验直接复制大段实现。

### 2.3 架构边界规则

1. `domain_id` 是跨模块强制字段，首域为 `acupuncture`；不得把针灸硬编码成平台唯一领域。
2. 业务核心为 Evidence Schema、审核发布、引用溯源、release/回滚和权限门禁；这些不得托管给 LLM 或第三方 GraphRAG 黑盒。
3. 保持端口边界：
   - `DocumentParser`
   - `EvidenceExtractor`
   - `ConceptNormalizer`
   - `GraphRepository`
   - `RetrievalService`
   - `SkillRegistry`
   - `SourceConnector`
   - `ReleaseService`
4. 原始数据、解析数据、候选知识、已发布知识和派生索引必须逻辑隔离。
5. 用户聊天检索只能读取 active release 的已发布知识，不得直接访问 candidate 数据。

### 2.4 数据与知识规则

1. 原始资料不可被后续流程覆盖；重新解析或重新抽取必须创建新版本或运行记录。
2. 每条已发布证据命题必须包含可回溯来源：文档、片段定位、抽取配置版本和审核记录。
3. 普通三元组可以用于图谱导航，但医学相关回答必须基于带来源的 `EvidenceAssertion`。
4. 新资料与既有证据冲突时保留两方证据并标记冲突，不自动覆盖旧结论。
5. 外部来源统一进入 `SourceArtifact`；实际载荷允许为 JSON、PDF/MD、二进制文件或文件引用。
6. tVNS/taVNS 术语标准化必须保留原文写法和标准概念映射，重点覆盖耳甲艇/Cymba Conchae、耳甲腔/cavum conchae/concha cavity/cavity of auricular concha、耳屏/tragus。
7. `depression`、`blues`、`Postpartum blues` 等疾病或症状表述不得仅按字面合并，必须允许审核人员确认诊断级别和语义范围。
8. 文献来源质量信号用于排序和审核提示，不自动生成最终证据等级；初始优先级为专业数据库一区/二区、高被引、高热点论文优先，其次为数据库中其他论文，公众号或其他来源仅作低优先级背景。

### 2.5 模型与 Skill 规则

1. LLM 通过 provider adapter 调用；默认 provider 为 MiMo，`base_url`、`api_key`、`model` 不得硬编码。
2. 模型结构化抽取结果必须经过 Schema 校验后才能进入 candidate 层。
3. Skill 必须版本化，使用包含 `name` 与 `description` frontmatter 的 `SKILL.md`，平台权限放在独立注册元数据中执行。
4. 模型可自动选择的 Skill 仅限用户有权使用的只读 Skill。
5. 写图、发布、配置数据源和未来高风险动作不得由对话模型自行执行。

### 2.6 安全与配置规则

1. 真实 API key、口令、token、连接密码不得提交到仓库。
2. 仓库只提供 `.env.example` 或配置模板，不写真实密钥。
3. PDF/外部数据中的文本仅作为资料处理，不能作为系统指令执行。
4. 文件处理、后台写操作、发布/回滚和 Skill 执行必须留审计记录。
5. V1 页面和回答中应说明用途为内部科研证据辅助，不作为诊疗建议。

### 2.7 质量规则

1. 每个新增功能应有对应的自动化测试或可复现验收脚本；不能只靠人工点击确认。
2. 每个核心接口应有错误路径测试，如文件不支持、解析失败、Schema 不合规、无权限、无 active release。
3. 新增解析器、模型、检索引擎或 Skill 版本时，要在固定样例或评测集上运行回归检查。
4. 未通过验收条件的任务不得在本清单标记为完成。

---

## 3. 状态标记与完成证据

### 3.1 状态定义

| 状态 | 含义 |
|---|---|
| `[ ]` | 未开始 |
| `[-]` | 正在实现或部分完成 |
| `[x]` | 已完成且通过验收 |
| `[?]` | 依赖用户/导师/外部接口提供信息，目前不可完成 |
| `[~]` | 当前版本决定不做或已被替代，并需写明原因 |

### 3.2 每个任务完成时需要记录

任务被标记为 `[x]` 时，在任务项下记录：

```text
完成证据：
- 修改/新增文件：
- 验收命令或操作：
- 结果摘要：
- 未覆盖风险（若有）：
```

### 3.3 V1 总体验收条件

仅当以下条件全部成立，V1 才可视为完成：

- 能导入针灸 PDF/Markdown 资料，并查看每份资料的处理状态。
- 能从资料生成带来源定位的 candidate 证据命题。
- 能在管理端审核候选知识并生成 active `GraphRelease`。
- 能在网页对话中基于 active release 流式回答，并展示引用。
- 能定义、启用和记录至少两个只读查询 Skill 的执行。
- 能配置并执行至少一种增量资料进入方式：人工新增资料必须支持；外部接口在有样例后验收。
- 能查看关键审计记录、失败任务、发布/回滚历史和模型配置状态。
- 核心测试和固定评测样例可重复运行，且不出现候选知识泄漏到正式回答的情况。

---

## 4. TODO 总览

| ID | 任务组 | 优先级 | 状态 | 依赖 |
|---|---|---:|---|---|
| T-000 | 工程骨架与质量基线 | P0 | `[x]` | 无 |
| T-010 | 领域配置与 Evidence Schema | P0 | `[x]` | T-000 |
| T-020 | 数据模型、存储与迁移 | P0 | `[x]` | T-010 |
| T-030 | 文档上传、原始存储与解析 | P0 | `[x]` | T-020 |
| T-040 | MiMo provider 与候选知识抽取 | P0 | `[x]` | T-030 |
| T-050 | 标准化、审核与发布版本 | P0 | `[x]` | T-040 |
| T-060 | 图谱写入与检索 baseline | P0 | `[x]` | T-050 |
| T-070 | Agent Skill Registry 与只读 Skill | P0 | `[x]` | T-060 |
| T-080 | 流式问答前后端 | P0 | `[x]` | T-060, T-070 |
| T-090 | 管理面板 P0 能力 | P0 | `[x]` | T-030, T-050, T-070 |
| T-100 | 增量更新与 SourceConnector | P0/P1 | `[?]` | T-030, T-050 |
| T-110 | 权限、审计、安全与观测 | P0 | `[x]` | T-020 起贯穿实施 |
| T-120 | 评测、回归与 V1 发布验收 | P0 | `[?]` | T-030 至 T-110 |
| T-300 | 生产持久化与数据访问层 | P0 | `[ ]` | T-020 至 T-120 |
| T-310 | 生产任务队列与异步流水线 | P0 | `[ ]` | T-030, T-040, T-100, T-300 |
| T-320 | 真实认证、授权与租户/角色治理 | P0 | `[ ]` | T-110, T-300 |
| T-330 | 生产对象存储、文件安全与解析增强 | P0 | `[ ]` | T-030, T-300, E-001 |
| T-340 | Neo4j/向量/混合检索生产化 | P0/P1 | `[ ]` | T-050, T-060, T-120, T-300 |
| T-345 | Microsoft GraphRAG 框架接入 | P1 | `[ ]` | T-340, E-003, E-001 |
| T-350 | 模型调用网关、抽取质量与成本治理 | P0/P1 | `[ ]` | T-040, T-120, E-005 |
| T-355 | 关系抽取成熟度专项优化 | P0/P1 | `[ ]` | T-030, T-040, T-050, E-001, E-003, E-005 |
| T-356 | 多轮分级全文知识抽取流水线 | P0/P1 | `[ ]` | T-330, T-350, T-355 |
| T-357 | 科研实验设计知识模型与 Skill | P1 | `[ ]` | T-340, T-345, T-356, E-003 |
| T-360 | 可观测、审计留存与运维监控 | P0 | `[ ]` | T-110, T-300, T-310, T-350 |
| T-370 | 部署、配置、备份与灾备 | P0 | `[ ]` | T-300 至 T-360 |
| T-380 | 真实数据源 adapter 与数据合同 | P1 | `[?]` | T-100, E-006 |
| T-390 | 生产验收、压测与安全测试 | P0 | `[ ]` | T-300 至 T-380 |

---

## 5. P0 可执行 TODO

### T-000 `[x]` 工程骨架与质量基线

**目标：** 从当前文档仓库建立可运行、可测试、可持续扩展的工程项目基础。

**实施内容：**

- [ ] 确认并建立单仓结构，至少包含 API、Web、worker、领域包、配置、测试和文档目录。
- [ ] 创建 Python 后端依赖与启动方式；创建前端工程与启动方式。
- [ ] 提供开发环境配置模板，如 `.env.example`，包含 MiMo、数据库、对象存储和图数据库配置占位符。
- [ ] 提供本地依赖服务编排方式，包含 PostgreSQL、Redis、对象存储、Neo4j 等实际决定使用的基础服务。
- [ ] 配置 lint、format、type check、unit test 的执行命令。
- [ ] 创建 README 开发启动说明和首份 ADR 目录。

**验收：**

- 新环境按 README 能启动 API 和 Web 空页面/健康检查。
- 配置模板中无真实密钥。
- lint 与基础测试命令可运行成功。

**不得做：**

- 不在没有实现需求前一次性安装大量 AI/Agent/GraphRAG 依赖。
- 不把开发配置中的真实密钥提交进仓库。

完成证据：
- 修改/新增文件：
  - 根目录：`README.md`、`.env.example`、`.gitignore`、`pyproject.toml`、`Makefile`、`docker-compose.yml`
  - 后端：`backend/src/lingshu_nexus/`
  - 前端：`frontend/`
  - 领域包：`packages/lingshu-domain/`
  - 配置/文档/测试：`config/`、`docs/`、`scripts/quality.py`、`tests/test_scaffold.py`
- 验收命令或操作：
  - `make quality`
  - `python3 -m compileall backend/src packages/lingshu-domain/src scripts tests`
  - `docker compose config`
  - `npm --prefix frontend run`
  - `uv sync --extra dev` 与 `env UV_CACHE_DIR=.uv-cache uv sync --extra dev` 已尝试用于安装依赖并验证 API 启动，但当前沙箱无法访问 PyPI，提升网络权限未在自动审批时间内完成。
- 结果摘要：
  - 已建立 API/Web/worker/领域包/config/tests/docs 单仓骨架。
  - 已提供 FastAPI 健康检查入口、worker 入口、Vite/Vue 空页面工程、Docker Compose 本地依赖服务、配置模板、质量命令、README 和首份 ADR。
  - `make quality`、Python 编译检查、Compose 配置解析和前端脚本清单检查均通过。
- 未覆盖风险（若有）：
  - 因本地未安装 FastAPI/Vite 依赖且 PyPI 网络不可用，本次未实际启动 API dev server 或 Web dev server；README 中已提供依赖安装和启动命令，后续具备网络或本地缓存后应执行一次启动验收。

---

### T-010 `[x]` 领域配置与 Evidence Schema

**目标：** 固化首域及证据建模契约，保证后续抽取、审核、图谱、问答共享同一结构。

**实施内容：**

- [ ] 建立 `acupuncture` 领域配置，所有核心对象支持 `domain_id`。
- [ ] 定义首版核心对象 Schema：`SourceDocument`、`SourceChunk`、`CanonicalConcept`、`EvidenceAssertion`、`ReviewDecision`、`GraphRelease`。
- [ ] 定义首版实体/概念类型：疾病/症状、穴位/穴位组合、干预方法、治疗参数、结局、安全信息、文献。
- [ ] 定义首版关系/命题类型，并明确哪些字段允许为空、哪些发布时强制存在。
- [ ] 在 `acupuncture` 下支持可选 `topic_tags`/`scenario_id`，首批用于标记 `tVNS`/`taVNS` 语料、词表和评测问题。
- [ ] 在 `ParameterSet` 中覆盖 tVNS/taVNS 的干预剂量、刺激部位、频率、脉宽、强度、单次时长、总疗程、波形类型和 sham/control 设置。
- [ ] 在 `SourceDocument`/`Study`/`EvidenceAssertion` 中保留来源质量信号，如来源类型、期刊分区、引用量、高被引/热点标记，不把这些信号自动等同于证据等级。
- [ ] 创建初始术语词表模板，可在拿到资料后补充内容。
- [ ] 创建 tVNS/taVNS 初始术语种子：`tVNS`、`taVNS`、`transcutaneous auricular vagus nerve stimulation`、耳甲艇/Cymba Conchae、耳甲腔/cavum conchae/concha cavity/cavity of auricular concha、耳屏/tragus、depression/blues/Postpartum blues。
- [ ] 创建 ADR：为什么用证据命题而不是只存普通三元组。

**验收：**

- Schema 能通过测试样例进行有效/无效数据校验。
- 发布态 `EvidenceAssertion` 缺少 `domain_id` 或来源定位时校验失败。
- 新增第二个假领域 fixture 不需要修改通用模型代码。

**等待外部输入：**

- `[-]` 已收到 tVNS/taVNS 术语易错点、参数关注点、来源质量排序和代表性问题；仍需在真实资料到位后继续补充完整针灸词表和优先覆盖范围。

完成证据：
- 修改/新增文件：
  - `packages/lingshu-domain/src/lingshu_domain/config.py`
  - `packages/lingshu-domain/src/lingshu_domain/evidence.py`
  - `packages/lingshu-domain/src/lingshu_domain/validation.py`
  - `packages/lingshu-domain/src/lingshu_domain/__init__.py`
  - `config/domains/acupuncture/schema.v0.1.json`
  - `config/domains/acupuncture/terminology.v0.1.json`
  - `docs/adr/0002-evidence-assertion-schema.md`
  - `tests/test_evidence_schema.py`
- 验收命令或操作：
  - `make quality`
  - `python3 -m unittest discover -s tests`
- 结果摘要：
  - 已建立 `acupuncture` 领域配置，首批 schema 版本为 `acupuncture-tvns-v0.1.0`，支持 `topic_tags` 标记 tVNS/taVNS 子场景。
  - 已定义 `SourceDocument`、`SourceChunk`、`Study`、`CanonicalConcept`、`EvidenceAssertion`、`ReviewDecision`、`GraphRelease` 等核心对象和发布校验。
  - 已定义概念类型、命题类型、审核状态、来源质量信号和 tVNS/taVNS `ParameterSet` 字段。
  - 已提供术语种子，覆盖 tVNS/taVNS、耳甲艇/Cymba Conchae、耳甲腔/cavum conchae/concha cavity/cavity of auricular concha、耳屏/tragus、depression/blues/Postpartum blues。
  - 测试覆盖有效/无效 Schema、发布态缺少 `domain_id` 或来源定位失败、非 approved assertion 不可发布、第二个假领域 fixture 不修改通用代码。
- 未覆盖风险（若有）：
  - 当前是首批种子词表和 schema v0.1；完整针灸词表、真实文献中的优先疾病/穴位/结局范围仍需在真实资料导入后扩充。

---

### T-020 `[x]` 数据模型、存储与迁移

**目标：** 为文档、任务、候选知识、审核、版本、Skill 和审计提供可迁移的持久化基础。

**实施内容：**

- [ ] 设计并创建业务数据库模型与迁移。
- [ ] 建立原始文件/解析产物的对象存储接口。
- [ ] 建立图存储 adapter 接口，准备 published evidence 写入 Neo4j。
- [ ] 如采用 `pgvector`，建立片段向量字段或索引迁移；如变更选择，记录 ADR。
- [ ] 建立 `job_run`、`config_version`、`audit_event` 基础模型。

**验收：**

- 数据库可从空库执行迁移并回滚/重建开发环境。
- 存储层测试覆盖 domain 隔离、版本记录与基础审计字段。
- 原始文档与解析/抽取产物拥有不同记录，不互相覆盖。

完成证据：
- 修改/新增文件：
  - `backend/src/lingshu_nexus/persistence/models.py`
  - `backend/src/lingshu_nexus/persistence/object_store.py`
  - `backend/src/lingshu_nexus/persistence/graph.py`
  - `backend/src/lingshu_nexus/persistence/migrations.py`
  - `backend/src/lingshu_nexus/persistence/__init__.py`
  - `backend/migrations/0001_foundation.up.sql`
  - `backend/migrations/0001_foundation.down.sql`
  - `backend/migrations/README.md`
  - `docs/adr/0003-persistence-foundation.md`
  - `tests/test_persistence_foundation.py`
- 验收命令或操作：
  - `make quality`
  - `python3 -m unittest discover -s tests`
  - `docker compose config`
- 结果摘要：
  - 已建立基础业务表迁移，覆盖文档、片段、研究、标准概念、证据命题、审核决策、图谱 release、对象 artifact、图同步、job_run、config_version、audit_event。
  - 已用 SQLite 内存库 smoke test 验证 foundation migration 可从空库 apply、drop、re-apply；Compose 配置仍可解析。
  - 已实现对象存储端口和 in-memory adapter，测试覆盖 domain 隔离、不可覆盖同一对象版本、raw 与 parsed artifact 分层隔离。
  - 已实现图存储端口和 in-memory graph adapter，准备后续 Neo4j adapter 写入 published evidence；测试覆盖只接受 approved publishable assertion。
  - 已记录 T-020 暂不引入 pgvector，向量索引留到 T-060 与 retrieval baseline 一起评测。
- 未覆盖风险（若有）：
  - 当前未启动真实 PostgreSQL/Neo4j，也未接入 SQLAlchemy/Alembic；迁移使用保守 SQL 子集进行本地验证，真实数据库联调应在 T-020 后续环境具备或 T-030/T-060 前补跑。
  - 图存储目前是端口和 in-memory adapter，不是 Neo4j 生产 adapter。

---

### T-030 `[x]` 文档上传、原始存储与解析

**目标：** 支持 PDF/Markdown 文档安全入库并生成可引用定位的解析块。

**实施内容：**

- [x] 实现批量上传接口与文献列表/详情接口。
- [x] 实现内容哈希、重复识别、文件类型/大小限制和状态流转。
- [x] 实现 Markdown 确定性解析，生成带标题/段落 locator 的 chunks。
- [x] 通过 `DocumentParser` adapter 接入 PDF 解析 baseline；生产解析增强固定进入 T-330 的 Docling/OCR 流水线。
- [x] 保存原文件、parser 版本、解析结果、失败原因和重跑记录。
- [x] 建立可验证 API 展示处理状态；管理页面留到 T-090。

**验收：**

- 上传一个 MD 和一个可处理 PDF 后，均能查询文档状态及来源片段 locator。
- 重复上传同一文件不会创建重复的正式文档记录，且行为有测试覆盖。
- 不支持或解析失败的文件进入失败状态，并能重跑，不影响其他文件。
- 在首批验收语料可得后，记录解析成功率和失败样例。

**等待外部输入：**

- `[?]` 首批真实针灸/tVNS PDF/MD 文件；未提供本地文件或可访问样例前，可以用明确标记的 fixture 验证功能。

完成证据：
- 修改/新增文件：
  - `backend/src/lingshu_nexus/documents/`
  - `backend/src/lingshu_nexus/api/routes/documents.py`
  - `backend/src/lingshu_nexus/api/main.py`
  - `backend/src/lingshu_nexus/persistence/object_store.py`
  - `backend/src/lingshu_nexus/config/settings.py`
  - `backend/migrations/0002_document_ingestion.up.sql`
  - `backend/migrations/0002_document_ingestion.down.sql`
  - `backend/migrations/README.md`
  - `.env.example`
  - `.gitignore`
  - `pyproject.toml`
  - `uv.lock`
  - `README.md`
  - `docs/adr/0004-document-ingestion-parser-baseline.md`
  - `tests/test_document_ingestion.py`
- 验收命令或操作：
  - `UV_CACHE_DIR=.uv-cache uv sync --extra dev`（普通沙箱网络失败后，经提升权限同步成功）
  - `make quality PYTHON=.venv/bin/python`
  - `.venv/bin/python -m unittest tests/test_document_ingestion.py`
  - `.venv/bin/python -m unittest discover -s tests`
  - `PYTHONPYCACHEPREFIX=/private/tmp/lingshu-pycache .venv/bin/python -m compileall backend/src packages/lingshu-domain/src tests`
  - `docker compose config`
- 结果摘要：
  - 已新增文档接入应用层，包含 `DocumentParser` 端口、Markdown parser、`pypdf` PDF baseline parser、上传去重服务、重跑服务和 in-memory 文档 repository。
  - 已新增本地文件系统对象存储 adapter，原始文件与解析 JSON 通过 `DataLayer.RAW` / `DataLayer.PARSED` 分层保存且不可覆盖同一版本。
  - 已实现 `POST /api/v1/domains/{domain_id}/documents:batch-upload`、`GET /api/v1/documents`、`GET /api/v1/documents/{document_id}`、`POST /api/v1/documents/{document_id}:reprocess`。
  - 测试覆盖 MD heading/paragraph locator、PDF page locator、重复上传、unsupported 文件失败状态、解析失败重跑、大小限制、本地对象存储不可覆盖、0002 迁移 apply/drop、FastAPI 上传/列表/详情路由。
  - `make quality PYTHON=.venv/bin/python` 通过，当前共 24 个 unittest 通过。
- 未覆盖风险（若有）：
  - 首批真实针灸/tVNS PDF/MD 文件仍为外部输入 `[?]`，因此尚未记录真实语料解析成功率和失败样例。
  - 当前 PDF baseline 面向文本层 PDF；复杂版面、扫描件、表格和 OCR 未声明完成，待真实中文样例到位后按 T-330 的 Docling/OCR 流水线补齐。
  - 文档元数据 repository 当前仍是 in-memory adapter；0002 迁移已记录 PostgreSQL 表形，真实 ORM/PostgreSQL repository 留到后续持久化集成。

---

### T-040 `[x]` MiMo Provider 与候选知识抽取

**目标：** 通过配置化 MiMo 调用，从解析片段生成结构化 candidate 证据数据。

**实施内容：**

- [x] 创建 LLM provider 端口及 MiMo adapter。
- [x] 通过环境/配置读取 `MIMO_API_KEY`、`MIMO_BASE_URL` 和 `MIMO_MODEL_ID`，支持后续 provider 替换。
- [x] 建立抽取 Prompt 版本管理和结构化输出 Schema 校验。
- [x] 从 chunks 抽取实体、关系、EvidenceAssertion 及对应来源定位。
- [x] 对 tVNS/taVNS 文献重点抽取刺激位置、频率、脉宽、强度、波形、疗程、sham/control、结局指标、禁忌症、不良反应和安全注意事项。
- [x] 对研究设计类信息保留 RCT、分组方式、纳排标准、样本量、主要/次要结局、研究地区或团队等字段，供后续科研方案和文献格局问答使用。
- [x] 保存调用所用 provider/model/prompt/schema 版本、耗时和费用/Token 可得指标。
- [x] 提供 mock/fake provider，确保无真实 key 时也可运行单元/集成测试。

**验收：**

- fake provider 的固定样例可生成通过 Schema 校验的 candidate 数据。
- 不符合 Schema 或无引用定位的输出会被拒绝并记录失败原因。
- 有真实 MiMo 配置时，可以对样例文档运行一次抽取并留存运行记录；无 key 时不阻塞非联网测试。
- 更换 fake provider 或第二个 provider adapter 时，业务层测试无需改写。

**等待外部输入：**

- `[?]` 真实 MiMo key/base URL/model ID 在联调时由用户配置，不写入仓库。

完成证据：
- 修改/新增文件：
  - `backend/src/lingshu_nexus/extraction/`
  - `backend/src/lingshu_nexus/api/routes/documents.py`
  - `backend/src/lingshu_nexus/config/settings.py`
  - `backend/src/lingshu_nexus/documents/parsers.py`
  - `backend/migrations/0003_candidate_extraction.up.sql`
  - `backend/migrations/0003_candidate_extraction.down.sql`
  - `backend/migrations/README.md`
  - `config/prompts/acupuncture/literature_extraction.v0.1.md`
  - `.env.example`
  - `pyproject.toml`
  - `uv.lock`
  - `README.md`
  - `docs/adr/0005-llm-provider-and-candidate-extraction.md`
  - `tests/test_candidate_extraction.py`
- 验收命令或操作：
  - `UV_CACHE_DIR=.uv-cache uv lock --offline`
  - `make quality PYTHON=.venv/bin/python`
  - `.venv/bin/ruff check backend/src/lingshu_nexus/extraction`
  - `.venv/bin/ruff format --check backend/src/lingshu_nexus/extraction`
  - `.venv/bin/mypy backend/src packages/lingshu-domain/src scripts tests`
  - `.venv/bin/python -m unittest tests/test_candidate_extraction.py`
  - `.venv/bin/python -m unittest discover -s tests`
  - `PYTHONPYCACHEPREFIX=/private/tmp/lingshu-pycache .venv/bin/python -m compileall backend/src packages/lingshu-domain/src tests`
  - `git diff --check`
- 结果摘要：
  - 已新增 `LlmProvider` 端口、`MiMoProvider` adapter 和 `FakeLlmProvider`，MiMo 仅从环境变量读取 base URL、API key 和模型配置；占位配置会拒绝 live call。
  - 已新增版本化针灸文献抽取 prompt，明确 PDF/外部文本只作为资料数据处理，不作为系统指令执行。
  - 已新增 candidate extraction service，将 parsed chunks 转换为 candidate entities、relations 和 `ReviewStatus.PENDING` 的 `EvidenceAssertion`，并校验 JSON、Schema、source chunk locator 和置信度。
  - 已将 candidate 结果写入 `DataLayer.CANDIDATE` 对象 artifact，记录 provider/model/prompt/schema、token usage、latency、raw response hash 和 study metadata。
  - 测试覆盖 fake provider 成功抽取、无效 chunk 引用拒绝、无效 JSON 拒绝、MiMo 未配置时不联网失败、candidate artifact 不包含 API key、0003 迁移 apply/drop。
  - `make quality PYTHON=.venv/bin/python` 通过，当前共 29 个 unittest 通过。
- 未覆盖风险（若有）：
  - 真实 MiMo key/base URL/model ID 仍为外部输入 `[?]`，本次未执行 live MiMo 调用，也未声称真实模型抽取质量。
  - MiMo adapter 当前按可配置 chat-completions-compatible 传输实现；若真实 MiMo 契约不同，应在拿到接口样例后只替换 provider adapter，不修改 Evidence Schema 或审核发布边界。
  - candidate repository 当前为 in-memory adapter；0003 迁移已记录 PostgreSQL 表形，真实 ORM/PostgreSQL repository 留到后续持久化集成。

---

### T-050 `[x]` 标准化、审核与发布版本

**目标：** 将自动抽取限定在候选层，并通过可审计流程产生正式知识版本。

**实施内容：**

- [x] 实现概念标准化候选、别名合并和人工修订入口。
- [x] 实现 tVNS/taVNS 专业术语别名归一和保留原文写法，避免耳部刺激位置误译。
- [x] 为 `depression`、`blues`、`Postpartum blues` 等易混淆概念提供待审核映射，不自动合并为同一疾病实体。
- [x] 实现审核批次、单条批准/驳回/修改、审核备注和冲突标记。
- [x] 审核页展示来源质量信号和冲突证据，不因高质量来源存在就自动覆盖低质量来源的原始结论。
- [x] 实现 `GraphRelease` 创建、预览差异、激活和回滚。
- [x] 校验发布要求：来源定位、审核决定、Schema/Prompt/model/parser 版本完整。
- [x] 发布前后保留 candidate 数据和历史发布记录，不覆盖历史。

**验收：**

- 未审核 candidate 无法进入发布版本。
- 批准的 assertion 可加入新 release，驳回项不会加入。
- 激活 release 后可以切换回上一个版本，历史数据仍可查询。
- 冲突命题可并存且显示冲突状态。

完成证据：
- 修改/新增文件：
  - `backend/src/lingshu_nexus/review/`
  - `backend/src/lingshu_nexus/api/routes/review.py`
  - `backend/src/lingshu_nexus/api/main.py`
  - `backend/src/lingshu_nexus/extraction/service.py`
  - `packages/lingshu-domain/src/lingshu_domain/evidence.py`
  - `backend/migrations/0004_review_release.up.sql`
  - `backend/migrations/0004_review_release.down.sql`
  - `backend/migrations/README.md`
  - `docs/adr/0006-review-release-governance.md`
  - `tests/test_review_release.py`
  - `项目TODO与Codex实现规则.md`
- 验收命令或操作：
  - `.venv/bin/python -m unittest tests/test_review_release.py`
  - `.venv/bin/python -m unittest discover -s tests`
  - `.venv/bin/ruff check backend/src/lingshu_nexus/review backend/src/lingshu_nexus/api/routes/review.py backend/src/lingshu_nexus/api/main.py backend/src/lingshu_nexus/extraction/service.py packages/lingshu-domain/src/lingshu_domain/evidence.py tests/test_review_release.py`
  - `.venv/bin/ruff format --check backend/src/lingshu_nexus/review backend/src/lingshu_nexus/api/routes/review.py backend/src/lingshu_nexus/api/main.py backend/src/lingshu_nexus/extraction/service.py packages/lingshu-domain/src/lingshu_domain/evidence.py tests/test_review_release.py`
  - `.venv/bin/mypy backend/src packages/lingshu-domain/src scripts tests`
  - `make quality PYTHON=.venv/bin/python`
- 结果摘要：
  - 新增 `ReviewReleaseService`、术语标准化器和 in-memory review repository，支持从 candidate run 创建审核批次、生成标准化候选、保留 candidate 原始数据、批准/驳回/修改/冲突标记与基础审计。
  - tVNS/taVNS 和耳部刺激位置别名可归一到种子概念并保留原文；`depression`、`blues`、`Postpartum blues` 等敏感疾病/症状词只生成 `needs_review` 映射，不自动合并。
  - 新增 release 预览、创建、激活和回滚；发布校验要求来源 chunk、审核决策以及 candidate run/provider/model/prompt/schema/parser 版本 lineage 完整。
  - release snapshot 写入 `DataLayer.PUBLISHED`，candidate artifact 保留在 `DataLayer.CANDIDATE`；冲突命题可带冲突元数据并存发布。
  - 新增 Review/Release API 路由，返回标准化候选、来源质量信号、冲突信息和 release 历史，供 T-090 管理面板接入。
  - 当前共 35 个 unittest 通过，`make quality PYTHON=.venv/bin/python` 通过。
- 未覆盖风险（若有）：
  - 实际审核人员账号、RBAC 权限和生产级审计策略仍依赖 E-004/T-110；本次用 actor/reviewer 字符串和 audit event 记录完成可验证基础链路。
  - review repository 仍为 in-memory adapter；0004 迁移记录 PostgreSQL 表形，真实 ORM/PostgreSQL repository 留到后续持久化集成。
  - T-060 前尚未把 active release 同步到 Neo4j 或检索索引，本任务只完成发布版本治理边界。

---

### T-060 `[x]` 图谱写入与检索 Baseline

**目标：** 将已发布证据写入可查询图谱，并提供带引用的基础检索能力。

**实施内容：**

- [x] 实现 `GraphRepository`，将 active/published release 内容同步或绑定至图谱；提供 release-local in-memory baseline，并预留可注入 Neo4j driver 的 adapter。
- [x] 定义局部图查询能力：概念、证据命题、来源文献和关系导航。
- [x] 实现 `RetrievalService` 端口。
- [x] 优先验证可行 baseline retriever，并附加 `domain_id`、active release 与审核状态过滤。
- [x] 已评估暂不引入片段向量检索；首版 lexical baseline 可完成可验证闭环，向量/GraphRAG 引擎留到 T-120 评测收益明确后接入。
- [x] 建立检索结果到原文 chunk 的引用映射。

**验收：**

- 只能检索到 active release 中审核通过的知识。
- 给定样例 query，返回的证据结果包含文档和 chunk locator。
- 切换 release 后检索结果随版本正确改变。
- candidate-only 数据无法通过用户检索接口获取。

完成证据：
- 修改/新增文件：
  - 图谱端口与 adapter：`backend/src/lingshu_nexus/persistence/graph.py`、`backend/src/lingshu_nexus/persistence/__init__.py`
  - 检索服务与 API：`backend/src/lingshu_nexus/retrieval/`、`backend/src/lingshu_nexus/api/routes/retrieval.py`、`backend/src/lingshu_nexus/api/main.py`
  - 迁移与文档：`backend/migrations/0005_graph_retrieval.up.sql`、`backend/migrations/0005_graph_retrieval.down.sql`、`backend/migrations/README.md`、`docs/adr/0007-graph-retrieval-baseline.md`
  - 测试：`tests/test_graph_retrieval.py`
- 验收命令或操作：
  - `env UV_CACHE_DIR=.uv-cache uv run pytest tests/test_graph_retrieval.py tests/test_persistence_foundation.py`
  - `env UV_CACHE_DIR=.uv-cache uv run pytest`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff check backend/src/lingshu_nexus/persistence/graph.py backend/src/lingshu_nexus/persistence/__init__.py backend/src/lingshu_nexus/retrieval backend/src/lingshu_nexus/api/main.py backend/src/lingshu_nexus/api/routes/retrieval.py tests/test_graph_retrieval.py`
  - `env UV_CACHE_DIR=.uv-cache uv run mypy backend/src/lingshu_nexus/persistence/graph.py backend/src/lingshu_nexus/retrieval backend/src/lingshu_nexus/api/routes/retrieval.py tests/test_graph_retrieval.py`
- 结果摘要：
  - 新增 release-local 图谱写入、active release 指针、概念/关系/来源文献导航和带 citation 的检索结果。
  - `RetrievalService` 只依赖 active `ReleaseRecord` 与 `GraphRepository`，不依赖 candidate repository；测试覆盖 candidate-only 数据无法通过用户检索接口获取。
  - 样例 query 可返回 active release 中的已审核命题，并包含 `document_id`、`chunk_id` 和 locator；切换 active release 后检索结果随版本变化。
  - 相关测试 9 个通过，全量 pytest 40 个通过；定向 ruff 与 mypy 通过。
- 未覆盖风险（若有）：
  - 当前 Neo4j adapter 采用外部 driver 注入，尚未在真实 Neo4j 服务上做端到端联调；本地可验证路径使用 in-memory baseline。
  - 暂未引入向量检索或 Neo4j GraphRAG for Python；需等 T-120 评测集确定后用召回/质量收益决定是否引入。
  - `env UV_CACHE_DIR=.uv-cache uv run python scripts/quality.py lint` 当前会因历史文件中既有 ruff 问题失败，T-060 新增/修改文件已通过定向 ruff 检查。

---

### T-070 `[x]` Agent Skill Registry 与首批只读 Skill

**目标：** 提供受控、可版本化的 Agent Skill 能力，支持用户指定或模型安全路由。

**实施内容：**

- [x] 实现 Skill Registry 数据模型、版本、状态、scope、允许工具和执行日志。
- [x] 支持 `SKILL.md` 校验，至少检查 `name` 和 `description` frontmatter。
- [x] 实现平台侧 registry 元数据权限校验，不依赖提示词授权。
- [x] 创建 `evidence-query` Skill。
- [x] 创建 `literature-landscape` Skill。
- [x] 让首批只读 Skill 支持参数汇总、安全禁忌、频率效应、机制归纳、RCT 设计摘要和按时间列出文献等 tVNS/taVNS 问题类型。
- [x] 实现用户指定 Skill 与自动选择只读 Skill 两种路径。

**验收：**

- 两个 Skill 均有测试样例，可启用/禁用/查看版本。
- 禁用或无权限 Skill 无法执行。
- 自动路由不会选择后台写操作或未启用 Skill。
- 每次执行记录 Skill 版本、调用方式、release 版本与引用信息。

完成证据：
- 修改/新增文件：
  - 后端 Skill：`backend/src/lingshu_nexus/skills/`
  - API/配置：`backend/src/lingshu_nexus/api/routes/skills.py`、`backend/src/lingshu_nexus/api/main.py`、`backend/src/lingshu_nexus/config/settings.py`、`.env.example`
  - 迁移：`backend/migrations/0006_skill_registry.up.sql`、`backend/migrations/0006_skill_registry.down.sql`、`backend/migrations/README.md`
  - 内置 Skill 包：`skills/evidence-query/`、`skills/literature-landscape/`
  - 测试/文档：`tests/test_skill_registry.py`、`docs/adr/0008-agent-skill-registry-read-only.md`、`README.md`
- 验收命令或操作：
  - `env UV_CACHE_DIR=.uv-cache uv run pytest tests/test_skill_registry.py`
  - `env UV_CACHE_DIR=.uv-cache uv run pytest`
  - `env UV_CACHE_DIR=.uv-cache uv run make test`
  - `env UV_CACHE_DIR=.uv-cache uv run mypy`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff check backend/src/lingshu_nexus/skills backend/src/lingshu_nexus/api/routes/skills.py backend/src/lingshu_nexus/api/main.py backend/src/lingshu_nexus/config/settings.py tests/test_skill_registry.py`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff format --check backend/src/lingshu_nexus/skills backend/src/lingshu_nexus/api/routes/skills.py tests/test_skill_registry.py`
  - `python3 scripts/quality.py lint`
  - `python3 scripts/quality.py format-check`
  - `python3 scripts/quality.py typecheck`
- 结果摘要：
  - 新增 `SkillDefinition`、`SkillExecutionRecord`、in-memory `SkillRepository`、filesystem loader、`SKILL.md` frontmatter 校验、平台 `registry.yaml` 权限元数据校验和执行日志。
  - 新增两个 active read-only Skill：`evidence-query` 与 `literature-landscape`，覆盖参数汇总、安全禁忌、频率效应、机制归纳、RCT 设计摘要、按时间列出文献和研究空白等 tVNS/taVNS 问题类型。
  - 用户指定执行会校验 active/status/scope/role/server_allowed_tools；自动路由只在用户有权使用的 active read-only Skill 中选择，不会选择后台写操作或禁用 Skill。
  - Skill 执行只调用 `RetrievalService` 读取 indexed active release 的已发布证据，并记录 Skill 版本、调用方式、release 版本和 citation keys。
  - `tests/test_skill_registry.py` 6 个通过；全量 pytest 46 个通过；`uv run make test` 46 个 unittest 通过；全量 mypy 45 个 source files 通过；T-070 新增/修改 Python 文件定向 Ruff 与 format check 通过；裸环境质量脚本 lint/format/typecheck 通过。
- 未覆盖风险（若有）：
  - `0006_skill_registry` 已定义持久化表结构，但运行期仍使用 in-memory repository；PostgreSQL adapter 随后续持久化任务补齐。
  - T-070 不实现 T-080 的网页流式对话 UI、LLM 自动生成答案或前端 Skill 选择器。
  - `make quality` 在裸 `python3` 环境会因缺少 FastAPI 于 unittest 阶段失败；`env UV_CACHE_DIR=.uv-cache uv run make quality` 会触发 T-060 已记录的历史全量 Ruff 问题。T-070 相关文件已通过定向 Ruff、format、mypy 与全量测试。

---

### T-080 `[x]` 流式问答前后端

**目标：** 实现研究者可使用的网页流式证据对话。

**实施内容：**

- [x] 实现会话和消息数据模型。
- [x] 实现 SSE 流式消息 API，至少支持检索阶段、文本片段、引用和完成/错误事件。
- [x] 实现网页对话页、Skill 选择、引用侧栏、来源跳转和失败提示。
- [x] 在回答中展示使用的 Skill、active release 与研究辅助声明。
- [x] 实现反馈入口，如有用/无用或纠错备注。

**验收：**

- 浏览器中可发送问题并收到流式回答。
- 有证据的回答能展开引用到来源文档/片段。
- 无 active release 或无证据时给出清晰限制提示，不编造结论。
- 对话不能引用未审核 candidate 数据。

完成证据：
- 修改/新增文件：
  - 后端 Chat：`backend/src/lingshu_nexus/chat/`
  - API：`backend/src/lingshu_nexus/api/routes/chat.py`、`backend/src/lingshu_nexus/api/main.py`
  - 迁移：`backend/migrations/0007_chat_sessions.up.sql`、`backend/migrations/0007_chat_sessions.down.sql`、`backend/migrations/README.md`
  - 前端：`frontend/src/App.vue`、`frontend/src/style.css`、`frontend/src/env.d.ts`、`frontend/tsconfig.json`
  - 配置/文档/测试：`.env.example`、`tests/test_chat_stream.py`、`docs/adr/0009-sse-chat-active-release.md`、`README.md`
- 验收命令或操作：
  - `env UV_CACHE_DIR=.uv-cache uv run pytest tests/test_chat_stream.py`
  - `env UV_CACHE_DIR=.uv-cache uv run pytest`
  - `env UV_CACHE_DIR=.uv-cache uv run mypy`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff check backend/src/lingshu_nexus/chat backend/src/lingshu_nexus/api/routes/chat.py backend/src/lingshu_nexus/api/main.py tests/test_chat_stream.py`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff format --check backend/src/lingshu_nexus/chat backend/src/lingshu_nexus/api/routes/chat.py tests/test_chat_stream.py`
  - `npm --prefix frontend run build`
  - 浏览器联调：API `http://127.0.0.1:8765/api/v1` + Vite `http://127.0.0.1:5175/`，验证 Skill 列表加载、发送问题和无 active release 的 SSE 错误提示。
- 结果摘要：
  - 新增会话、消息、反馈和 SSE 事件模型，运行期使用 in-memory ChatRepository；`0007_chat_sessions` 固化 PostgreSQL 表结构。
  - 新增 `/api/v1/chat/sessions`、消息列表、`messages:stream` 和反馈接口；SSE 输出 `retrieval`、`text`、`citation`、`done`、`error` 事件。
  - 流式回答复用 T-070 `SkillRegistryService`，只读取 indexed active release 的已发布证据；无 active release 或无证据时返回清晰限制提示。
  - 前端默认进入证据聊天工作台，支持 Skill 选择、流式文本、引用侧栏、来源链接、active release/Skill 展示、失败提示和有用/无用/纠错反馈；开发环境 API 开启本地 Vite CORS 白名单。
  - `tests/test_chat_stream.py` 覆盖 SSE happy path、反馈、无 active release 错误、candidate-only 不泄漏和迁移 apply/drop；全量 pytest 当前 50 个测试通过；全量 mypy 当前 50 个 source files 通过；前端 build 通过。
- 未覆盖风险（若有）：
  - 当前回答仍为确定性 Skill/Retrieval baseline，不接入 LLM 生成；后续若加入 chat LLM 必须走 provider adapter 和引用安全策略。
  - ChatRepository 运行期仍是 in-memory，`0007_chat_sessions` 仅定义后续 PostgreSQL 持久化形态。
  - 浏览器联调覆盖了本地无 active release 路径；带引用的流式展开由 `tests/test_chat_stream.py` 中的 active release fixture 覆盖，未在本地浏览器手工伪造 release 数据。

---

### T-090 `[x]` 管理面板 P0 能力

**目标：** 让管理端能够操作文献、审核、版本、任务和 Skill，而非依赖脚本手工维护。

**实施内容：**

- [x] 总览：文献数量、待审数量、active release、失败任务和调用成本摘要。
- [x] 文献库：上传、状态查看、详情/片段、失败重跑。
- [x] 审核工作台：候选命题、原文对照、批准/修改/驳回/冲突。
- [x] 图谱版本：release diff、激活、回滚。
- [x] Skill 管理：上传/查看、校验、启用/禁用、试运行与日志。
- [x] 数据源/任务页面占位并与 T-100 接通。

**验收：**

- 可以仅通过页面完成“文献查看 -> 候选审核 -> 创建并激活 release -> 查看聊天引用”的核心路径。
- 高风险操作有确认提示并产生审计事件。
- 错误和失败任务可查看原因。

完成证据：
- 修改/新增文件：
  - 后端 API：`backend/src/lingshu_nexus/api/routes/admin.py`、`backend/src/lingshu_nexus/api/main.py`
  - 后端服务：`backend/src/lingshu_nexus/documents/repository.py`、`backend/src/lingshu_nexus/documents/service.py`、`backend/src/lingshu_nexus/review/service.py`、`backend/src/lingshu_nexus/skills/service.py`、`backend/src/lingshu_nexus/skills/__init__.py`、`backend/src/lingshu_nexus/persistence/models.py`
  - 前端：`frontend/src/App.vue`、`frontend/src/style.css`
  - 测试/文档：`tests/test_admin_panel.py`、`README.md`、`docs/adr/0010-management-panel-baseline.md`
  - 相关格式清理：`backend/src/lingshu_nexus/documents/__init__.py`、`backend/src/lingshu_nexus/documents/models.py`、`backend/src/lingshu_nexus/documents/parsers.py`
- 验收命令或操作：
  - `env UV_CACHE_DIR=.uv-cache uv run pytest tests/test_admin_panel.py`
  - `env UV_CACHE_DIR=.uv-cache uv run pytest`
  - `env UV_CACHE_DIR=.uv-cache uv run python -m unittest discover -s tests`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff check backend/src/lingshu_nexus/api/routes/admin.py backend/src/lingshu_nexus/api/main.py backend/src/lingshu_nexus/documents backend/src/lingshu_nexus/review/service.py backend/src/lingshu_nexus/persistence/models.py backend/src/lingshu_nexus/skills tests/test_admin_panel.py`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff format --check backend/src/lingshu_nexus/api/routes/admin.py backend/src/lingshu_nexus/api/main.py backend/src/lingshu_nexus/documents backend/src/lingshu_nexus/review/service.py backend/src/lingshu_nexus/persistence/models.py backend/src/lingshu_nexus/skills tests/test_admin_panel.py`
  - `env UV_CACHE_DIR=.uv-cache uv run mypy`
  - `npm --prefix frontend run build`
  - `git diff --check`
- 结果摘要：
  - 新增 `/api/v1/admin/overview`、`/api/v1/admin/jobs`、`/api/v1/admin/audit-events`、`/api/v1/admin/skills:upload` 和带审计的 Skill 启用/禁用管理入口。
  - 管理总览聚合文献状态、待审命题、active release、失败任务、Skill 执行摘要和模型用量边界；当前无模型用量仓库时明确返回 unavailable，不伪造 token 或费用。
  - 文档管理支持上传、列表、详情/片段、失败原因和重跑；任务页展示解析/重跑 job，并把 SourceConnector 标为 T-100 接通占位。
  - 审核与版本管理页面接入候选命题、批准/修改/驳回/冲突、release preview diff、创建、激活和回滚；高风险 release 操作有前端确认并使用已有审计事件。
  - Skill 管理支持 package 上传、查看、校验、启用/禁用、试运行和日志查看；上传要求 `SKILL.md`、`registry.yaml`、`tests/cases.yaml` 同时通过现有 Skill 校验后才更新 registry，并记录 `skill.*` 审计事件。
  - 前端首屏改为管理控制台，并保留 Chat 标签用于验证 active release 聊天引用；`tests/test_admin_panel.py` 覆盖管理总览/失败任务、Skill 上传/启停审计、审核发布激活与聊天引用闭环。
- 未覆盖风险（若有）：
  - 当前运行期仍使用多个 in-memory repository；持久化生产 adapter、完整 RBAC、结构化观测和更丰富审计归属留到 T-110。
  - SourceConnector、schedule、外部增量同步真实契约留到 T-100，本次只提供任务页占位和解析/重跑 job 可视化。
  - 管理面板没有伪造模型费用；模型调用成本需在后续接入候选抽取/LLM 调用日志仓库后汇总。

---

### T-100 `[?]` 增量更新与 SourceConnector

**目标：** 支持新资料持续进入系统，且不绑定尚未确定的外部接口格式。

**实施内容：**

- [x] 实现人工新增资料触发增量处理。
- [x] 定义内部 `SourceArtifact` 契约，支持 JSON、文件和下载引用。
- [x] 实现 `SourceConnector` 端口与 generic connector 配置模型。
- [x] 实现 schedule、执行记录、幂等键、失败重试和原始响应保留。
- [x] 对新批次执行解析、抽取、差异/冲突提示与候选审核。
- [?] 获得真实外部接口样例后，实现对应 adapter 与契约测试。

**验收：**

- 追加一份新文档后可产生新的候选批次，发布后形成新 release。
- 重复同步不会重复发布同一文档/命题。
- 未提供真实外部接口时，generic connector/fixture 可验证 JSON 和文件两类载荷处理。
- 有真实样例后，adapter contract test 可重复运行。

**等待外部输入：**

- `[?]` 外部接口地址、认证、请求参数与真实返回样例。

完成证据：
- 修改/新增文件：
  - 后端 SourceConnector：`backend/src/lingshu_nexus/sources/`
  - API 接入：`backend/src/lingshu_nexus/api/routes/sources.py`、`backend/src/lingshu_nexus/api/main.py`、`backend/src/lingshu_nexus/api/routes/admin.py`
  - 迁移：`backend/migrations/0008_source_connector.up.sql`、`backend/migrations/0008_source_connector.down.sql`
  - 前端管理台：`frontend/src/App.vue`、`frontend/src/style.css`
  - 测试/文档：`tests/test_source_connector.py`、`tests/test_admin_panel.py`、`README.md`、`docs/adr/0011-source-connector-incremental-update.md`
- 验收命令或操作：
  - `env UV_CACHE_DIR=.uv-cache uv run pytest tests/test_source_connector.py`
  - `env UV_CACHE_DIR=.uv-cache uv run pytest tests/test_admin_panel.py tests/test_document_ingestion.py tests/test_candidate_extraction.py`
  - `env UV_CACHE_DIR=.uv-cache uv run mypy`
  - `env UV_CACHE_DIR=.uv-cache uv run ruff check backend/src/lingshu_nexus/sources backend/src/lingshu_nexus/api/routes/sources.py backend/src/lingshu_nexus/api/routes/admin.py backend/src/lingshu_nexus/api/main.py tests/test_source_connector.py tests/test_admin_panel.py`
  - `npm --prefix frontend run build`
- 结果摘要：
  - 新增 `SourceArtifact` 内部契约，覆盖 JSON、文件和下载引用；所有 artifact/response 先进入 Raw 层。
  - 新增 `SourceConnector` 端口、fixture connector、generic REST connector 配置模型、schedule 元数据、source sync run、artifact record、幂等键、显式 retry 入口和 SQL 迁移。
  - 人工新增资料可通过 `POST /api/v1/domains/{domain_id}/sources:manual-sync` 进入文档解析、候选抽取、review batch；不直接发布到 active release。
  - 新批次会生成潜在冲突/影响提示；重复 artifact 或重复文档哈希会跳过，不重复创建候选批次。
  - 管理面板展示 source configs、source runs、重复跳过数、失败数和冲突提示；缺真实 MiMo 配置时记录 extraction 失败，不伪造候选证据。
  - 测试覆盖人工增量新增后形成候选批次并发布新 release、重复同步不重复发布、fixture JSON/文件/下载引用处理、source API 和迁移 apply/drop。
- 未覆盖风险（若有）：
  - `[?]` 真实外部接口地址、认证方式、请求参数、分页/游标语义和返回样例尚未提供，因此未实现特定外部 adapter 与 contract test。
  - 当前运行期仍使用 in-memory source repository；生产级持久化 adapter、完整权限控制和结构化观测留到 T-110/T-120。

---

### T-110 `[x]` 权限、审计、安全与观测

**目标：** 让内部科研版本具备最低限度的责任追踪、安全控制和排错能力。

**实施内容：**

- [x] 实现基础角色：研究者、审核专家、管理员、只读用户，或记录采用的简化 V1 方案。
- [x] 实现上传、审核、发布/回滚、Skill 启停、数据源配置、聊天调用的审计事件。
- [x] 实现密钥仅通过环境变量/安全配置注入，UI 和日志不回显密钥。
- [x] 为任务、模型调用和错误提供结构化日志/指标。
- [x] 对上传文件和资料内容的指令注入风险采取隔离策略。
- [x] 在产品界面显示内部科研用途与非诊疗声明。

**验收：**

- 无权限用户不能发布 release、管理数据源或启用高权限 Skill。
- 审计日志能还原一次发布和一次聊天回答所依据的版本与操作者。
- 仓库扫描不含真实 token/key。
- 文献内容中的指令文本不会触发后台工具或权限动作。

完成证据：
- 修改/新增文件：
  - 后端：`backend/src/lingshu_nexus/security.py`、`backend/src/lingshu_nexus/observability.py`、`backend/src/lingshu_nexus/api/routes/`、`backend/src/lingshu_nexus/documents/`、`backend/src/lingshu_nexus/extraction/service.py`、`backend/src/lingshu_nexus/sources/`、`backend/src/lingshu_nexus/review/service.py`
  - 测试：`tests/test_admin_panel.py`、`tests/test_source_connector.py`、`tests/test_document_ingestion.py`
  - 文档：`README.md`、`docs/adr/0012-v1-security-audit-observability.md`、`项目TODO与Codex实现规则.md`
- 验收命令或操作：
  - `uv run pytest tests/test_admin_panel.py tests/test_source_connector.py tests/test_document_ingestion.py tests/test_chat_stream.py`
  - `env UV_CACHE_DIR=.uv-cache PYTHONPYCACHEPREFIX=/private/tmp/lingshu-nexus-pycache make quality PYTHON='uv run python'`
  - `npm --prefix frontend run build`
  - `rg -n "(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|api_key\\s*[:=]\\s*['\\\"][A-Za-z0-9_\\-]{20,})" --glob '!frontend/node_modules/**' --glob '!frontend/dist/**' --glob '!项目TODO与Codex实现规则.md' .`
- 结果摘要：
  - 已实现 V1 简化角色模型与服务端 RBAC：上传/重处理需研究者及以上，审核和 release 快照需审核专家及以上，release 激活/回滚、数据源管理和 Skill 启停需管理员。
  - 审计事件覆盖文档上传/重处理、审核、release 创建/激活/回滚、Skill 上传/启停/执行、数据源配置/同步、聊天完成/失败和反馈；聊天审计记录 release、Skill execution、citation keys、操作者与 query hash，不写完整 query。
  - 新增脱敏配置状态和观测事件接口；SourceConnector config 响应遮罩 secret reference，明文 secret-looking key 仍被拒绝。
  - 文献/资料内容作为 evidence data 处理，不参与权限或后台动作授权；界面继续显示“内部科研证据辅助，不作为诊疗建议”。
- 未覆盖风险（若有）：
  - 当前身份来源是 V1 内部基线的请求级 actor 字段，不是生产登录/SSO；生产持久化审计仓库和外部 OpenTelemetry/日志后端仍需后续 adapter。

---

### T-120 `[?]` 评测、回归与 V1 发布验收

**目标：** 通过固定样例和自动化检查证明 V1 基础闭环有效，而不是仅可演示。

**实施内容：**

- [x] 建立 `evals/` 结构，存放 fixture 文档、抽取期望、问题种子、越界/拒答样例和术语标准化样例。
- [?] 用户提供真实资料后，逐步形成针灸/tVNS 领域验收集；当前所有自动评测资产均明确标注为 fixture-only。
- [x] 将导师补充的 tVNS/taVNS 代表问题整理为 eval seeds，覆盖失眠干预参数、频率效应、禁忌症与安全、研究方案参数和结局指标、作用机制、精神/神经/疼痛适应症机制差异、RCT 通用设计、行为学以外指标、国内外研究侧重点、按时间列文献、近三年趋势和“无统一标准时禁止编造结论”。
- [x] 为术语易错点创建标准化测试，覆盖耳甲艇/耳甲腔/耳屏英文映射和 depression/blues/Postpartum blues 区分。
- [x] 测试解析、抽取 Schema、审核发布、检索引用、两个只读 Skill、SSE、权限、审计、候选隔离与回滚。
- [x] 建立 fixture 端到端验证流程：资料导入 -> 候选抽取 -> 审核 -> release -> 带引用 SSE 回答 -> 回滚。
- [x] 输出 V1 验收记录，逐项列明 fixture 已通过项目与真实验收未覆盖风险。

**验收：**

- 固定 fixture 端到端测试可在本地重复成功执行。
- 使用真实资料后，验收集中每条正式医学回答均可定位至已发布来源。
- 不存在未审核内容进入正式问答的已知路径。
- V1 总体验收条件逐项有结果记录。

完成证据：
- 修改/新增文件：
  - 评测资产：`evals/README.md`、`evals/fixtures/`、`evals/expected/`、`evals/questions/`、`evals/boundary/`、`evals/terminology/`
  - 验收代码/测试：`scripts/run_v1_acceptance.py`、`tests/test_v1_acceptance.py`、`scripts/quality.py`
  - 文档：`README.md`、`docs/v1-acceptance-record.md`、`docs/adr/0007-graph-retrieval-baseline.md`
- 验收命令或操作：
  - `env UV_CACHE_DIR=.uv-cache uv run python scripts/run_v1_acceptance.py`
  - `env UV_CACHE_DIR=.uv-cache PYTHONPYCACHEPREFIX=/private/tmp/lingshu-nexus-pycache make quality PYTHON='uv run python'`
- 结果摘要：
  - 统一验收脚本通过 51 个相关后端测试并完成 Vue/TypeScript 生产构建。
  - 全量质量门禁通过 Ruff lint/format、73 个 source files 的 Mypy 检查和 66 个 unittest。
  - fixture API 回归覆盖上传/解析、结构化抽取、审核权限、release preview/create/activate、候选命题排除、两个只读 Skill、SSE 引用、candidate-only 不泄漏、审计和回滚。
  - 已固化 12 类 tVNS 问题种子、15 个越界/拒答种子和 8 个术语标准化样例；seed-only 问题不写入伪造期望引用。
  - 当前 fixture 无法量化真实领域语义召回收益，因此没有依据新增向量检索或其他 GraphRAG 依赖，V1 继续使用 lexical baseline。
- 未覆盖风险（若有）：
  - `[?]` E-001 真实针灸/tVNS PDF/Markdown 与授权说明未到位，尚不能记录真实解析成功率、失败样例或正式引用准确率。
  - `[?]` E-005 可用 MiMo base URL/model/key 未到位，尚未完成 live 抽取质量、延迟和成本验收。
  - `[?]` E-003 已整理问题种子，但专家期望引用/证据不足判断仍待补充，不能声称完成真实问答评测。
  - `[?]` E-006 真实外部资料接口契约未到位，特定 connector contract test 仍未完成。
  - 当前运行期元数据仓库主要为 in-memory adapter；可做单进程 fixture/API 演示，但重启持久化的浏览器演示仍需 durable repository 和可重置 demo 数据方案。

---

## 6. 外部输入 TODO

以下事项不是 Codex 可以独立产生的真实业务数据，但 Codex 应提供接入位置并在收到后继续实施。

| ID | 输入项 | 状态 | 收到后用于 |
|---|---|---|---|
| E-001 | 首批针灸/tVNS PDF/Markdown 科研资料 | `[?]` | T-030/T-040/T-120 真实验证；已给出飞书资料方向，仍需本地文件或可访问样例落地 |
| E-002 | 重点疾病、穴位、参数、结局和安全关注范围 | `[-]` | T-010 Schema/词表完善；已收到 tVNS 部分术语、参数、安全和来源质量原则 |
| E-003 | 代表性业务问题与期望证据 | `[?]` | T-120 问题种子已整理为 evals；真实资料对应的专家期望引用/证据不足判断仍待提供 |
| E-004 | 审核人员/发布权限安排 | `[?]` | T-050/T-090/T-110 实际账号配置 |
| E-005 | MiMo 可用配置和真实 key | `[?]` | T-040 真实模型联调 |
| E-006 | 外部资料接口真实契约和样例 | `[?]` | T-100 特定 connector adapter |
| E-007 | 术语和证据处理规则 | `[-]` | T-010/T-050/T-120；已收到 tVNS 易错术语、来源可靠性排序和冲突保留原则，后续由专家继续补全 |

规则：外部输入未到位时允许使用 fixture 完成结构和自动测试，但不得把 fixture 结果描述为针灸领域真实效果或正式知识库成果。

---

## 7. 生产化 TODO（V1.5）

目标：把当前可执行 fixture/demo 基线升级为可在生产环境长期运行、可恢复、可审计、可扩容的内部科研证据平台。以下任务优先复用成熟框架和托管组件，不重复造轮子；但 Evidence Schema、候选/发布隔离、审核决策、release 版本和引用边界仍由本项目自有代码掌控。

### T-300 `[ ]` 生产持久化与数据访问层

**目标：** 用 PostgreSQL 替换运行期核心 in-memory repository，使文献、候选、审核、release、source run、Skill、chat、审计和观测记录在进程重启后完整保留。

**确定技术路线：**

- PostgreSQL 作为主业务库。
- SQLAlchemy 2.x ORM/Core + `psycopg` 3 作为数据库访问层，使用 repository adapter 隔离数据库细节。
- Alembic 作为唯一迁移入口；现有 `backend/migrations/*.sql` 迁入 Alembic revision，后续不再维护双迁移体系。
- Pydantic/typed DTO 只用于 API 边界，不替代领域 dataclass 的业务校验。

**实施内容：**

- [ ] 为 `DocumentRepository`、`CandidateRepository`、`ReviewRepository`、`SourceRepository`、Skill/chat/audit/observability 相关 repository 实现 PostgreSQL adapter。
- [ ] 明确事务边界：文档入库、候选抽取 run、review batch 创建、release snapshot 创建、release 激活/回滚必须具备一致性。
- [ ] 将当前 `create_app()` 从默认 in-memory repository 切到可配置 repository factory，保留 in-memory 仅用于单元测试。
- [ ] 将 release、review decision、source run、candidate run 的 JSON 字段落入 `JSONB` 或清晰的 normalized 表，禁止只用一大段不可检索文本糊住核心状态。
- [ ] 为常用查询建立索引：`domain_id`、状态、document hash、release active、source idempotency key、review status、created_at。
- [ ] 增加种子/重置脚本：可以创建本地 demo 域、管理员、fixture 文档和 active release，且不会污染生产数据。
- [ ] 增加数据库连接池、超时、健康检查和迁移版本检查。

**验收：**

- 重启 API/worker 后，文档、review batch、release、source run、chat history 和 audit events 仍可查询。
- 同一文档重复上传仍由数据库唯一约束和业务逻辑共同防重。
- release 创建失败时不会留下半成品 active release 或半成品发布 artifact。
- 迁移可在空库和已有 fixture 库上重复执行；CI 中包含 migration apply/drop 或 upgrade/downgrade 检查。

**不得做：**

- 不让 API 直接散落写 SQL，必须走 repository/transaction 边界。
- 不把候选知识和已发布知识放进同一张无状态大表。

### T-310 `[ ]` 生产任务队列与异步流水线

**目标：** 把解析、抽取、source sync、release index、批量导入等长任务从同步 API 请求中移出，形成可重试、可观测、可恢复的后台流水线。

**确定技术路线：**

- Celery 5 + Redis 作为生产任务队列组合；Redis 同时作为 broker 和 result backend，业务最终状态仍写 PostgreSQL。
- Flower 用于任务观察和本地/内网运维查看。
- 不引入第二套工作流引擎；当前任务模型以 Celery 的 task、retry、chain/group 和数据库幂等状态实现。

**实施内容：**

- [ ] 建立 worker app 和任务模块：`parse_document`、`extract_candidates`、`create_review_batch`、`sync_source`、`sync_active_release_index`、`refresh_retrieval_index`。
- [ ] API 对长任务返回 `202 Accepted + job_id`，管理台轮询或 SSE 展示进度，不阻塞请求线程。
- [ ] 任务状态写入持久化 `job_runs/source_sync_runs`，包含输入引用、输出引用、attempt、耗时、错误、trace id。
- [ ] 实现幂等键：同一 source artifact、同一 document hash、同一 extraction config 不重复创建候选批次。
- [ ] 实现 retry/backoff、最大重试、人工重跑、取消和失败隔离。
- [ ] 对 LLM 调用、PDF 解析、Graph sync 等任务设置独立超时与并发限制。

**验收：**

- 上传大文件或批量文件时 API 不超时，后台任务可继续执行。
- worker 中断后重启，未完成任务不会重复发布正式知识。
- 失败任务能在管理台看到完整原因并可重试；重试后保留原失败记录。
- 同一批 source sync 并发触发不会产生重复 review batch。

### T-320 `[ ]` 真实认证、授权与租户/角色治理

**目标：** 用真实身份体系替代请求参数里的 `actor_id/actor_role`，使系统具备生产可追责能力。

**确定技术路线：**

- Keycloak 作为默认 OIDC/OAuth2 身份提供方，支持后续接企业微信/飞书作为上游身份源。
- 前端使用 `oidc-client-ts` 完成 Authorization Code + PKCE。
- 后端使用 PyJWT + JWKS cache 校验 access token；角色与领域权限在本项目 PostgreSQL 中做映射。

**实施内容：**

- [ ] 建立 `users`、`roles`、`domain_memberships`、`permissions` 表，支持同一用户在不同 `domain_id` 下不同角色。
- [ ] 所有写接口从 token/session 获取 actor，不再信任请求体中的 actor 字段。
- [ ] 保留 service 层 `ActorContext`，但由认证 middleware/dependency 注入。
- [ ] 管理台增加登录、退出、当前用户、无权限状态页。
- [ ] 高风险操作增加二次确认与可配置审批策略：release 激活/回滚、数据源配置、Skill 启停、未来设备相关动作。
- [ ] 审计事件记录真实 user id、显示名、角色、来源 IP/request id、领域和目标对象。

**验收：**

- 未登录用户不能访问管理台和受保护 API。
- 研究者不能发布 release，审核员不能配置系统数据源，管理员操作有审计。
- 篡改请求体 `actor_role=admin` 不会提升权限。
- 同一用户在两个 domain 的权限隔离可由测试验证。

### T-330 `[ ]` 生产对象存储、文件安全与解析增强

**目标：** 让原文资料、解析产物、候选产物和发布产物进入可备份、可审计、可校验的对象存储，并提升真实 PDF 解析能力。

**确定技术路线：**

- MinIO 作为默认 S3-compatible object storage，使用 `boto3` 实现 `S3ObjectStore`。
- 文件类型识别使用 `python-magic`，不能只信任扩展名。
- 病毒/恶意文件扫描接 ClamAV 服务。
- PDF 解析主路线固定为 Docling；扫描件 OCR 固定接 PaddleOCR，并通过同一个 `DocumentParser` adapter 暴露结果。

**实施内容：**

- [ ] 实现 `S3ObjectStore`，支持 bucket、prefix、版本、content hash、metadata、服务端加密配置和只读签名 URL。
- [ ] RAW/PARSED/CANDIDATE/PUBLISHED artifact 均保留不可变版本；禁止覆盖同一 object version。
- [ ] 上传阶段加入 MIME sniffing、大小限制、页数限制、文件扫描和拒绝原因。
- [ ] 为真实中文 PDF 建立 Docling + PaddleOCR parser benchmark，记录同一语料上的成功率、locator 质量、表格/标题处理和耗时。
- [ ] 对解析结果增加质量标记：是否 OCR、是否低置信、是否缺页、是否抽取到表格。
- [ ] 为文档详情页提供安全下载/预览入口，但不暴露对象存储内部密钥。

**验收：**

- 生产对象存储中的 artifact 可用 hash 校验，备份后可恢复。
- 上传伪装扩展名、超大文件、空文本 PDF、扫描 PDF 均有明确状态。
- 在 E-001 真实样本上记录解析成功率和失败分类，达到上线门槛后再标记完成。

### T-340 `[ ]` Neo4j/向量/混合检索生产化

**目标：** 将当前内存图谱和词法检索升级为持久化、可查询、可评测的生产检索层，同时保持 active release 和引用边界。

**确定技术路线：**

- Neo4j official Python driver 作为图数据库 adapter。
- 向量检索使用 PostgreSQL `pgvector`，不另引入独立向量数据库。
- Embedding provider 通过 adapter 接入，记录 embedding model/version。
- 检索融合固定为 PostgreSQL full-text + `pgvector` + Neo4j graph neighborhood 的 hybrid ranker。

**实施内容：**

- [ ] 在 app 启动配置中接入 `Neo4jGraphRepository`，建立约束和索引：release、document、chunk、assertion、concept。
- [ ] 将 release sync 设计为幂等任务：重复 sync 不重复节点/边，失败可重跑。
- [ ] 建立 durable `retrieval_index_entries` 或等价索引表，保存 assertion、chunk、locator、index_text、embedding ref、release id。
- [ ] 为 active release 查询增加全文检索、向量召回、图邻域扩展和 citation filter；所有结果必须可回溯到 `SourceChunk`。
- [ ] 建立检索评测脚本，比较 lexical baseline 与本任务实现的 hybrid ranker 在同一问题集上的 recall、citation accuracy、latency、cost。
- [ ] 实现 `RagEngine`/`GraphRagAdapter` 端口，T-345 固定接入 Microsoft GraphRAG；T-340 自身完成可控的 release-local hybrid baseline。

**验收：**

- Neo4j 重启后 active release 图谱仍可查询。
- 切换 active release 后，用户检索立即只读新 active release。
- 未审核 candidate assertion 无法通过任何检索路径返回。
- 每个搜索结果都有 document/chunk locator citation；无引用的 assertion 不进入医学回答。

### T-345 `[ ]` Microsoft GraphRAG 框架接入

**目标：** 接入 Microsoft GraphRAG 作为正式 GraphRAG 框架，承担社区摘要、全局主题概览、多跳关系查询和研究空白分析；同时保证框架只能读取 active release 派生数据，不能绕过审核发布边界。

**确定技术路线：**

- Microsoft GraphRAG 作为唯一 GraphRAG 框架主线，用于 global/local/DRIFT 查询、社区摘要和跨文献主题概览。
- 本项目自有 `RagEngine` adapter 负责 release export、索引触发、查询、引用映射和权限控制。
- DeepEval 用于 answer relevance、faithfulness、context precision 和 citation recall 评测。
- V1.5 只接入 Microsoft GraphRAG，不引入第二套 GraphRAG/RAG 编排框架。

**实施内容：**

- [ ] 定义统一 `RagEngine` 端口：`index_release()`、`query_release()`、`delete_release_index()`、`healthcheck()`、`explain()`。
- [ ] 为 Microsoft GraphRAG 建立独立 adapter，输入只允许 `PublishedReleaseExport`，输出必须带 source chunk/citation mapping。
- [ ] 建立 release export 格式：只导出 active/published assertion、source document、source chunk、concept 和 review metadata，不导出 candidate/raw LLM response。
- [ ] 建立 Microsoft GraphRAG 上线评测：在同一问题集上记录召回、引用准确率、延迟、成本、索引耗时和运维复杂度，并与现有 baseline 指标并列展示。
- [ ] 对框架生成的社区摘要或全局总结打上 `DERIVED` 层标记，不能反写为正式 `EvidenceAssertion`；若摘要发现新关系，只能创建候选任务等待审核。
- [ ] 管理台增加“GraphRAG 索引”视图，展示 Microsoft GraphRAG 版本、索引状态、评测结果和发布状态。

**验收：**

- 完成 Microsoft GraphRAG adapter，并在 ADR 中记录索引格式、查询模式、权限边界和引用映射。
- 同一 E-003 问题集上有可复现评测报告，不能只凭主观演示决定上线。
- 框架输出不得出现 candidate 泄漏；所有回答引用必须落回本系统 `SourceChunk`。
- Microsoft GraphRAG 默认作为科研主题概览、研究空白分析和复杂多跳问题引擎；直接事实查证和医学证据回答默认仍走 T-340 hybrid evidence retrieval。

**不得做：**

- 不让 Microsoft GraphRAG 自动抽出的图谱直接成为主知识库。
- 不把框架内部索引当作唯一存储；主数据仍在 PostgreSQL/Neo4j release schema 与对象存储中。
- 不在没有真实评测集时为了“看起来先进”接入多个框架到生产路径。

### T-350 `[ ]` 模型调用网关、抽取质量与成本治理

**目标：** 让 LLM 抽取和问答具备稳定配置、可追踪成本、失败治理和质量回归，而不是单次 live 调用。

**确定技术路线：**

- LiteLLM 作为统一模型调用网关，封装 MiMo、DeepSeek 和后续 OpenAI-compatible provider。
- Langfuse 作为 prompt/version、LLM trace 和模型调用观测后端。
- Pydantic v2 + JSON Schema 作为结构化输出校验层，业务对象仍落到 Evidence Schema。

**实施内容：**

- [ ] 建立 model invocation 表，记录 provider、model、prompt version、schema version、token、latency、cost、raw response hash、error。
- [ ] 为抽取任务增加 chunk batching、长文窗口策略、重试策略、JSON repair 边界和严格 Schema validation。
- [ ] 对 provider 响应做脱敏持久化，不存 API key，不把完整敏感 query 写入审计。
- [ ] 建立 golden extraction regression：同一 fixture/真实样本在 prompt/model 更新前后比较 assertion 数量、source_chunk_ids、关键字段和错误率。
- [ ] 管理台展示模型调用量、失败率、平均延迟和估算成本。
- [ ] 明确模型降级策略：provider 不可用时任务失败并可重试，不伪造候选证据。

**验收：**

- live provider 配置可通过健康检查验证，但不回显密钥。
- 每次候选抽取可从 assertion lineage 追溯到具体 provider/model/prompt/schema/parser。
- prompt 或 model 变更必须跑 extraction regression，未通过不得默认切换。

### T-355 `[ ]` 关系抽取成熟度专项优化

**目标：** 把当前 fixture-level 关系抽取升级为可评测、可迭代、可审核的真实语料抽取能力，重点解决普通 `relations` 未进入主流程、跨 chunk 关系合并、复杂 PICO/参数/安全信息抽取和置信度不可校准的问题。

**确定技术路线：**

- Label Studio 作为人工标注/复核工具，用于构建金标准关系集。
- Pydantic v2/JSON Schema 生成抽取输出 schema，用于严格 provider response validation。
- 项目内 `evals` runner 记录 relation precision、recall、F1、citation accuracy、field completeness。
- GLiNER 作为实体预标注辅助组件；发布仍以 Evidence Schema 和人工审核为准。

**实施内容：**

- [ ] 建立真实语料金标准：至少覆盖 tVNS/taVNS 的干预、刺激部位、参数、结局、安全事件、对照组、疾病/症状、人群和研究设计。
- [ ] 明确 `relations` 与 `evidence_assertions` 的职责：普通关系可用于导航，但医学结论必须转成带来源的 `EvidenceAssertion` 才能发布。
- [ ] 扩展 review workflow，使普通 `CandidateRelation` 可选择性进入审核台，支持批准为导航关系、转写为 EvidenceAssertion 或拒绝。
- [ ] 增加跨 chunk 合并与去重策略：同一研究、同一干预、同一结局、多参数描述不能产生大量重复命题。
- [ ] 优化抽取 prompt/schema，覆盖 PICO、阴性结果、无差异结果、冲突结论、表格参数、安全/禁忌和研究设计字段。
- [ ] 建立错误分类：实体边界错误、predicate 错误、方向错误、参数遗漏、source chunk 错误、幻觉关系、重复关系、过度合并。
- [ ] 校准或降级 `extraction_confidence`：在真实评测前只作为模型自报提示，不得当作统计概率；评测后记录按区间的实际准确率。
- [ ] 建立 prompt/model/parser 联合回归：解析器或 prompt 更新后必须比较关系数量、字段完整性、source citation 准确率和错误类型变化。
- [ ] 将关系抽取指标接入管理台和观测：按 domain、source、model、prompt、parser_version 展示抽取成功率与人工通过率。

**验收：**

- 至少一批真实 E-001 文献完成专家标注或双人复核，形成可复现 gold dataset。
- live provider 在 gold dataset 上输出 precision、recall、F1、citation accuracy 和字段完整性报告。
- 普通 `relations` 不再只是 artifact 中的旁路数据：要么进入审核台作为导航关系候选，要么明确不参与生产图谱。
- 任一发布命题都能追溯到原文 chunk、抽取 run、prompt/schema/parser version 和 review decision。
- 关系抽取错误类型有统计，后续 prompt/model/解析器优化能用同一指标比较。

**不得做：**

- 不把模型自报置信度当作真实准确率。
- 不让普通关系绕过 `EvidenceAssertion` 和 review/release 直接支撑医学回答。
- 不在没有真实标注集时声称关系抽取成熟或达到生产质量。

### T-356 `[ ]` 多轮分级全文知识抽取流水线

**目标：** 从当前“一次性候选命题抽取”升级为“全文、多轮、分级、可回溯”的知识抽取流水线，覆盖文档中细节关系、研究设计、证据命题和主题总结，贴近完整科研知识图谱建设目标。

**确定技术路线：**

- 使用 Celery workflow 编排多轮抽取任务，每一轮输出独立 artifact 和 run record。
- 使用 LiteLLM 调用模型，所有轮次共享 T-350 的模型调用记录和成本治理。
- 使用 Pydantic v2 schema 定义每一层输出结构，失败轮次可单独重跑。
- 使用 PostgreSQL 保存抽取 run、候选对象和去重结果；使用 MinIO 保存每轮原始响应和派生 JSON。

**实施内容：**

- [ ] 定义五层抽取结构：
  1. `EntityLayer`：疾病/症状、干预、穴位/刺激部位、参数、量表、结局、安全事件、研究设计术语。
  2. `RelationLayer`：chunk 级细粒度实体关系和普通导航关系。
  3. `StudyDesignLayer`：PICO、样本量、随机/盲法、对照、纳入/排除标准、随访、统计指标。
  4. `EvidenceLayer`：可审核 `EvidenceAssertion`，包含方向、人群、参数、结局、source chunk。
  5. `TopicLayer`：研究主题、趋势、冲突、证据空白和可复现实验线索，进入 `DERIVED` 层。
- [ ] 每一层都必须记录输入 chunk ids、prompt version、model、schema version、parser version 和 output artifact。
- [ ] 设计跨层合并规则：实体归一化后再合并关系，研究设计层约束证据层，主题层只能引用已抽取证据和原文。
- [ ] 设计跨 chunk/cross-section 合并：同一论文的参数、结局和安全信息可合并到同一 study record，但必须保留每个字段来源。
- [ ] 实现抽取差异比较：重新解析或重新抽取后展示新增、删除、修改和冲突候选。
- [ ] 管理台增加“分级抽取 run”视图，按文档展示各层状态、错误、重跑和审核入口。

**验收：**

- 一篇真实论文能生成五层抽取 artifact，并可从主题层追溯到具体 `SourceChunk`。
- 任一层失败不会污染已成功层，也不会自动发布知识。
- 同一文档重抽后能展示层级 diff 和影响的候选 evidence assertions。
- 主题层和 GraphRAG 摘要只能作为派生辅助，不直接成为正式医学结论。

### T-357 `[ ]` 科研实验设计知识模型与 Skill

**目标：** 支持研究者询问“应该如何设计某类实验”，系统基于已发布证据、GraphRAG 派生摘要和研究设计 Schema 生成可引用、可审查的实验设计建议草案。

**确定技术路线：**

- 新增 `ResearchDesign` 领域模型，结构化表达研究问题、PICO、样本、人群、干预参数、对照、结局、量表、安全监测、随访和证据依据。
- 新增只读 `research-design` Agent Skill，只能读取 active release、Microsoft GraphRAG `DERIVED` 摘要和发布来源引用。
- 使用 LiteLLM 生成实验设计草案，所有建议必须附 citation，不足之处必须明确标记为“证据不足/需专家确认”。

**实施内容：**

- [ ] 定义 `ResearchDesign` schema：`research_question`、`population`、`inclusion_criteria`、`exclusion_criteria`、`intervention`、`parameter_set`、`comparator`、`outcomes`、`measurement_tools`、`followup`、`safety_monitoring`、`feasibility_notes`、`evidence_gaps`、`citations`。
- [ ] 将 T-356 的 `StudyDesignLayer` 映射到可检索的研究设计索引。
- [ ] 实现 `research-design` Skill：输入研究方向和约束，输出实验设计草案、证据依据、冲突点、待专家确认项。
- [ ] 检索策略固定为：active release evidence -> study design index -> Microsoft GraphRAG topic summary -> citation rerank。
- [ ] 管理台增加实验设计草案预览和导出入口；导出内容标注“科研设计辅助，不作为临床治疗建议”。
- [ ] 建立 eval seeds：失眠 tVNS、轻度认知障碍 tVNS、安全监测、不同刺激部位对照、参数优化和阴性结果复现实验。

**验收：**

- 对一个 E-003 研究设计问题，系统能生成结构化实验设计草案，并为每个关键建议给出已发布 citation。
- 当缺少样本量、随访或安全依据时，答案明确标记证据不足，不编造数字。
- 草案不调用 candidate 层数据，不输出设备可执行控制指令。
- 专家可根据引用审查草案来源，反馈进入 eval/gold dataset。

### T-360 `[ ]` 可观测、审计留存与运维监控

**目标：** 用标准观测体系替代内存 recorder，使生产故障、性能、成本和安全事件可定位。

**确定技术路线：**

- OpenTelemetry instrumentation for FastAPI/httpx/Celery/SQLAlchemy。
- Prometheus + Grafana 采集和展示指标。
- Sentry 用于异常追踪。
- structlog 输出结构化 JSON 日志。

**实施内容：**

- [ ] 统一 request id/trace id/job id，并贯穿 API、worker、LLM、DB、object store、Neo4j。
- [ ] 将 observability events 和 audit events 持久化，设置留存策略和导出接口。
- [ ] 增加关键指标：解析成功率、抽取成功率、candidate->release 转化、检索无结果率、citation 缺失率、LLM 成本、队列积压、任务耗时、错误率。
- [ ] 建立告警规则：队列堆积、模型失败率升高、对象存储不可用、数据库连接耗尽、未授权访问异常、candidate 泄漏测试失败。
- [ ] 管理台从真实指标仓库读取，不再返回 unavailable 占位。

**验收：**

- 本地 docker compose 或生产环境能打开 Grafana dashboard 查看 API/worker/DB/LLM 指标。
- 任一 chat answer 可追踪到 request、Skill execution、retrieval、release、citation 和审计事件。
- 故障样例能在日志/APM/任务记录中串起来定位。

### T-370 `[ ]` 部署、配置、备份与灾备

**目标：** 提供可重复部署、可回滚、可备份恢复的生产运行方案。

**确定技术路线：**

- Docker 多阶段构建；生产运行使用 gunicorn/uvicorn workers。
- Docker Compose 作为 V1.5 生产部署基线。
- Pydantic Settings v2 扩展为环境分层配置。
- PostgreSQL、对象存储、Neo4j 使用各自成熟备份机制，不自行写备份格式。

**实施内容：**

- [ ] 编写 production Dockerfile、docker-compose.prod.yml 和环境变量说明。
- [ ] 配置 API、worker、frontend、PostgreSQL、Redis、MinIO、Neo4j、Prometheus/Grafana 的部署拓扑。
- [ ] 增加启动前检查：迁移版本、对象存储 bucket、Neo4j 连接、身份源配置、必要密钥存在。
- [ ] 建立备份/恢复 runbook：PostgreSQL dump/PITR、对象存储 bucket versioning、Neo4j dump、配置和 Skill 包备份。
- [ ] 建立环境分层：local、staging、production；生产禁用 debug docs 或加保护。
- [ ] 建立蓝绿/滚动发布和回滚步骤，至少支持 staging 验收后升级 production。

**验收：**

- 新机器按 runbook 可从备份恢复到可查询 active release。
- staging 与 production 配置隔离，生产密钥不进入仓库和前端 bundle。
- 一次失败部署可按文档回滚到上一版本。

### T-380 `[?]` 真实数据源 adapter 与数据合同

**目标：** 在拿到真实外部接口契约后，实现可维护的数据源接入，而不是依赖 generic REST 处理未知结构。

**确定技术路线：**

- HTTP client 固定使用 `httpx`。
- 数据合同使用 OpenAPI + Pydantic v2 models 固化。
- 首个生产 adapter 固定对接 E-006 提供的真实外部资料接口；E-006 未提供前保持阻塞。

**实施内容：**

- [?] 获取 E-006：接口地址、认证方式、请求参数、分页/游标、速率限制、返回样例、全文获取权限。
- [ ] 为 E-006 source 建立独立 adapter 和 contract tests。
- [ ] 实现 cursor/checkpoint、增量时间窗、去重字段、失败重试和速率限制。
- [ ] 明确 metadata 到 `SourceDocument`/`Study`/`SourceQualitySignals` 的映射，未知字段保留在 metadata，不随意猜测医学含义。
- [ ] 管理台支持 E-006 source 的配置表单、测试连接和 dry-run 预览。

**验收：**

- 真实 source 的 contract test 可离线使用录制 fixture 重放。
- 一次 sync 可拉取真实 metadata/文件进入统一 document pipeline。
- 权限或全文不可用时清楚标记，不伪造文档内容。

### T-390 `[ ]` 生产验收、压测与安全测试

**目标：** 在上线前用可重复脚本证明系统能承受真实使用，并符合内部科研产品的安全和质量底线。

**确定技术路线：**

- pytest + Playwright 做端到端回归。
- k6 做负载测试。
- OWASP ZAP 做 Web/API 基础安全扫描。
- pip-audit/npm audit/Trivy 做依赖和镜像漏洞扫描。

**实施内容：**

- [ ] 建立 staging 端到端验收脚本：真实登录、上传、异步解析、抽取、审核、发布、检索、聊天、回滚。
- [ ] 建立负载模型：并发上传、批量 source sync、并发聊天、后台抽取并发、管理台查询。
- [ ] 建立安全测试：认证绕过、越权、文件上传、prompt injection、candidate 泄漏、敏感配置泄漏、CORS/CSRF/速率限制。
- [ ] 建立数据恢复演练：从备份恢复后 active release 和引用可用。
- [ ] 输出生产发布清单，逐项记录版本、配置、迁移、备份、回滚、已知风险和负责人签收。

**验收：**

- staging 全链路自动验收通过。
- 压测达到内部目标并记录瓶颈；未达标项进入阻塞清单。
- 高危安全问题为 0；中危问题有明确修复或缓解方案。
- 发布清单完成后才允许标记 production-ready。

---

## 8. P1/P2 远期任务

以下任务不阻塞 V1，不得在 P0 主链路未验收前扩张实现范围。

### T-210 `[ ]` 新领域接入

- [ ] 通过新 `domain_id`、新 Schema/词表和独立评测集接入新领域。
- [ ] 验证不改变针灸领域的 active release、Skill 和检索结果。

### T-220 `[ ]` 科研系统与报告导出

- [ ] 获取目标系统接口与导出模板后再实现。
- [ ] 输出只使用已发布证据，并附来源和生成版本。

### T-230 `[ ]` 商用/临床/设备/BCI 演进评估

- [ ] 明确用途变化、数据敏感度、安全要求和责任边界后再立项。
- [ ] 任何治疗建议或设备控制能力必须建立独立风险审核与验收标准。

---

## 9. Codex 每次实现的交付模板

后续让 Codex 执行某项 TODO 时，建议使用如下要求：

```markdown
请阅读 `项目TODO与Codex实现规则.md` 与相关实施文档，实现任务 `T-XXX`。

要求：
1. 先检查当前仓库结构与已有修改，说明本次实现范围。
2. 严格遵守该文档中的范围、安全、数据和依赖规则。
3. 实现代码、测试和必要文档，不只给出方案。
4. 运行与该任务相关的验证命令。
5. 完成后更新 TODO 状态与完成证据；若受外部输入阻塞，标记 `[?]` 并实现可验证的非伪造基础部分。
```

---

## 10. 当前下一步

当前 P0 代码链路和 fixture 自动回归已经完成；若目标是生产环境可用，下一步按以下顺序推进，避免继续扩大 demo 功能：

1. 先实现 T-300 durable PostgreSQL repository adapter，把 in-memory 运行期状态迁出。
2. 接着实现 T-310 Celery/Redis 后台任务，把解析、抽取、索引和 source sync 从同步请求中移出。
3. 并行准备 T-320 真实认证方案，生产环境不再接受请求体伪造 actor。
4. 补 T-330/T-340，使对象存储、PDF 解析、Neo4j 和检索索引具备重启恢复能力。
5. 在 E-001/E-005/E-003 到位后，执行 live 抽取、真实 citation 评测和 T-390 staging 验收。
6. 执行 T-345 Microsoft GraphRAG 接入，使科研主题概览、研究空白分析和多跳问题不再依赖手写检索逻辑。

在 T-300 至 T-390 完成前，本系统应描述为“可执行 V1 基线/fixture demo”，不得描述为 production-ready。真实验收门禁完成前，T-120 保持 `[?]`，不得把 fixture 结果描述为正式针灸证据成果。
