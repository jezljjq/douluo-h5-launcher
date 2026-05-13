# 方式二：账号密码 + 通行证上号 — 设计方案

**日期：2026-05-13**
**状态：方案已确认，进入阶段2实现**

> **修正记录（2026-05-13）：**
> 1. 阶段2-3 不重构 `run_game_flow()`，方式二新建独立入口 `run_method2()`
> 2. CSV 行号 = 游戏窗口号（第1行→窗口1，第9行→窗口9）
> 3. password 禁止写入临时 JSON / 日志 / debug 文件 / Dm 子进程
> 4. 阶段2 只做 CSV 导入，阶段3 只做账号密码登录，阶段4 再接通行证

---

## 一、文件修改清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `douluo_launcher/config.py` | **修改** | 新增 `CSVAccount` 数据类、CSV 加载函数 |
| `douluo_launcher/automation.py` | **修改** | 新增 `login_with_password()` 方法，拆分公共步骤 |
| `douluo_launcher/gui.py` | **修改** | 新增上号方式选择、CSV 导入按钮、CSV 账号表格 |
| `douluo_launcher/dm_client.py` | 不改 | — |
| `dm_click_helper.py` | 不改 | — |
| `automation_settings.json` | 不改 | — |
| `main.py` | 不改 | — |
| `tests/` | 暂不改 | 稳定后再加 |

---

## 二、明确不改的文件和模块

- `dm_click_helper.py` — Dm 点击底层
- `douluo_launcher/dm_client.py` — 窗口枚举、截图
- `douluo_launcher/__init__.py`
- `scripts/build_exe.bat` — 打包
- `automation_settings.json` — 配置
- `main.py` — 入口
- OCR 主流程（`_extract_passport_from_login_window`、`detect_login_page_state`、`_ocr_passport_from_text_region` 等）
- 已登录跳过逻辑
- 公告关闭
- 通行证按钮模板匹配
- Dm 点击 / Dm 链式调用
- 性能优化后的等待逻辑（canvas 轮询、快速校验、时间预算等）

---

## 三、新增数据结构

### CSVAccount（config.py 新增）

```python
@dataclass
class CSVAccount:
    name: str           # 账号名称或备注
    url: str            # 游戏入口链接
    username: str       # 账号
    password: str       # 密码（仅内存，禁止打印日志，GUI不显示明文）
    game_window_no: int # 分配的游戏窗口号（按CSV顺序1..N）
    passport: str = ""  # OCR 提取的通行证（运行时填充）
    status: str = "未开始"

    @property
    def key(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return f"{self.name} → 窗口{self.game_window_no}"
```

与 `AccountConfig` 的关系：`CSVAccount` 是独立新类，不继承不修改 `AccountConfig`。方式一继续用 `AccountConfig`，方式二用 `CSVAccount`。

### 新增 AutomationSettings 字段（可选，暂不加入）

考虑后续在 `AutomationSettings` 中增加账号密码登录相关配置（选择器、超时等），但阶段2-3先用硬编码常量，稳定后再提取为配置。

---

## 四、公共流程复用（阶段2-3不重构）

**阶段2-3 策略：** 不拆分 `run_game_flow()`。方式二新建独立方法 `run_method2()`，直接调用 `AccountRunner` 中已有的稳定函数（`_extract_passport_from_login_window`、`detect_login_page_state` 等），不做大规模提取。

**等方式二单账号稳定后（阶段5后），再考虑小范围提取公共函数。**

### 方式二在阶段2-3可复用的已有方法（不改动）

- `_extract_passport_from_login_window()` — OCR 通行证（阶段4接入）
- `detect_login_page_state()` — 状态判断
- `_quick_login_state()` — 快速状态检测
- `_ensure_not_stopped()` / `_wait_or_stop()` — 控制流
- `_window_position()` — 窗口布局计算

### 方式二新增方法

这些方法仅用于方式二，不改动已有代码：

| 方法 | 职责 |
|------|------|
| `_detect_login_form(page)` | 检测页面是否包含账号密码登录表单。返回 `True/False` |
| `_locate_login_elements(page)` | 定位 username 输入框、password 输入框、登录按钮。返回选择器或坐标 |
| `_fill_and_submit_login(page, username, password)` | 填表 + 提交登录 |
| `_wait_game_page_ready(page)` | 等待登录成功后进入正式游戏页（复用 canvas 轮询逻辑） |
| `run_method2(csv_account)` | 方式二入口方法：完整流程 |

### 方式二完整流程 `run_method2()`

```
1. _step_ocr_passport()                    → 获取通行证（公共）
2. _step_open_browser(csv_account.url)     → 打开浏览器（公共，不同URL）
3. _detect_login_form(page)                → 检测登录表单（方式二专属）
4. _locate_login_elements(page)            → 定位输入框和按钮（方式二专属）
5. _fill_and_submit_login(page, username, password) → 填表登录（方式二专属）
6. _wait_game_page_ready(page)             → 等待进入游戏页（方式二专属）
7. _step_close_notice(page)                → 关闭公告（公共）
8. _step_click_button_and_input(page, passport) → 按钮+输入（公共）
9. _step_verify_login()                    → 校验（公共）
```

---

## 五、GUI 修改

### 1. 上号方式选择

在运行控制区顶部增加 RadioButton 组：

```
○ 方式一：通行证上号    ○ 方式二：账号密码 + 通行证上号
```

默认选中方式一。切换时显示/隐藏对应控件。

### 2. 方式一控件（不变）

- 收藏夹文件路径
- 读取收藏夹按钮
- 根文件夹名称
- 层级下拉 / 账号下拉
- 运行按钮（单账号 / 当前层 / 全部）

### 3. 方式二控件（新增）

- "选择CSV" 按钮 → `filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])`
- "导入CSV" 按钮 → 校验表头 + 解析数据
- CSV 文件路径显示（只读）
- CSV账号列表 Treeview

### 4. CSV 账号列表 Treeview

列定义：

```
("name", "url", "username", "password_status", "window", "passport", "status")
```

列标题：名称 / 链接 / 账号 / 密码 / 窗口号 / 通行证 / 状态

password_status 列显示 `已填写` 或 `未填写`，永不显示明文。

### 5. 运行按钮逻辑

方式二下的三个运行按钮：
- 单账号运行 → CSV列表中选中的账号
- 当前层串行 → 不适用（CSV 没有层级概念），或改为 "CSV列表串行"（所有有效账号）
- 全部串行 → 所有 CSV 账号

方式二的账号传递给 `_start_serial_run()` 的变体 `_start_serial_run_method2()`。

### 6. 串行执行适配

在 `_serial_worker` 中根据当前模式调用不同入口：
- 方式一：`runner.run_game_flow()`
- 方式二：`runner.run_method2(csv_account)`

CSVAccount 的信息通过临时 JSON 文件传递给子进程（与 AccountConfig 相同的模式）。

---

## 六、CSV 导入流程

```
用户点击"选择CSV" → 选文件 → 显示路径
用户点击"导入CSV" →
  1. 打开文件，读第一行
  2. 校验表头完全等于 "name,url,username,password"
     不匹配 → 弹窗错误 "CSV格式错误，第一行必须是 name,url,username,password"
  3. 使用 csv.DictReader 逐行解析
  4. 对每一行：
     - name 为空 → 跳过
     - url 为空 → 跳过
     - username 为空 → 状态标记 "配置缺失"，不执行
     - password 为空 → 状态标记 "配置缺失"，不执行
     - 都有效 → 创建 CSVAccount，game_window_no = 行号（第1行→窗口1，第9行→窗口9）
  5. 显示在 CSV 账号表格中
```

---

## 七、账号密码登录界面识别

优先使用 DOM 选择器，不使用盲点坐标。

### 定位策略（按优先级）

**Username 输入框**：
1. `input[type="text"][name="username"]`
2. `input[type="text"]` 且 placeholder 含 "账号"/"用户名"/"手机"
3. 页面上第一个 `input[type="text"]`

**Password 输入框**：
1. `input[type="password"]`

**登录按钮**：
1. `button[type="submit"]`
2. 含文本 "登录"/"登入"/"进入游戏" 的 button 或 a 标签
3. `input[type="submit"]`

### 登录成功判定

点击登录后，轮询检测以下条件（复用 canvas 轮询逻辑）：
- 页面 URL 发生变化（不再包含 "login"）
- 游戏 canvas 元素出现
- 或页面标题/内容变化表明进入游戏

超时 30 秒判定失败。

---

## 八、密码安全规则

1. `CSVAccount.password` 仅存在主进程内存中
2. `CSVAccount.__repr__` / `__str__` 不包含 password
3. 日志输出规则：
   - 允许：`username=xxx, password=已填写`
   - 禁止：`password=真实密码`
4. 失败日志不包含密码
5. **禁止写入临时文件**：password 不写入临时 JSON、不写入 debug 文件、不写入 .log
6. **禁止传给子进程**：password 不传给 `dm_click_helper.py`（32位Dm子进程）
7. 方式二账号密码登录使用 Playwright DOM 操作（`page.fill()`），全程在主进程内完成
8. GUI 表格 password_status 列只显示 `已填写` / `未填写`

---

## 九、错误处理

方式二区分以下失败原因：

| 错误类型 | 触发条件 | 日志/提示 |
|----------|----------|-----------|
| CSV格式错误 | 表头不匹配 | CSV格式错误，第一行必须是 name,url,username,password |
| CSV字段缺失 | name/url/username/password 为空 | 账号 {name} 配置缺失：{缺失字段} |
| 未找到登录程序窗口 | `select_login_window_by_game_no` 返回 None | 未找到登录程序窗口 H5-{n} |
| 登录程序状态未知 | `detect_login_page_state` 返回非 qr_page 非 logged_in | 登录程序窗口状态未知 |
| OCR通行证失败 | 两次 OCR 都失败 | 通行证识别失败（页面状态={state}） |
| 打开url失败 | page.goto 超时/异常 | 打开链接失败: {url} |
| 未检测到登录表单 | `_detect_login_form` 返回 False | 未检测到账号密码登录界面 |
| 账号输入失败 | fill/click 失败 | 账号输入失败 |
| 密码输入失败 | fill/click 失败 | 密码输入失败 |
| 登录按钮未找到 | `_locate_login_elements` 找不到按钮 | 登录按钮未找到 |
| 登录后未进入游戏 | 等待超时 | 登录后未进入正式游戏页 |
| 后续通行证流程失败 | 方式一后半段失败 | 通行证流程失败: {具体原因} |

不写统一的"失败"。

---

## 十、开发阶段

### 阶段1：设计方案 ✅ 当前阶段

输出设计文档，确认后进入实现。

### 阶段2：CSV 导入

实现 `config.py` 中的 `load_csv_accounts()` 和 GUI 中的 CSV 导入控件。

### 阶段3：账号密码登录单步测试

实现 `_detect_login_form()`、`_fill_and_submit_login()`，单账号测试登录流程。暂不接通行证。

### 阶段4：接入方式一后半段

在 `run_method2()` 中接上步骤7-9（公告→按钮→输入→校验）。

### 阶段5：串行测试

单账号成功后，做 CSV 列表串行测试。

---

## 十一、回归要求

每个阶段完成后验证方式一：

1. 切换到方式一，读取收藏夹
2. 单账号运行 → 成功
3. 已登录跳过 → 正常
4. 需要登录的账号 → 正常
5. GUI 状态刷新 → 正常
6. 日志输出 → 正常

---

## 十二、当前限制

1. 只支持源码模式（`python main.py`），暂不打包
2. 账号密码登录界面定位优先用 DOM 选择器，固定坐标仅作为最后回退
3. 方式二的 game_window_no 按 CSV 行号分配（1..N）
4. 只支持前台串行，不支持并发
5. password 通过子进程临时文件传递时需加密或使用独立通道
