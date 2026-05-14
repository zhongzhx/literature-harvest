# literature-harvest

学术文献批量检索与下载工具，一条命令搜索四个数据库，自动去重，按 OA 直链 → 机构访问 → 浏览器辅助的顺序尝试下载全文。

> 与 Claude Code 深度集成：`--score-only` 输出候选表，Claude 自动逐篇打分排序，再回传下载。

## 快速开始

```bash
# 安装
pip install literature-harvest

# 搜索 "microglia inflammation"，每个数据源取 100 篇
python -m literature_harvest harvest "microglia inflammation" --limit 100 --score-only

# Claude 评分后，按分数从高到低下载
python -m literature_harvest harvest "microglia inflammation" \
    --papers-file ./scoring_table.csv --download --institutional
```

## 工作原理

```
搜索                   评分                  下载
PubMed ─┐           ┌─────────┐          OA 直链 ─── ✅ PDF
PMC    ─┤  去重合并  │ Claude  │ 分数排序 机构访问 ─── ✅ PDF
EuropePMC ─┼──────▶ │ 逐篇评分 │────────▶ 浏览器 ───── ✅ PDF
Crossref ─┤          └─────────┘          └── 不可下载 ── 📋 手动队列
OpenAlex ─┘
```

1. **搜索** — 同时查 PubMed/PMC、Europe PMC、Crossref、OpenAlex
2. **去重** — DOI → PMID → PMCID → 标题归一化，按元数据完整度择优合并
3. **评分** — Agent 读取候选表，根据标题摘要对每篇打分（0-100）
4. **下载** — 按分数排序，依次尝试三种通道，实时显示进度

## 三种下载通道

| 通道 | 原理 | 需要什么 |
|------|------|----------|
| OA 直链 | 直接下载开放获取 PDF | 不需要额外条件 |
| 机构访问 | 通过 `requests.Session` 跟随 DOI 重定向，利用校园 IP/VPN 权限 | 校园网或 VPN |
| 浏览器辅助 | Playwright 打开出版商页面，复用浏览器登录态 | 浏览器已登录机构 |

三种通道依次尝试：OA 优先，其次机构，最后浏览器。都不可行则标记为 `manual_download_required`，写入手动队列。

## 参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `query` | 必填 | 检索关键词 |
| `--limit N` | 5000 | 每个数据源取回数量 |
| `--score-only` | — | 只搜索，输出候选表后停止 |
| `--download` | — | 启用下载 |
| `--papers-file PATH` | — | 评分表路径，按分数降序下载 |
| `--institutional` | — | 启用机构访问 |
| `--browser-assisted` | — | 启用浏览器辅助 |
| `--show-browser` | — | 显示浏览器窗口 |
| `--browser-profile-dir PATH` | — | 浏览器持久化配置目录 |
| `--output-root PATH` | `./harvest_output` | 输出根目录 |
| `--run-name NAME` | 自动生成 | 运行目录名 |
| `--email EMAIL` | 空 | 邮箱，用于 PubMed 礼貌池提高限速 |

## 输出文件

每次运行在 `harvest_output/<run_id>/` 下：

| 文件 | 用途 |
|------|------|
| `harvest_candidates.csv` | 候选文献表，Claude 读取并打分 |
| `harvest_candidates.jsonl` | 候选文献完整元数据 |
| `scoring_table.csv` | 打分结果，回传给下载命令 |
| `download_status.jsonl` | 每篇下载状态 |
| `download_summary.json` | 汇总统计 |
| `manual_download_queue.csv` | 需手动获取的文献 |
| `failed_downloads.csv` | 下载失败详情 |

## 下载状态速查

```
✅ oa_pdf_downloaded           OA 直链获取 PDF
✅ institution_pdf_downloaded  机构访问获取 PDF
✅ browser_pdf_downloaded      浏览器辅助获取 PDF
⚠  html_saved                 仅 HTML 全文
⚠  xml_saved                  仅 XML 全文
❌ manual_download_required    无法自动下载
❌ paywall_detected            付费墙无权限
❌ institution_login_required  需要机构登录
```

## 合规

此工具仅使用用户本地合法权限（校园 IP、VPN、浏览器登录态）。不绕过付费墙、不使用 Sci-Hub 等盗版来源、不将凭据写入日志或输出文件。

## 安装

依赖 `requests`、`pandas`、`beautifulsoup4`、`lxml`，Python ≥ 3.10。浏览器辅助需要额外安装 Playwright：

```bash
pip install literature-harvest[browser]
playwright install chromium
```
