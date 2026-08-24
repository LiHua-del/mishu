# 安全

## 报告安全问题

发现安全问题，请通过 GitHub 的 [私密漏洞报告](https://github.com/pipi242526/mishu/security/advisories/new) 联系维护者。

> [!IMPORTANT]
> 请勿在公开 Issue、截图或日志中披露漏洞细节和敏感信息。

请说明受影响版本、复现步骤和可能造成的影响。如有临时处理办法，也请一并提供。

## 提交前请检查

- 删除 `.env`、访问口令和 `MISHU_SESSION_SECRET`
- 隐去 AI API 密钥、Cookie、令牌和设备凭据
- 不要上传 `runtime-data/`、数据库或阅读偏好记录

## 安全部署

公开部署时：

- 使用 HTTPS，并设置访问口令和独立的会话密钥。
- 应用端口仅绑定 `127.0.0.1`，外部访问交给 Caddy 或 Nginx。
- 不要把配置、运行数据、密钥和同步记录提交到 Git。
- 定期查看设置页中的来源状态，及时更新失效的平台适配。

完整配置见 [部署指南](docs/DEPLOYMENT.md)。
