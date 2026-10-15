# 部署指南

觅书适合部署在一台低配置 Linux VPS 上。推荐结构是：

```text
Internet → HTTPS (Caddy / Nginx) → 127.0.0.1:8001 → Docker 容器 → SQLite 数据卷
```

## 1. 准备配置

```bash
cp .env.example .env
```

至少填写：

```dotenv
MISHU_ACCESS_CODE=一段只用于打开网页的长口令
MISHU_SESSION_SECRET=另一段独立的随机长字符串
MISHU_COOKIE_SECURE=1
```

可用以下命令分别生成两段随机值，二者不要相同：

```bash
openssl rand -hex 32
```

AI 和 Brave 搜索均为可选项。没有配置时，基础推荐、平台书库、口味学习和同步仍可用。

## 2. 启动容器

```bash
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8001/api/health
```

默认只监听 VPS 本机回环地址，不直接暴露容器端口。

## 3. 配置 HTTPS

将 `deploy/Caddyfile.example` 中的域名改成自己的域名，然后让 Caddy 代理到 `127.0.0.1:8001`。代理必须保留 `X-Forwarded-Proto`；Caddy 默认会正确设置，应用据此发送 Secure Cookie。

若使用 Nginx，核心配置为：

```nginx
location / {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 70s;
}
```

## 4. 升级与回滚

升级前备份数据库：

```bash
mkdir -p backups
sqlite3 runtime-data/mishu.db ".backup 'backups/mishu-$(date +%Y%m%d-%H%M%S).db'"
docker compose up -d --build
```

升级后检查：

```bash
docker compose ps
docker compose logs --tail=100 mishu
curl --fail http://127.0.0.1:8001/api/health
```

回滚代码时不要删除 `runtime-data/`；先停止容器，再恢复经过验证的数据库备份。

## 5. 运行维护

- 定期备份 `runtime-data/mishu.db`，并测试恢复。
- 定期查看设置页的来源状态；平台公开页面改变时，旧候选仍可短期使用，但应尽快更新适配器。
- 反向代理和系统日志不要记录查询串、Cookie 或请求体。
- 不要把数据库目录做成公开静态目录。
- 若用户很少，1 核 CPU、512 MB–1 GB 内存通常足够；来源刷新时会有短时网络和 CPU 峰值。

## 6. 带宽预估

应用自身的 HTML、CSS、JavaScript 和图标约为数百 KB，Service Worker 首次加载后会缓存静态资源。推荐接口主要返回六本书的元数据，封面通常由手机直接向各平台图片域名加载，因此这些封面流量通常不经过 VPS。

实际 VPS 流量主要来自：

1. VPS 请求平台榜单、书库和少量详情页；
2. 手机与 VPS 之间的推荐 JSON、同步记录和设置请求；
3. 可选 AI 请求的文本内容。

个人低频使用一般属于低流量服务。平台候选池冷启动或连续细筛换批时流量会明显高于日常缓存命中；请以 VPS 月度网卡统计为准。

本项目在 2026-08-24 的发布测试中，候选池命中的六本推荐响应约 37 KB；五个平台完整来源巡检约下载 39 MB、上传 0.9 MB。若完整巡检每周运行一次，约为 160 MB/月；每天运行一次约为 1.2 GB/月。该巡检不是每次换批都会触发，实际页面体积和平台结构也会随时间变化。
