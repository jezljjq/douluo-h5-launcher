# Codex Skills / MCP 自动调用规则

## 已安装工具

当前 Codex 已安装并启用以下工具：

- codebase-recon
- brooks-lint
- webapp-testing
- Playwright MCP
- Context7 MCP

MCP 当前状态应通过以下命令验证：

```bash
codex mcp list
```

## 自动调用规则

- 遇到陌生代码库、需要理解项目结构、历史热点、风险文件、模块职责时，优先使用 `codebase-recon`。
- 遇到代码审查、架构健康、技术债、测试质量、可维护性评估时，优先使用 `brooks-lint` 相关能力。
- 遇到本地 Web 应用验证、前端交互检查、页面截图、浏览器日志、UI 回归测试时，优先使用 `webapp-testing` 或 Playwright MCP。
- 遇到需要浏览器自动化、页面导航、可访问性快照、截图验证时，优先使用 Playwright MCP；使用前先确认浏览器运行时可用。
- 遇到库、框架、SDK、CLI、云服务的用法、版本差异、配置和 API 文档问题时，优先使用 Context7 MCP 查询官方/当前文档。

## 使用约束

- 不要凭猜测写 MCP 配置；需要修改前必须先读取现有 `C:\Users\Administrator\.codex\config.toml` 并备份。
- 不要乱填 API key、token 或密钥；如果工具要求密钥，先记录需求并询问用户。
- 对业务项目默认只读分析；需要修改业务代码时，必须确认任务明确要求修改。
- 禁止批量删除文件，禁止为了验证工具能力而改动业务逻辑。
