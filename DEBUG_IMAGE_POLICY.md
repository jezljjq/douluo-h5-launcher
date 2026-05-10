# 调试截图管理策略

**目标：避免 debug_ocr/ 堆积大量一次性截图，区分临时/保留/失败现场。**

---

## 1. 目录结构

```
debug_ocr/
├── _tmp/                          ← 临时截图（每步/每次运行结束自动清理）
├── _error/                        ← 失败时 _tmp/ 内容移入（排查后手动删除）
├── template_passport_btn.png      ← 永久：通行证按钮模板
├── browser_pos.json               ← 永久：浏览器渲染区坐标缓存
└── latest_ocr_success.png         ← 保留：最新 OCR 成功截图
```

---

## 2. 生命周期规则

### 临时截图（_tmp/）

- **创建**：流程各步骤中通过 `_capture_browser_client()` 和 `_extract_passport_from_login_window()` 自动写入 `_tmp/`
- **清理时机**：
  - 每个 retry 循环开头：`_clean_tmp()` 清除上一轮残留
  - OCR 成功后：`_clean_tmp()` 清除 OCR 中间图
  - 登录成功后：`_clean_tmp()` 清除全流程临时图
  - 最终失败后：`_clean_tmp()` 清除残留
- **日志**：每次删除文件时记录：`删除临时截图: <文件名>`

### 失败现场（_error/）

- **触发**：任何异常发生时，`_save_error_snapshots()` 自动执行
- **行为**：将 `_tmp/` 下所有文件移动到 `_error/`
- **日志**：`失败现场已保留: _error/ (3 个文件)`
- **不自动清理**：`_error/` 目录由用户手动管理

### 永久保留文件

| 文件 | 说明 |
|------|------|
| `template_passport_btn.png` | 按钮模板，手动创建，不被自动清理 |
| `browser_pos.json` | 浏览器坐标缓存，每次覆盖写入 |
| `latest_ocr_success.png` | 最新 OCR 成功截图，每次成功覆盖 |

---

## 3. 代码入口

| 方法 | 文件 | 说明 |
|------|------|------|
| `_tmp_path(name)` | automation.py | 生成 `_tmp/<name>` 路径 |
| `_clean_tmp()` | automation.py | 删除 `_tmp/` 下所有文件 |
| `_save_error_snapshots()` | automation.py | 移动 `_tmp/` → `history/error_ts/` |
| `_save_latest_ocr_success(img)` | automation.py | 保存 `latest_ocr_success.png` |

---

## 4. 注意事项

- 不要手动删除 `_tmp/` 目录本身，只清理其中的文件
- `history/` 目录不会自动清理，需定期手动处理
- 不要在代码中直接写 `debug_ocr/xxx.png`，统一通过 `_tmp_path()` 或 `self._debug_dir` 访问
