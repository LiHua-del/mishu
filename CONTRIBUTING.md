# 参与开发

感谢你帮助改进觅书。项目优先考虑简单、稳定、可解释和低资源占用。

## 开始前

1. 先阅读 [ARCHITECTURE.md](ARCHITECTURE.md)，确认不会破坏固定六本、来源硬约束和口味信号边界。
2. 不提交正文、私有接口、账号 Cookie、绕过验证的代码或固定内置书单。
3. 平台页面解析变化必须附最小脱敏样本与回归测试。

## 本地验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_preference_model.js
python3 -m compileall -q server.py mishu
```

涉及部署时再执行：

```bash
docker build -t mishu:test .
```

## 改动原则

- 新平台解析放在 `mishu/sources/`，推荐决策放在 `mishu/recommendation/`。
- AI 只能分析已有候选，不能添加、替换或绕过硬筛选。
- 只有详情、想看、喜欢和明确不喜欢等行为能形成口味证据；单纯展示不是偏好。
- 外部网络请求必须有超时、并发上限和失败回退。
- UI 改动同时检查 iPhone 两列布局、键盘操作、触控尺寸和深色主题。

提交前请确认没有把 `.env`、`runtime-data/`、截图中的个人信息或任何密钥带入提交。
