# 安全说明

## 报告问题

请优先使用 GitHub 仓库的 **Security → Report a vulnerability** 私密报告入口。若仓库尚未启用该入口，可先创建一个不含漏洞细节的 Issue，请维护者提供私密联系方式。

不要在公开 Issue、截图或日志中提交以下内容：

- `.env` 内容、访问口令或 `MISHU_SESSION_SECRET`
- AI API 密钥
- 同步令牌、会话 Cookie
- `runtime-data/` 数据库或可识别个人口味的数据

报告中请包含受影响版本、复现条件、影响范围和建议修复方式；公开披露前请给维护者合理的修复时间。

## 部署基线

- 公网部署必须通过 HTTPS，并设置访问口令与独立的会话密钥。
- 应用端口默认只绑定 `127.0.0.1`，由 Caddy 或 Nginx 反向代理。
- 容器以非 root 用户运行，根文件系统只读，移除 Linux capabilities，并限制进程数。
- `.env`、运行数据库、AI 密钥和同步记录均不应提交到 Git。
- 公开来源结构可能变化；请定期在设置页查看“实时来源状态”，不要绕过平台访问限制。

完整部署检查见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。
