# 中文经管重点期刊 RSS

本项目将19本中文经济学、管理学及相关重点期刊的公开官网文章列表转换为可由 Inoreader 订阅的 RSS 2.0 源。

> 这些 RSS 并非期刊官方提供。项目只保存公开元数据和原文链接，不保存论文全文。

## 覆盖期刊

- A1：中国社会科学、经济研究
- A2：管理世界、世界经济、金融研究、管理科学学报
- A3：经济学（季刊）、中国工业经济、数量经济技术经济研究、财贸经济、经济学动态、统计研究、系统工程理论与实践、中国管理科学、中国软科学、中国农村经济、地理研究、中国人口科学、求是

## 运行

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

只测试某一本期刊：

```bash
python run.py --journal jinrong-yanjiu
```

生成结果位于：

```text
docs/feeds/
```

主要综合源：

- `docs/feeds/a1-all.xml`
- `docs/feeds/a2-all.xml`
- `docs/feeds/a3-all.xml`
- `docs/feeds/all-journals.xml`

## 发布与订阅

### 方案一：GitHub Pages

1. 在 GitHub 创建空仓库 `chinese-econ-journal-rss`。
2. 上传本项目全部文件。
3. 打开仓库 **Settings → Pages**。
4. 在 **Build and deployment** 中选择：
   - Source：`Deploy from a branch`
   - Branch：`main`
   - Folder：`/docs`
5. 保存后，访问：

```text
https://你的GitHub用户名.github.io/chinese-econ-journal-rss/
```

例如全部期刊综合源：

```text
https://你的GitHub用户名.github.io/chinese-econ-journal-rss/feeds/all-journals.xml
```

将该地址直接添加到 Inoreader。

### 方案二：Raw 地址

即使未启用 Pages，也可以尝试订阅：

```text
https://raw.githubusercontent.com/你的GitHub用户名/chinese-econ-journal-rss/main/docs/feeds/all-journals.xml
```

GitHub Pages 地址通常更适合长期使用。

## 自动更新

`.github/workflows/update-feeds.yml` 每天在北京时间 08:30 和 20:30 自动运行，也支持在 Actions 页面手动触发。

抓取成功后，工作流会把更新后的 XML、状态文件和报告提交回仓库。

## 稳定性设计

- 自动发现网页中的原生 RSS/Atom，发现后优先使用。
- 没有原生源时，根据文章链接结构、标题文本和日期进行识别。
- 每本期刊的规则集中在 `journals.yml`，官网改版时无需修改主程序。
- 本次抓取为空或失败时保留历史条目，不覆盖成空 RSS。
- 同时输出单刊源、A1/A2/A3综合源和全部期刊综合源。
- `docs/report.md` 保存每本期刊最近一次抓取状态。

## 首次运行的重要说明

当前环境无法联网验证19个网站在2026年8月的实际HTML结构，因此本项目提供的是“可运行的自动发现框架和初始网址配置”，而不是已经逐站验收的最终选择器。

第一次 GitHub Actions 运行后，请查看：

```text
docs/report.md
```

如果某一本期刊显示“失败”或误识别，打开对应网页检查文章列表的 HTML，然后在 `journals.yml` 中为它补充：

```yaml
selectors:
  item: ".article-item"
  title: ".article-title"
  link: ".article-title a"
  date: ".article-date"
  author: ".article-author"
```

显式选择器的优先级高于通用识别。

## 合规与频率

- 每个起始页面之间默认间隔1.2秒。
- 每天只运行两次。
- 不绕过登录、验证码、付费墙或访问控制。
- 若网站明确禁止自动抓取，应停止抓取该站并改用官方提醒、数据库提醒或网页变化通知。
