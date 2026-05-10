# 日志策略

**双通道日志：GUI 前端简洁日志 + logs/run_时间.log 完整日志。**
**分级日志：normal（默认）/ debug（候选窗口详情等）通过 `log_level` 配置控制。**

---

## 1. 日志输出目标

| 目标 | 触发方式 | 级别 |
|------|----------|------|
| GUI 日志区域 | `_queue_log()` | 简洁（关键节点） |
| 文件日志 | `_write_file_log()` | 完整（所有细节） |
| 子进程 stdout | `print(..., flush=True)` | 完整（被主进程捕获） |

### GUI 前端（简洁日志）

只显示关键流程节点：OCR结果、状态变更、成功/失败/重试、弹窗检测结果。

### 文件日志（完整日志）

路径：`logs/run_<YYYYMMDD_HHMMSS>.log`

记录所有细节：候选窗口枚举、OCR 各变体输出、模板匹配得分、Dm 子进程输出、异常堆栈。

每次串行运行生成一个新日志文件。运行结束后写入汇总（总数/成功/失败/耗时）。

---

## 2. 关键日志格式

### 流程日志

```
[W1] [窗口1] 从登录程序窗口提取通行证
```

### 状态日志

```
STATUS:OCR中
STATUS:已提取通行证
STATUS:成功
```

### 通行证日志

```
PASSPORT:40f86bb2
```

### 结果日志

```
RESULT:True
RESULT:False
```

### 截图日志

```
临时截图已保存: _tmp/flow_step4_button_match_source.png
删除临时截图: flow_step4_button_match_source.png
失败现场已保留: _error/ (3 个文件)
```

---

## 4. 日志级别

通过 `automation_settings.json` 的 `log_level` 控制：

| 级别 | 输出内容 |
|------|----------|
| `normal` | 流程步骤、状态变更、OCR结果、点击操作、成功/失败 |
| `debug` | 以上 + 候选窗口枚举详情、OCR 各变体原始文本 |

`_vlog("debug", msg)` — 仅在 `log_level: "debug"` 时输出。

---

## 5. 子进程日志规则

- 所有输出使用 `str()` 拼接，**不使用 f-string**（KNOWN_BUGS #1）
- 每条消息后 `flush=True`，确保实时推送
- 特殊前缀行（`STATUS:`, `PASSPORT:`, `RESULT:`）不显示在 GUI 日志区域，仅解析为内部状态
- 出现次数：f-string 嵌套逃逸 2 次（wn, result）

---

## 6. 注意事项

- OCR 原始文本可能包含大量乱码，已通过 `_preview_text()` 截断到 200 字符
- stderr 输出会被截断到 200 字符（避免占用日志空间）
- RESULT 行匹配不含空格：`"RESULT:True"` 而非 `"RESULT: True"`（KNOWN_BUGS #1）
