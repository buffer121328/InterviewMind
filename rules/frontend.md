# 前端规则

## 范围

适用于 `web/` 下的 Next.js、React、Zustand、API client 与 UI 组件。

## 约定

- 前端状态统一通过 `web/store/useInterviewStore.ts` 及 slices 管理，避免在组件中复制长期业务状态。
- 模型配置保存在前端设置页；新增通道时同步更新 `ApiConfig` 类型、`DEFAULT_API_CONFIG`、`getApiConfigForRequest()` 与设置页选择器。
- RAG/mem0 模型 Key 优先通过前端 `api_config` 传给后端，不再默认写入 `.env`。
- 组件内不要打印完整 `apiConfig`、API Key、简历全文或浏览器 localStorage。
- UI 行为变化优先补类型检查和用户可见边界测试；至少运行 `npm run typecheck`。
- 不要让前端直接绕过后端审批、权限、BOSS 投递确认或工具治理策略。

## 安全注意

- localStorage 中的模型 Key 是明文，所有新增入口都要提示用户不要截图/共享配置。
