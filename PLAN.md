# 微博超话助手 — 设计文档

本地桌面应用。给拍图频的站子用：懂艺人的话题/事件/梗，写文案时自动联想，语气像本人；开机自启、能推送。

## 核心认知：风格 ≠ 知识（地基）

- **文案库** 只教「怎么写」（语气/用词）——**不含梗义**。
- **术语/梗词典 + 事件库** 才是「写什么、梗指什么」——**必须有人写释义**。
- 全网大众梗 Qwen 预训练可能懂；**圈内梗/黑话/特定事件 100% 要人工喂**，无捷径。
- ⚠️ **释义必须每次写文案时检索注入 prompt**（没微调，模型不会"记住"）。
- ⚠️ 自动只能**提候选**，不能**确认含义**（7B 对不认识的圈内梗会自信编造）。
  → 流程：**机器缩小范围，人工校准产生知识**。

## 技术栈

| 层 | 选型 |
|---|---|
| 界面 | FastAPI 本地服务 + pywebview 独立窗口（HTML/CSS/JS）；端口默认 8756，被占自动换空闲口 |
| 打包 | PyInstaller 文件夹版（`app.spec` / `build.bat` → `dist/app/app.exe`）；`run_app.py` 为打包入口 |
| 图标 | `assets/icon.ico`（任务栏/窗口/托盘/通知/exe/快捷方式统一）；`tools/make_icon.py` 生成 |
| 模型 | Ollama（`qwen2.5:7b-instruct`，备选 `3b`）；首启向导可检测 + 一键下载 |
| 数据库 | SQLite（`data/fan.db`；打包后 data/ 落在 exe 旁，便携） |
| 定时 | APScheduler（进程内） |
| 推送 | winotify 桌面弹窗；短信预留接口 |
| 常驻 | pystray 托盘 + 关窗最小化到托盘 |
| 自启 | 启动文件夹快捷方式（app 内开关；打包态指向 exe） |

> **关窗不退出**——最小化到托盘，调度器继续运行，「开机自启 → 定时总结/推送」才成立。

## 功能模块

- **Dashboard**：状态卡（模型就绪 / 今日新事件 / 待校准候选 / 下次推送 / 下次总结）+ 快捷入口
- **写文案**：模板下拉 + 术语/事件联想 + 风格样本 → 生成 → 一键存入文案库
- **文案库**：风格来源（只教怎么写），手动录入 + 批量粘贴
- **术语/梗词典**：词条 = 术语 + 释义 + 类型 + 关联事件（知识核心）
- **事件库**：标题/时间/描述/关联梗/关联人物
- **校对台**：候选抽取（自动，标"可疑"）→ 逐条校准（标可信度：较可信 / 可能编造）→ 入库
- **总结事件**：按可配频率读未处理帖 → 模型总结 → 候选事件待确认
- **推送**：按可配刷新时间检查新事件/摘要 → 桌面弹窗；短信预留
- **设置**：模型、Ollama 地址、推送开关/频率、总结频率、开机自启、抓取配置（预留）

## 数据表

`posts` `captions` `terms` `term_candidates` `events` `prompt_templates` `settings` `push_log` `runs`

## 目录

```
weibochassistant/
├─ app/
│  ├─ main.py        入口：uvicorn 线程 + pystray 托盘 + pywebview 窗口
│  ├─ config.py      路径/常量
│  ├─ db.py          SQLite 建表 + CRUD
│  ├─ llm.py         Ollama 调用封装
│  ├─ scheduler.py   APScheduler 定时任务
│  ├─ notify.py      桌面弹窗 + 短信预留
│  ├─ autostart.py   开机自启
│  ├─ api.py         FastAPI 路由
│  └─ modules/       captions/terms/events/summarize/fetcher
├─ web/              index.html / app.js / style.css
├─ data/             fan.db
├─ requirements.txt
├─ run.bat
└─ README.md
```

## 阶段

- **阶段一（本次）**：骨架 + 三个库 + 写文案 + 校对台 + 弹窗 + 定时 + 自启 + 界面
- **阶段二（以后）**：真实超话抓取（cookie + containerid，只取增量）；短信推送

## 边界

- 它是**起草工具**，成品仍需本人顺一遍。
- 阶段一**不碰真实抓取**，避免风控/封号。
