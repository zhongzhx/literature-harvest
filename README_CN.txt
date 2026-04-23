关键词文献自动抓取与下载 Skill 使用说明

1. 这是什么
这是一个可复用的本地文献抓取工具包，用来根据任意关键词自动搜索和下载研究文献。
它适合做的事情包括：
- 按关键词批量搜索文献
- 自动生成候选文献表
- 尝试下载可合法访问的 PDF 或全文
- 当只能拿到 HTML 页面时，再做一次 PDF 追链
- 最后对下载结果做去重


2. 包含哪些内容
本文件夹内主要包括：
- SKILL.md
  给 AI/agent 看的 skill 说明
- scripts/run_keyword_harvest_no_dedup.py
  新建一次文献抓取任务
- scripts/continue_download_and_dedup.py
  继续下载剩余文献、HTML 二次追 PDF、去重
- references/config_template.json
  配置模板，改关键词时主要编辑这个文件
- references/prompt_template.md
  可以直接交给其他 AI/agent 的提示词模板
- literature_harvest/scripts/
  已经打包好的底层依赖脚本，别人单独拿走这个 skill 也能运行

3. 运行前准备
建议环境：
- Windows
- PowerShell
- Python 3.13（或接近版本）
- 能访问 PubMed、Europe PMC、Crossref、OpenAlex

不需要你自己先准备：
- literature_harvest/
- search_pubmed.py
- download_fulltexts.py

这些已经被打包进 skill 里了。

4. 基本使用流程
第一步：复制并修改配置文件

打开：
- references/config_template.json

重点修改：
- queries
- include_terms
- secondary_terms
- exclude_terms

其中：
- queries 是实际搜索的查询语句
- include_terms 是你想重点保留的关键词
- secondary_terms 是辅助相关词
- exclude_terms 是你想排除的词

建议把修改后的配置另存为一个新文件，例如：
- my_topic_config.json

5. 启动一次新抓取

命令格式：

py -3.13 .\scripts\run_keyword_harvest_no_dedup.py --output-root "<输出目录>" --config "<配置文件路径>" --run-name "<运行文件夹名>"

示例：

py -3.13 .\scripts\run_keyword_harvest_no_dedup.py --output-root "D:\literature_runs" --config ".\references\my_topic_config.json" --run-name "marine_fungal_metabolites_20260423"

运行后会在 <输出目录>\<运行文件夹名> 下生成：
- 候选文献表
- 高优先级表
- 中优先级表
- 下载日志
- 下载文件夹

6. 中断后如何续跑

如果任务很大，中途停止很正常。
可以直接用同一个运行目录继续下载：

py -3.13 .\scripts\continue_download_and_dedup.py --run-root "<运行目录>" --retry-failed

示例：

py -3.13 .\scripts\continue_download_and_dedup.py --run-root "D:\literature_runs\marine_fungal_metabolites_20260423" --retry-failed

这个脚本会做三件事：
1. 继续下载还没成功的文献
2. 对已保存的 HTML 页面尝试二次追链 PDF
3. 对下载结果去重，并生成去重后的文件夹

7. 主要输出文件说明

在运行目录里通常会看到：
- keyword_research_candidate_table.csv
  全部候选记录
- keyword_research_high_priority.csv
  高优先级记录
- keyword_research_medium_priority.csv
  中优先级记录
- downloaded_pdfs/
  原始下载结果
- downloaded_pdfs_deduplicated/
  去重后保留的文件
- download_logs/keyword_research_download_log.csv
  主下载日志
- download_logs/keyword_research_html_second_pass.csv
  HTML 二次追 PDF 的日志
- keyword_research_dedup_manifest.csv
  去重清单
- keyword_research_harvest_summary.md
  汇总报告

8. 关于 PDF、HTML、XML

要注意：
- success 不一定等于“拿到了 PDF”
- 有些站点只能拿到 HTML 或 XML 全文
- 只有扩展名是 .pdf 或日志中 content_format = pdf 的，才是真正 PDF

因此，下载结果一般分成三类：
- 直接拿到 PDF
- 只拿到 HTML/XML
- 无法访问，仅保留元数据

9. 去重规则

去重阶段主要按以下顺序处理：
1. DOI
2. 标题标准化
3. 文件哈希

并优先保留：
- PDF
- 文件更完整的版本

10. 使用建议

如果你的目标是“尽可能多抓下来”，建议：
- 第一轮不要卡得太死
- 先放宽关键词
- 先抓、先下、先留日志
- 再根据结果做二次筛选

如果你的目标是“更干净、更少噪音”，建议：
- 在 include_terms 和 exclude_terms 上收紧
- 在 queries 里用更具体的组合词

11. 常见问题

为什么很多文件是 HTML，不是 PDF？
因为有些站点只提供网页全文，不直接提供 PDF。
脚本会先把合法可访问的全文保存下来，再尝试二次追 PDF。

为什么会有重复文献？
因为第一次抓取是先不去重的，目的是先尽量收全。
去重步骤在续跑脚本里完成。

为什么有些文献下不下来？
常见原因包括：
- 403 / 订阅限制
- 站点跳转但不给直接文件
- 页面可见但 PDF 不公开
- 网络请求超时

这些情况都会写进日志，不会被静默丢弃。

