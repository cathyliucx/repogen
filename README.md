# RepoGen: 基于代码仓库语义理解的自动化训练数据生成系统 

是一款专为本地代码仓设计的小型项目自动化数据生成工具。它通过深度解析组件（Components）、提取业务逻辑并结合 RAG（检索增强生成）技术，生成高质量的 代码问答（QA） 与 系统设计（Design） 训练数据集，旨在支持专有大模型在代码理解与架构方案生成能力上的进化。

🌟 核心特性业务逻辑与代码绑定：通过结合代码仓 README.md 重新从业务角度理解 docstring，将枯燥的底层描述转换成业务语言。
证据链驱动生成：每一条生成的数据都带有 Context（代码仓内部）和 WIKI（外部查询）的支撑，确保生成内容有据可查。
递归语义聚合：采用自下而上的方式，从原子函数到文件，再到模块和全局架构，逐级构建代码仓知识图谱。
可持续增量生成：具备中断检测机制，自动跳过已处理组件，支持数据与日志的追加模式。
中心化 Agent 编排：基于 Orchestrator 模式，实现 Reader（分析）、Searcher（检索）、Writer（生成）的协同闭环。

🏗 系统架构项目由元数据预处理、WIKI 知识库构建和任务生成流水线三大核心模块组成。

## 📃 设计文档
请参考 assets/ 路径下，分别提供docx和pdf版本：
本地代码仓的小型项目的自动化训练数据生成系统 

## 🌲 目录结构

```
RepoGen
  └── agent
        ├── llm # 包含主流LLM接口类
        ├── base.py # BaseAgent基类
        ├── readmefilter.py # Readme内容过滤Github仓库Agent
        ├── task # 完成生成任务的Agents系统
            ├── orchestrator.py # 组织r-s-w逻辑Agent
            ├── reader.py # 阅读理解Agent
            ├── searcher.py # 查询WIKI和下载仓库(单一)Agent
            └──  writer.py # 任务执行Agent
        └── wiki # 用于理解Repo生成WIKI.md的Agents系统
            ├── build_repo_wiki.py # 单独直接构造Pipeline
            ├── recursive_system.py # 递归方式实现Pipeline
            ├── state.py # 共享agents状态
            └── agents
                ├── context_manager.py # readme摘要Agent
                ├── atomic_analyzer.py # docstring理解Agent
                ├── architect.py # 架构理解Agent
                └── wiki_builder.py # 合成WIKI.md Agent       
  └── data_process
        ├── repo_downloader.py # 按照过滤要求下载Github仓库
        └── repo_tree.py # 生成repo文件目录结构
  └── dependency_analyzer
        ├── ast_parser.py # AST解析代码仓，生成组件
        ├── filter_components_by_cis.py # 根据图结构过滤重要性，保留前 60-80% 的重要的组件，可覆盖原dependency_graph.json
        └── topo_sort.py # 将组件构成图
  └── visualizer # task Agents Pipeline 处理组件流程可视化
  └── fiter_readme.py # 离线测试 agent/readmefilter.py是否正确
  └── generate_wiki # wiki Agents Pipeline 入口
  └── run_ast_parser.py # 生成dependency_graph.json
  └── run_repo_tree.py # 生成 repo_tree.json
  └── main.py # task agents pipeline 入口
```

## 🛠 核心工作流

1. WIKI Agents 系统 (知识建模)该系统（RecursiveRepoWikiSystem）

采用自下而上的思路构建代码仓的“百科全书”：

Context Manager: 摘要 README.md，提取全局业务术语，生成“身份卡”。
Atomic Analyzer: 执行“原子级”理解，将 docstring 聚合成模块级语义摘要。
Architect: 基于依赖图抽取“架构洞见”（如 Hub 包、分层模式）。
Wiki Builder: 组装生成多级 Markdown 页面，作为后续阶段的本地 RAG 知识库。

2. Task Agents 系统 (数据生产)采用中心化编排架构，通过 Orchestrator 维护全局状态：

Reader (需求分析官)：判断当前代码信息是否足以理解业务。若不足，则向 Searcher 发起请求。
Searcher (资料检索员)：从 AST 树中拉取关联代码片段，或从 WIKI 中检索业务文档。
Writer (高级撰稿人)：基于完整的上下文，按照 Business Requirement -> Logic Design -> Code Implementation 的链路进行推理并生成产物。

## 🚀 快速开始

第一步：元数据准备将目标代码仓放入 data/，目前参数配置以示例代码仓raw_test_repo/为例运行。

1. 生成代码仓目录树
python run_repo_tree.py

2. 解析 AST 生成依赖图与组件信息
python run_ast_parser.py

3. (可选) 按照图统计特征过滤重要性组件
python filter_components_by_cis.py

第二步：vllm启动推理模型
请参考 scripts/下的bash文件，目前采用Qwen3-Next-80B-A3B-Instruct，
建议使用上下文窗口长的模型做推理，上下文容量能保证系统执行

第三步：构建 RAG 知识库运行 Wiki Agents 系统，生成业务逻辑文档。
python generate_wiki.py

第四步：自动化生成训练数据启动主程序，开始递归生成 QA 对与设计方案。
python main.py

## 参数

1. Agent相关参数请参考Config/agent_config.yaml
2. Data路径相关参数请参考Config/data_config.yaml
3. 下载Github代码仓相关参数请参考download_repo_config.yaml

## 📊 数据示例

1. 问答任务 (QA)系统通过 TRACE 链路确保回答深度：Q: 系统如何在库存修改期间维护审计追踪？A: mod() 方法被扩展，在扣减成功时将时间戳、前后库存水平记录到内部列表。TRACE: 业务需求（合规调试）-> 逻辑设计（领域对象内捕获状态转换）-> 代码实现（在 mod 期间追加审计条目）。

2. 设计任务 (Design)基于现有架构提出的需求驱动式方案：Requirement: 为所有数量变动添加审计追踪。Strategy: 扩展现有的 Item 类结构，利用 datetime 记录状态变更，并通过只读副本暴露接口。TRACE: 业务需求 -> 设计模式 (Domain Event) -> 代码实现。
