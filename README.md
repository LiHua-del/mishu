<div align="center">
  <img src="web/icons/logo-mark.png" width="72" height="72" alt="觅书图标">
  <h1>觅书</h1>
  <p>可自行部署的网络小说发现工具，聚合多平台榜单，支持按频道、题材和阅读偏好筛选推荐。</p>
  <p>
    <a href="https://github.com/pipi242526/mishu/actions/workflows/ci.yml"><img alt="Tests" src="https://github.com/pipi242526/mishu/actions/workflows/ci.yml/badge.svg"></a>
    <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-C86B56?style=flat-square&logo=python&logoColor=white">
    <img alt="Docker" src="https://img.shields.io/badge/Docker-Ready-718273?style=flat-square&logo=docker&logoColor=white">
    <img alt="PWA" src="https://img.shields.io/badge/PWA-Ready-B47A3B?style=flat-square">
    <a href="LICENSE"><img alt="GNU AGPL v3.0" src="https://img.shields.io/badge/License-AGPL%20v3-74566F?style=flat-square"></a>
  </p>
</div>

<p align="center">
  <img src="docs/images/readme-hero-dark.webp" width="100%" alt="觅书项目主视觉">
</p>

## 📖 项目概述

觅书从起点、番茄、书旗、七猫和 QQ 阅读的公开书库与榜单中整理候选书目。用户可按频道、题材、细分标签、篇幅和连载状态筛选，并以每批 6 本的形式查看推荐结果。

本项目仅展示书名、作者、封面、简介及平台链接，不提供小说正文。确认书目后，可复制书名至其他阅读工具中检索。

## 热榜研究扩展

在原版觅书基础上增加独立热榜研究页面：[打开热榜研究](http://127.0.0.1:8001/hotlists.html)。支持五站已接入榜单、全部频道与分类、范围联网刷新、每日快照及近 7／30 天跟踪。保留原版六本推荐与 AGPL-3.0 许可证。

用法、来源范围和数据边界见 [热榜研究说明](docs/HOTLISTS.md)，版本记录见 [CHANGELOG](CHANGELOG.md)。

## ✨ 主要功能

| 功能 | 说明 |
| --- | --- |
| 🌐 多平台候选 | 联网整理五个平台的公开书目，不使用固定内置书单 |
| 🔎 条件筛选 | 支持频道、题材、细分标签、篇幅及连载状态 |
| 🎯 推荐模式 | 提供热门、随机和个性三种模式，每批展示 6 本 |
| 🧠 偏好学习 | 根据详情浏览、想看和不想看等明确操作调整后续排序 |
| 🔄 跨设备同步 | 同步书单与偏好记录，不同步 AI 接口及密钥 |
| ✦ 可选 AI | 对真实候选进行内容分析和辅助排序，未配置时使用基础推荐 |
| 📱 移动端支持 | 提供 PWA、深色模式、主题色及 iPhone 安全区适配 |

## 🚀 安装与启动

### Docker 部署（推荐）

准备一台已安装 Docker Engine 和 Docker Compose 的 Linux、macOS 或 Windows 设备。

#### 1. 获取项目

```bash
git clone https://github.com/pipi242526/mishu.git
cd mishu
```

#### 2. 创建配置

```bash
cp .env.example .env
```

公网部署前，编辑 `.env` 并至少填写以下项目：

```dotenv
MISHU_ACCESS_CODE=用于访问服务的长口令
MISHU_SESSION_SECRET=独立的随机长字符串
MISHU_COOKIE_SECURE=1
```

会话密钥可使用以下命令生成：

```bash
openssl rand -hex 32
```

#### 3. 启动服务

```bash
docker compose up -d --build
```

#### 4. 检查状态

```bash
docker compose ps
curl --fail http://127.0.0.1:8001/api/health
```

服务启动后访问 <http://127.0.0.1:8001>。默认端口仅绑定本机回环地址；公网使用时应通过 Caddy 或 Nginx 提供 HTTPS。配置、备份和升级方式见 [部署指南](docs/DEPLOYMENT.md)。

> 觅书依赖服务端接口和 SQLite，不能直接部署到 GitHub Pages。

### Python 本地运行

本地运行需要 Python 3.10 或更高版本，无第三方运行依赖。

```bash
git clone https://github.com/pipi242526/mishu.git
cd mishu
HOST=127.0.0.1 python3 server.py
```

服务启动后访问 <http://127.0.0.1:8001>。直接打开 `web/index.html` 无法使用实时推荐、同步及本地数据功能。

## ⚙️ 配置

完整配置见 [.env.example](.env.example)。常用项目如下：

- `MISHU_PORT`：Docker 的本机映射端口，默认 8001
- `PORT`：直接运行 Python 时的监听端口，默认 8001；Python 不自动加载 `.env`
- `MISHU_ACCESS_CODE`：公网访问口令
- `MISHU_SESSION_SECRET`：会话与同步凭据签名密钥
- `MISHU_COOKIE_SECURE`：通过 HTTPS 使用时设为 `1`
- `AI_API_URL`、`AI_API_KEY`、`AI_API_MODEL`：可选的 OpenAI 兼容接口
- `BRAVE_SEARCH_API_KEY`：可选的搜索补充能力

AI 未配置或请求失败时，系统自动使用基础推荐。AI 仅分析已获取的真实候选，不生成书目，也不绕过筛选条件。

## 💾 数据与同步

- 书单、偏好记录和候选缓存保存在 `runtime-data/mishu.db`
- Docker 升级或迁移前，请先备份 `runtime-data/`
- 跨设备同步包含书单和偏好记录，不包含 AI 地址、模型及密钥
- AI 密钥仅保存在服务端，不写入浏览器备份

## ⚠️ 使用限制

- 项目依赖公开平台页面，结构调整、访问限制或网络差异可能影响候选数量
- 热度依据公开榜单、点击、收藏或订阅信息计算，不代表准确阅读人数
- 觅书与起点、番茄、书旗、七猫、QQ 阅读及其运营方无隶属或合作关系
- 使用及部署本项目时，请遵守相关平台条款，不得提交账号 Cookie、密钥或小说正文

## 🧪 开发

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_preference_model.js
python3 -m compileall -q server.py mishu
```

## 📚 文档

- [项目架构](ARCHITECTURE.md)
- [部署与维护](docs/DEPLOYMENT.md)
- [参与开发](CONTRIBUTING.md)
- [安全说明](SECURITY.md)

## 📜 许可证

本项目基于 [GNU Affero General Public License v3.0](LICENSE) 发布。修改并通过网络提供服务时，须依照许可证要求向用户提供对应源代码。
