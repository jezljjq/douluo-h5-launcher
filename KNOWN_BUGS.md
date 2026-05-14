# 已知问题/重复踩坑记录

**目标：避免同样的问题反复出现。**

---

## 1. f-string 嵌套逃逸

**场景**：`gui.py` `_serial_worker` 中用 f-string 生成子进程代码。

**问题**：外层 f-string 会求值 `{变量}`。子进程内部的变量（如 `wn`, `result`）在外部不存在。

**症状**：`NameError: name 'wn' is not defined`

**正确做法**：子进程代码中的变量用 `str()` 拼接，不要用 f-string。
```python
# ❌ 错误
print(f"[W{wn}] {msg}")

# ✅ 正确
print("[W" + str(cfg["game_window_no"]) + "] " + str(msg))
```

**出现次数**：2 次（wn, result）

---

## 2. JSON 文件编码

**场景**：`write_text(json.dumps(...))` 写临时配置。

**问题**：默认编码是系统 GBK，子进程读 UTF-8 时报错。

**症状**：`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xb5`

**正确做法**：显式指定 `encoding="utf-8"`

---

## 3. Dm BindWindow 不可用

**结论**：Dm 7.2607 Win11 全窗口全模式崩溃（36/36）。禁止重试。

---

## 4. Playwright asyncio 冲突

**结论**：`sync_playwright()` greenlet event loop 不释放。方案：子进程隔离。

---

## 5. Tesseract 读 canvas 中文无效

**结论**：canvas 游戏文字 OCR 不可用。方案：模板匹配 / 视觉检测。

**OCR 纠错顺序**：先纠错（o→0, l→1）再匹配，避免去空格后产生假阳性。

---

## 6. Canvas 游戏 isTrusted

**结论**：Playwright/CDP 合成事件全部被拦截。方案：Dm 前台点击。

---

## 7. Dm 剪贴板冲突

**症状**：`OpenClipboard` 报错 "句柄无效"，重试3次失败。

**方案**：用 `clip.exe` 子进程设置剪贴板 + Dm `Ctrl+V` 粘贴。不用 `win32clipboard` API，也不用 `KeyPressChar` 逐字输入。

**出现次数**：2 次（OpenClipboard API 冲突, KeyPressChar 焦点不确定）

---

## 8. 子进程 cwd 继承导致模块找不到

**场景**：GUI 从上级目录启动（如 `python 上号器/main.py`），子进程继承 cwd 而非项目根目录。

**症状**：`ModuleNotFoundError: No module named 'douluo_launcher'`（子进程 stderr）

**正确做法**：Popen/run 必须显式传 `cwd=project_root`，不可依赖父进程 cwd。同时设 `PYTHONPATH` 环境变量作为双保险。

---

## 9. cv2.imread 不支持中文路径

**场景**：`app_root()` 返回含中文的绝对路径（如 `D:\Ai\codex\上号器\...`）后，`cv2.imread()` 返回 None。

**症状**：`无法读取模板: D:\Ai\codex\上号器\...`，但文件确实存在且 PIL 可正常打开。

**正确做法**：用 `cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)` 代替 `cv2.imread(str(path))`。

**出现次数**：1 次（打包 exe 后绝对路径含中文）

---

## 10. exe 调用 32 位 Python 弹黑框

**场景**：所有子进程调用（`py`、`python`、`tesseract`、`clip`、`taskkill`）均可能弹出控制台窗口。

**症状**：Dm 点击、OCR 识别、输入剪贴板、进程清理时短暂黑框闪现。

**根因**：`pytesseract` 内部调用 `tesseract.exe` 时不传 `CREAT_NO_WINDOW`，是最后一次黑框的来源。

**正确做法**：
1. 所有显式 `subprocess.run`/`Popen` 加 `creationflags=CREATE_NO_WINDOW`（6 处：automation.py 4 + dm_click_helper.py 2 + dm_client.py 1 + gui.py 3 = 实际已全项目覆盖）
2. `automation.py` 模块级 monkey-patch `subprocess.Popen`，默认注入 `CREAT_NO_WINDOW`，一劳永逸覆盖 pytesseract 等第三方库的内部子进程调用

**出现次数**：1 次（打包 exe 后发现）

**⚠ 2026-05-12 补充**：monkey-patch 必须用 **class 包装**，不能用 function 替换。因为 `asyncio.windows_utils.Popen` 继承自 `subprocess.Popen`，用 function 替换会导致 `TypeError: function() argument 'code' must be code, not str`（Playwright → asyncio → windows_utils 触发）。修复见 `automation.py` 中的 `_NoConsolePopen` 类。

---

## 11. Treeview 新增列后 `values[-1]` 指向错误列

**场景**：在 CSV Treeview 增加 `timing` 列后，`_set_csv_status` 用 `values[-1]` 写入状态，但 `-1` 变成 `timing`（第7列）而非 `status`（第6列）。

**症状**：失败时状态栏显示"已输入通行证"而非"失败"。

**正确做法**：用显式索引 `values[6]` 代替 `values[-1]`。`_set_status` 同理改 `values[5]`。

**出现次数**：1 次

---

## 12. 方式二 `finally` 固定 `sleep(3)` 浪费

**场景**：`run_method2` 的 `finally` 块无条件 `time.sleep(3)`，已登录账号不打开浏览器也白等3秒。

**症状**：31个已登录账号串行，浪费 93s。

**正确做法**：只在 `browser is not None` 时 sleep，改为 2s。

**出现次数**：1 次

---

## 13. 方式一 retry=1 缺少 `raise RuntimeError`

**场景**：`run_game_flow` 中 retry=1 校验超时后 `if retry == 0: continue` 穿透到 `except`，无异常则直接 `return False`，`STATUS:失败` 从未发出。

**症状**：方式一失败时状态栏不更新为"失败"。

**正确做法**：`if retry == 0:` 后加 `raise RuntimeError(...)`。

**出现次数**：1 次
