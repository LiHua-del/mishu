# 贡献指南

欢迎提交修复和改进。觅书优先保证稳定、清晰和低资源占用。

## 开始前

- 修改推荐逻辑或项目结构前，请先阅读 [项目架构](ARCHITECTURE.md)。
- 较大的改动请先创建 Issue，说明要解决的问题。
- 不要提交小说正文、私有接口、账号 Cookie、绕过验证的代码或固定书单。
- 修改平台解析时，请补充脱敏样本和测试。

## 改动约定

- 平台来源放在 `mishu/sources/`，推荐逻辑放在 `mishu/recommendation/`。
- 网络请求必须设置超时、并发上限和失败回退。
- AI 只分析已有候选，不能绕过筛选条件。
- 仅展示过的书不会影响口味，查看详情、想看和不想看等明确操作才会。
- 修改界面后，请检查手机布局、键盘操作、触控尺寸和深色主题。

## 本地验证

提交前运行：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_preference_model.js
python3 -m compileall -q server.py mishu
```

修改部署文件时，再运行：

```bash
docker build -t mishu:test .
```

## 提交说明

Pull Request 请写清改了什么、为什么改以及如何验证。界面改动请附截图，新功能请补测试。

提交前确认没有包含 `.env`、`runtime-data/`、个人信息、Cookie、令牌或密钥。
