# 上传到 GitHub

## 1. 创建仓库

在 GitHub 新建一个**公开空仓库**：

```text
chinese-econ-journal-rss
```

不要勾选自动生成 README、`.gitignore` 或 License，以免首次推送发生冲突。

## 2. Windows 一键上传

在项目文件夹空白处打开 PowerShell，执行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\publish_to_github.ps1 -RepoUrl "https://github.com/你的用户名/chinese-econ-journal-rss.git"
```

## 3. 首次生成真实 RSS

进入仓库：

```text
Actions → Update journal RSS → Run workflow
```

运行后检查：

```text
docs/report.md
```

其中会逐本列出成功、失败、保留旧源和识别条目数。

## 4. 启用 GitHub Pages

进入：

```text
Settings → Pages
```

设置：

```text
Source: Deploy from a branch
Branch: main
Folder: /docs
```

之后在 Inoreader 中添加：

```text
https://你的用户名.github.io/chinese-econ-journal-rss/feeds/all-journals.xml
```
