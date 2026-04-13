# 工作流系统重构计划（M18 详细设计）

> 目标：在不打坏当前已闭环的 `LLM bbox 自动标注 + SAM2 实例分割 + 人工修正 + 导入导出 + 评估` 体系的前提下，引入**最小安全的 workflow 抽象层**，避免未来每支持一种视觉场景都把主流程继续写成新的特判分支。

---

## 1. 结论先行

本次重构**不做完整插件平台**，也**不做一次性全仓重写**。

我们采用的方案是：

- 面向用户：逐步以 `workflow` 作为项目创建和配置的主入口。
- 面向系统：保留 `task_family/result_type` 作为统一的数据与交互约束层。
- 面向实现：把 `LLM 调用`、`SAM 调用`、`tile_split`、`tile_merge`、`postprocess`、`evaluation_adapter` 等能力收敛为可复用的 atomic capabilities。
- 面向风险控制：优先新增 **workflow registry** 与兼容层，把当前默认流程先包装成内置 workflow；只有在该层稳定后，才允许继续增加遥感、变化检测等新流程。

一句话概括：

**不是把系统直接改造成“万能插件平台”，而是先把“工作流决策层”从当前主流程中抽出来。**

---

## 2. 为什么现在要做这件事

当前系统已经能稳定支持两条主线：

- 检测项目：`LLM/OpenAI-compatible -> bbox -> 写库`
- 分割项目：`LLM/OpenAI-compatible -> bbox -> SAM2 refine -> polygon/mask -> 写库`

这个设计对当前 MVP 足够有效，但已经暴露出两个增长风险：

### 2.1 场景扩展会不断污染主流程

如果未来新增：

- 遥感建筑物
- 遥感道路
- 变化检测
- 医学分割
- 工业缺陷

并且每一类都继续通过主流程里的 `if project.task_type == ...` 或 `if scene == ...` 增长，那么：

- 自动标注逻辑会越来越难维护
- 前端编辑器和后处理语义会混在一起
- 导入导出和评估也会被迫跟着堆特判
- 已经闭环的检测/分割主链路更容易被误伤

### 2.2 “任务大类”与“具体工作流”不是一回事

例如：

- 遥感建筑物分割和通用实例分割，结果类型都可能是 `instance_mask`
- 变化检测和普通分割，都可能输出 `mask`，但交互与评估完全不同
- 道路提取更接近 `polyline/semantic_mask`，并不适合当前 `bbox -> SAM` 流程

所以系统不能长期只依赖 `task_type = detection | segmentation` 承担全部语义。

---

## 3. 本次重构不做什么

这部分非常重要，用来约束范围，防止大爆炸。

### 3.1 不做动态第三方插件加载

这里的“插件化”仅指**仓库内的 workflow registry 和可插拔流程模块**，不是：

- 运行时从外部目录自动发现 Python 插件
- 独立版本发布的第三方 workflow 包
- 热插拔安装/卸载工作流 marketplace

第一阶段全部 workflow 都以内置模块存在于仓库内。

### 3.2 不立刻废弃现有 `task_type`

当前大量逻辑仍然依赖：

- `detection`
- `segmentation`

所以第一阶段不砍掉该字段，也不要求所有 API 一次性改名。

### 3.3 不在第一阶段重写数据库、前端编辑器和评估系统

第一阶段允许的变动重点是：

- 新增 workflow registry
- 新增 workflow 元数据
- 给现有默认流程包一层 workflow
- 为后续场景扩展留出插口

第一阶段**不以“做完所有新场景支持”为目标**。

---

## 4. 目标架构

新架构分三层。

### 4.1 第一层：`workflow_key`

这是项目实际选用的**业务流程配方**，更接近用户心智。

示例：

- `generic_detection`
- `generic_instance_segmentation`
- `remote_building_instance_segmentation`
- `remote_change_detection`
- `manual_only`

用户未来主要选择的是这一层。

### 4.2 第二层：`task_family / result_type`

这是系统内部的统一抽象，用于约束数据形态、交互方式、导出和评估。

建议首批定义：

- `bbox`
- `instance_mask`
- `semantic_mask`
- `polyline`
- `change_mask`

它不是为了替代 workflow，而是为了给底层逻辑一个稳定坐标系。

### 4.3 第三层：atomic capabilities

这些是 workflow 可复用的原子能力：

- `llm_grounding`
- `sam_refine`
- `tile_split`
- `tile_merge`
- `dedup`
- `postprocess`
- `evaluation_adapter`
- `dataset_export_adapter`
- `manual_bbox_edit`
- `point_refine`

workflow 不是一堆特判，而是这些能力的编排组合。

---

## 5. 推荐的数据与配置模型

### 5.1 第一阶段不要先改数据库列

为了控制风险，第一阶段不立即为 `projects` 表新增强制列。

推荐做法：

- `task_type` 继续保留在 `projects` 表中
- `workflow_key` 先进入 `project.config` 或项目设置响应中
- 当 `workflow_key` 缺失时，由兼容逻辑自动映射：
  - `detection -> generic_detection`
  - `segmentation -> generic_instance_segmentation`

这样有几个好处：

- 旧项目天然兼容
- 不必在第一步就引入 DB migration
- 可以先验证 workflow registry 是否足够稳

### 5.2 第二阶段再决定是否提升为一等字段

当 workflow 模型稳定后，再判断是否需要把 `workflow_key` 提升为数据库列。

只有在出现这些需求时，才值得升级：

- 需要高频按 workflow 过滤/统计项目
- 需要更明确的 schema 约束
- 前后端与导出链路都已经稳定依赖该字段

---

## 6. Workflow Registry 设计

### 6.1 最小注册单元

建议每个 workflow 至少包含这些元信息：

- `key`
- `display_name`
- `description`
- `task_family`
- `supports_auto_annotation`
- `supports_manual_bbox`
- `supports_point_refine`
- `capabilities`

建议每个 workflow 允许挂接这些 handler：

- `auto_annotate_image(...)`
- `predict_from_bbox(...)`
- `refine_with_points(...)`
- `build_export_profile(...)`
- `build_evaluation_profile(...)`

第一阶段不要求所有 handler 都实现。

### 6.2 第一批内置 workflow

第一阶段只需要先收敛两个内置 workflow：

#### `generic_detection`

- `task_family = bbox`
- capabilities:
  - `llm_grounding`
  - `manual_bbox_edit`
  - `postprocess`
  - `evaluation_adapter`

对应现有主链：

- 自动标注：LLM 出 bbox
- 人工修正：框增删改
- 导出：YOLO / COCO detection

#### `generic_instance_segmentation`

- `task_family = instance_mask`
- capabilities:
  - `llm_grounding`
  - `sam_refine`
  - `manual_bbox_edit`
  - `point_refine`
  - `postprocess`
  - `evaluation_adapter`

对应现有主链：

- 自动标注：LLM 出 bbox
- 分割：SAM2 refine
- 人工修正：bbox 修正 + 点修正

### 6.3 第二批候选 workflow

这些 workflow 先定义为路线图，不在第一阶段强行实现：

#### `remote_building_instance_segmentation`

- `task_family = instance_mask`
- capabilities:
  - `tile_split`
  - `llm_grounding`
  - `sam_refine`
  - `tile_merge`
  - `dedup`
  - `postprocess`

#### `remote_change_detection`

- `task_family = change_mask`
- capabilities:
  - `pair_loader`
  - `change_detector`
  - `postprocess`
  - `evaluation_adapter`

这类 workflow 的存在，正是我们引入 workflow layer 的意义，但它们不应该阻塞当前第一阶段落地。

---

## 7. 与当前系统的映射关系

### 7.1 当前状态

目前主流程里最核心的耦合点是：

- 自动标注逻辑按 `project.task_type` 决定是否调用 SAM
- 图片详情页的手工修正逻辑按 `project.task_type` 决定是否允许点修正
- 导入导出、评估和前端展示也默认把 `detection/segmentation` 当成全部语义

### 7.2 第一阶段映射原则

第一阶段不改变这些核心事实：

- 检测项目仍然输出 bbox
- 当前分割项目仍然输出 polygon / mask
- 现有人工修正交互和评估入口仍然可用

第一阶段只改变“决策入口”：

- 以前：`task_type` 直接决定流程
- 以后：`workflow_key` 决定流程，`task_type` 作为兼容映射和旧接口语义保留

### 7.3 推荐的兼容映射

默认映射建议固定：

- `task_type = detection`  
  对应 `workflow_key = generic_detection`

- `task_type = segmentation`  
  对应 `workflow_key = generic_instance_segmentation`

如果老项目没有 `workflow_key`，系统一律按上述规则解析。

---

## 8. API 与前端的最小改法

### 8.1 后端 API

第一阶段建议：

- 保持现有项目创建 API 可用
- 允许 `workflow_key` 成为可选参数
- 若未传 `workflow_key`，根据 `task_type` 自动填充默认 workflow
- 项目设置读取接口开始回传：
  - `workflow_key`
  - `task_family`
  - `workflow_metadata`

这样前端可以逐步接入，而不会立刻打断旧调用方。

### 8.2 前端项目创建入口

推荐分两步推进：

#### 第一步

仍允许旧 UI 只选 `task_type`，系统自动映射默认 workflow。

#### 第二步

新 UI 以 workflow 为主入口，例如：

- 通用目标检测
- 通用实例分割
- 遥感建筑物
- 变化检测

同时展示系统推导出的：

- `task_family`
- 主要能力
- 是否支持点修正
- 是否适合大图切片

这样用户不需要先理解“bbox 还是 segment”，而是直接选他要完成的流程。

### 8.3 手工标注工作台

第一阶段不重做编辑器，只新增 workflow metadata 的消费能力：

- 是否允许点修正
- 是否允许 bbox 新建
- 是否显示 workflow 特有说明

真正的编辑器差异化重构，留到后续前端重构阶段。

---

## 9. 推荐实施顺序

### Phase 0：现状盘点与回归基线

在真正动代码前，先固定回归基线：

- 检测项目自动标注
- 分割项目自动标注
- bbox 手工修正
- 点修正
- 导入导出
- 评估

必须保证后续所有 workflow 重构都以这条基线为红线。

### Phase 1：引入 workflow registry，但不改用户行为

目标：

- 先在后端内部引入 workflow registry
- 把现有 `detection` / `segmentation` 流程包装成两个内置 workflow
- API 对外仍保持兼容

这一步完成后，系统功能不该有任何用户可感知变化。

### Phase 2：引入 `workflow_key` 配置与兼容映射

目标：

- 项目设置中能存取 `workflow_key`
- 老项目可自动兼容
- 项目创建接口可以显式传 `workflow_key`

此时还不要求前端全面改版。

### Phase 3：前端以 workflow 作为主入口

目标：

- 创建项目与项目设置界面开始以 workflow 为主
- `task_type` 逐步转为派生/兼容信息
- 编辑器仍沿用旧能力，只读 workflow metadata 控制功能开关

### Phase 4：新增第一个“非默认” workflow

目标：

- 只新增一个真正不同于现有默认流程的 workflow
- 推荐优先级：
  - `remote_building_instance_segmentation`
  - 不推荐第一枪就做 `road extraction`
  - 不推荐第一枪就做 `change detection`

原因：

- 建筑物实例分割更接近当前系统
- 道路和变化检测都更容易牵涉新的标注数据结构与评估方式

---

## 10. 什么时候算“改动过大”

为了避免在 M18 里失控，定义以下“巨变判定”。

如果同时满足下列任意 3 项及以上，则认定为**大重构**，不得边做边猜，必须先更新本设计文档并补充专项章节：

- 需要数据库 schema 迁移，而不仅是 `project.config` 扩展
- 需要修改核心 REST 契约或批量改动现有请求/响应结构
- 需要引入新的标注基础数据结构，而不只是 bbox / polygon / mask 的重组
- 需要前端编辑器重做，而不是只读 workflow metadata 开关
- 需要导入导出语义整体重写
- 需要评估指标体系整体重写
- 需要新的任务编排/队列模型，而不是复用现有任务系统

如果触发该门槛，后续动作应是：

1. 更新本设计文档  
2. 单独列出迁移方案与回滚方案  
3. 明确哪些内容顺延到 M19 / M20 或后续新里程碑  
4. 经确认后再开始实现

---

## 11. 回归与验证策略

当前开发机资源非常有限，因此 M18 的验证策略必须偏“低算力、高覆盖”。

### 11.1 必须保留的自动回归

- detection 自动标注 API
- segmentation 自动标注 API
- 图片详情页 bbox 修正
- 点修正
- 项目设置读取/写入
- 导入导出
- 评估入口

### 11.2 新增的契约测试

至少补以下测试：

- 老项目缺少 `workflow_key` 时能正确映射默认 workflow
- 新项目显式设置 `workflow_key` 时，能推导出正确的 `task_family`
- workflow registry 缺失/非法 key 时，能给出清晰错误
- 默认 workflow 下的自动标注结果和当前行为一致
- workflow metadata 能正确控制“是否支持点修正”等前端/接口开关

### 11.3 真机验证放到后续

M18 的第一阶段不依赖真实大模型或 GPU 才能完成。

真实遥感 workflow、变化检测 workflow 的模型级验证，应放到：

- 新 workflow 真正实现之后
- 并且在后续真实环境统一联调时

---

## 12. 推荐的目录落点

建议新增以下目录或模块：

- `backend/workflows/registry.py`
- `backend/workflows/types.py`
- `backend/workflows/generic_detection.py`
- `backend/workflows/generic_instance_segmentation.py`

可选的共享能力目录：

- `backend/workflows/capabilities/`

但第一阶段不要把能力拆得过细，避免为了“原子化”而过度工程化。

推荐原则：

- 先抽“足够稳定的能力”
- 不要一开始把每一步都拆成独立层级

---

## 13. 对后续里程碑的影响

### 对 M19（OCI 分发）

影响应尽量小。

原则上：

- workflow 重构不应该改变服务拓扑
- 不应该增加新的基础运行时依赖
- 新增 workflow 若依赖额外模型，应在模型下载层按可选能力处理

### 对 M20（前端完全重构）

M18 实际上会为 M20 提供更清晰的前端边界：

- 创建项目页按 workflow 组织
- 编辑器按 `task_family` 决定主交互
- 能力开关由 workflow metadata 提供

所以 M18 做得越稳，M20 越不容易变成边做边猜。

---

## 14. 最终建议

当前最安全的实施方式是：

1. 先把现有默认流程注册成两个内置 workflow  
2. 继续保留 `task_type` 作为兼容层  
3. 让 `workflow_key` 先进入配置，不急着升数据库字段  
4. 先完成 registry 和回归测试，再考虑新增真实新 workflow  
5. 第一个新增 workflow 只选“最接近现有逻辑”的目标，优先遥感建筑物实例分割，不碰道路和变化检测

这条路径的好处是：

- 不会立刻打坏当前已闭环系统
- 不会把系统拖入“假插件化、真大重构”
- 仍然为后续场景扩展留下清晰的演进通道

---

## 15. 本文档对应的实施出口

当以下条件满足时，可以认为 M18 进入可实施状态：

- 已完成当前默认 workflow 的 registry 方案确认
- 已确定 `workflow_key` 的存放方式与兼容映射
- 已列出回归测试矩阵
- 已确认第一阶段不触发“大重构门槛”

若后续实现过程中发现门槛被触发，则应继续更新本文档，而不是跳过文档直接硬改代码。
