# 斗罗大陆 H5 上号器：客户端直登批次管理开发说明

## 一、当前方向

本项目最终目标是：使用 `X5Game.exe` 客户端完成斗罗大陆 H5 登录。

客户端路径：

```text
E:\Program Files\DLH5\X5Game.exe
```

项目目录：

```text
D:\Ai\codex\上号器
```

注意：

1. 最终窗口必须是 `X5Game.exe`。
2. 不是 Chrome / Edge / Playwright 普通浏览器登录。
3. 浏览器 HAR、login.php、JS、Network 分析只是辅助理解链路，最终逻辑必须落到 `X5Game.exe`。
4. 原后台通行证 / OCR 流程必须保留作为兜底，不允许破坏。
5. 日志必须脱敏，不输出完整 token、sign、cookie、IMEI、uid、session、openid、完整 login.php URL。
6. 不写死窗口数量、坐标、账号映射、分辨率、路径、端口等，能配置就配置。

---

## 二、已验证的客户端直登路线

`X5Game.exe` 支持 CDP 调试端口。

启动参数：

```text
--remote-debugging-port=9222 --remote-allow-origins=*
```

已验证：

```text
http://127.0.0.1:9222/json/version 可访问
/json 能看到客户端内部页面
客户端内核是 Chrome/66.0.3359.117
```

Playwright `connect_over_cdp` 不适合，因为旧内核不支持新版 Playwright 调用的 `Browser.setDownloadBehavior`。

原生 CDP WebSocket 可行。

已通过原生 CDP `Page.navigate` 在 `X5Game.exe` 客户端内部页面跳转完整直登 URL，并成功触发：

```text
importServer 200
gameNotice/showtimes 200
gameNotice 200
serverMobile 200
verjs 200
GameMain.max_*.js 200
js/login_*.js 200
js/main_*.js 200
X5_Main* 资源 200
canvas 可见
window.com.Game 存在
window.app.Params 存在
WebSocket 101
```

结论：

```text
客户端直登技术路径已打通。
下一步不要重做登录链路。
只补客户端批次管理、端口配置、追加准备、绑定持久化、修复本批窗口。
```

---

## 三、完整直登 URL 判断规则

判断完整直登 URL，不能只看域名和 path，要看参数。

必须包含：

```text
gid
pid
token
time
sign
isPcLauncher=true
```

允许为空：

```text
appVer
platCode
IMEI
```

兼容入口包括：

```text
dldl.50pk.com/login.php
app.xxh5.z7xz.com/login.php
7tu7tu.com/dldl
```

执行 `Page.navigate` 时必须使用收藏夹读取到的原始 URL。

禁止：

```text
不要强制替换域名
不要强制把 7tu7tu 转成 dldl.50pk
不要强制把 dldl.50pk 转成 7tu7tu
```

日志只能输出 host/path 和参数 key，不允许输出完整 query。

---

## 四、当前已有功能

源码模式已验证可用，未提交，未打包。

已完成：

```text
1. 单账号客户端直登：可用
2. 当前层串行客户端直登：可用
3. 全部串行客户端直登：可用
4. 准备客户端：可用
5. 排列本批客户端：可用
6. 执行客户端登录：可用
7. 自动进入游戏 true/false：可用
8. 原后台通行证/OCR流程保持不变
```

GUI 三步流程：

```text
准备客户端
→ 排列本批客户端
→ 执行客户端登录
```

准备客户端：

```text
启动 X5Game.exe
分配 CDP 端口
绑定 account_id/account_name/pid/hwnd/cdp_port/login_url/status
不登录
```

排列本批客户端：

```text
只排列 client_direct_bindings 里的 hwnd
不扫描全局窗口
不排列其他 Chrome、Edge、旧 X5Game 窗口
```

执行客户端登录：

```text
使用准备阶段保存的 pid/hwnd/cdp_port/login_url
连接 CDP
Page.navigate 到原始 URL
根据 auto_enter_game 配置执行
```

---

## 五、当前暴露的问题

真实使用场景：

```text
桌面1：已经开好 9 个 X5Game.exe 客户端
桌面2：还要再开 31 个 X5Game.exe 客户端
```

问题：

```text
1. 虚拟桌面不隔离进程和端口
2. 桌面1的9个可能占用 9222~9230
3. 桌面2再准备31个时，不能再从9222开始
4. 程序不能误操作桌面1那9个旧窗口
5. 不能默认当前机器上的 X5Game.exe 都归本程序管理
6. 只能管理当前批次绑定里的 X5Game.exe
7. live 脚本的 --limit 31 只是取前31个，不等于剩下31个，容易误操作前面的账号
```

核心原则：

```text
永远不要默认“当前机器上的 X5Game.exe 都归我管”。
只能管理“当前批次绑定记录里的 X5Game.exe”。
```

---

## 六、新增 Client Batch 客户端批次概念

新增客户端批次 `Client Batch`。

每个批次保存：

```text
batch_id
batch_name
scope
account_id
account_name
pid
hwnd
cdp_port
login_url
status
created_at
updated_at
virtual_desktop_note
```

说明：

```text
batch_id：唯一批次 ID
batch_name：用户可见批次名称，例如 桌面2-31号
scope：当前层 / 全部串行 / 自定义
virtual_desktop_note：只是备注，不作为技术判断依据
pid/hwnd/cdp_port：用于恢复和修复
login_url：原始收藏夹完整直登 URL
status：当前绑定状态
```

---

## 七、新增绑定持久化

新增文件：

```text
debug_client_direct/client_direct_sessions.json
```

注意：代码里不要写死绝对路径，应从项目运行目录或配置派生。

建议结构：

```json
{
  "schema_version": 1,
  "active_batch_id": "batch_20260705_001",
  "settings": {
    "default_base_port": 9222,
    "last_base_port": 9231,
    "restore_on_startup": true
  },
  "batches": [
    {
      "batch_id": "batch_20260705_001",
      "batch_name": "桌面2-31号",
      "scope": "全部串行",
      "base_port": 9231,
      "auto_enter_game": true,
      "virtual_desktop_note": "桌面2",
      "created_at": "2026-07-05 00:00:00",
      "updated_at": "2026-07-05 00:00:00",
      "bindings": [
        {
          "account_id": "10",
          "account_name": "第10号",
          "pid": 12345,
          "hwnd": 67890,
          "cdp_port": 9231,
          "login_url": "完整原始URL，文件内允许保存，但日志不能完整输出",
          "status": "prepared",
          "created_at": "2026-07-05 00:00:00",
          "updated_at": "2026-07-05 00:00:00"
        }
      ]
    }
  ]
}
```

规则：

```text
1. 文件里可以保存完整 login_url，因为恢复登录需要用
2. 日志里不能输出完整 login_url
3. 程序重开后只从 client_direct_sessions.json 恢复已知绑定
4. 不允许扫描全局 X5Game.exe 后自动接管
```

---

## 八、起始端口配置

客户端直登区域增加：

```text
起始端口：9231
本批数量：31
预计端口范围：9231 ~ 9261
```

默认仍是：

```text
9222
```

用户可以手动改成：

```text
9231
```

准备前必须检查：

```text
base_port ~ base_port + count - 1
```

如果端口被占用：

```text
1. 阻止准备
2. 提示具体占用端口
3. 建议用户更换起始端口
4. 当前阶段不要自动跳端口
```

---

## 九、追加准备

新增能力：

```text
追加准备到当前批次
```

作用：

```text
1. 不清空当前批次绑定
2. 不关闭旧 X5Game.exe
3. 不影响其他批次
4. 只把新准备的客户端追加到当前批次
```

追加准备时：

```text
1. 保留当前批次已有 bindings
2. 新账号追加到 bindings 后面
3. 起始端口可以手动指定
4. 如果端口和当前批次已有端口冲突，阻止
5. 如果账号已经在当前批次或其他批次里存在，提示或跳过
```

---

## 十、修复窗口新定位：修复本批窗口

用户习惯：

```text
可能已经打开了一批 X5Game.exe
关闭上号器程序
之后重新打开上号器
再使用“修复窗口”继续操作
```

旧逻辑如果是全局扫描所有 X5Game.exe 并自动接管，很危险。

新逻辑：

```text
修复本批窗口
= 只修复 client_direct_sessions.json 里当前批次已有绑定
```

修复依据优先级：

```text
pid -> cdp_port -> hwnd
```

流程：

```text
1. 读取当前批次 bindings
2. 检查 pid 是否存在
3. 检查 pid 对应进程是否仍是 X5Game.exe
4. 检查 cdp_port 是否可访问
5. 通过 pid 枚举 top-level window，重新查找 hwnd
6. 如果找到新的 hwnd，更新绑定
7. 如果 pid 不存在，状态标记 pid_missing
8. 如果 cdp_port 不通，状态标记 cdp_unavailable
9. 如果 hwnd 找不到，状态标记 hwnd_invalid
10. 保存修复结果
```

重点：

```text
可以根据已知 pid 找 hwnd。
不可以根据标题全局接管未知 X5Game.exe。
```

---

## 十一、程序重开后的恢复

程序启动时：

```text
1. 读取 debug_client_direct/client_direct_sessions.json
2. 显示已有批次列表
3. 默认选中 active_batch_id
4. 不自动接管全局 X5Game.exe
5. 对当前批次做轻量状态刷新
```

轻量刷新检查：

```text
pid 是否存在
cdp_port 是否可访问
hwnd 是否仍有效
```

用户点击“修复本批窗口”后，再执行完整修复：

```text
pid 找进程
cdp_port 验证
pid 找 hwnd
更新绑定文件
```

修复成功后必须可以继续：

```text
排列本批客户端
执行客户端登录
自动进入游戏 true / false
```

---

## 十二、当前批次操作规则

所有客户端直登按钮必须围绕当前批次。

### 1. 排列本批客户端

只排列：

```text
active_batch_id 对应 bindings 里的 hwnd
```

禁止：

```text
扫描全局 X5Game.exe 后全部排列
```

### 2. 执行客户端登录

只登录：

```text
active_batch_id 对应 bindings
```

登录时使用绑定里保存的：

```text
pid
hwnd
cdp_port
login_url
```

### 3. 清空本批绑定

新增按钮：

```text
清空本批绑定
```

作用：

```text
只删除当前批次绑定记录
不关闭 X5Game.exe
不杀进程
不影响其他批次
```

需要二次确认。

### 4. 关闭本批客户端

新增按钮：

```text
关闭本批客户端
```

作用：

```text
只关闭当前批次 bindings 里的 pid
不关闭其他 X5Game.exe
不关闭其他批次
```

需要二次确认。

---

## 十三、建议新增代码文件

建议新增：

```text
douluo_launcher/client_batch_store.py
```

负责：

```text
读取 client_direct_sessions.json
保存 client_direct_sessions.json
创建批次
切换当前批次
追加 binding
更新 binding 状态
清空当前批次
关闭当前批次记录
恢复当前批次
```

已有文件职责：

```text
douluo_launcher/client_direct_login.py
```

继续负责：

```text
启动 X5Game.exe
分配 CDP
Page.navigate
检测 importServer / serverMobile / canvas
登录状态判断
```

```text
douluo_launcher/client_cdp.py
```

继续负责：

```text
原生 CDP WebSocket 通信
/json/version
/json
Page.navigate
Runtime.evaluate
Network 监听
```

```text
douluo_launcher/window_manager.py
```

负责：

```text
根据 pid 找 hwnd
排列指定 hwnd 列表
关闭指定 pid / hwnd
验证 hwnd 是否有效
```

```text
douluo_launcher/gui.py
```

负责：

```text
批次选择
端口配置
准备前确认
按钮状态
列表展示
调用 BatchStore + ClientDirectLogin
```

---

## 十四、live 脚本增强

当前 `--limit 31` 容易误操作前面的账号。

建议增强：

```text
--offset
--account-range
--base-port
--only-include-in-all
--exclude-existing
--batch-name
--dry-run
```

推荐示例：

```bash
py -3.14-32 tools/live_client_direct_login_batch.py ^
  --account-range 10-40 ^
  --base-port 9231 ^
  --only-include-in-all ^
  --exclude-existing ^
  --batch-name 桌面2-31号 ^
  --auto-enter-game
```

`--dry-run` 输出：

```text
准备范围：账号 10-40
本批账号数量：31
起始端口：9231
端口范围：9231~9261
自动进入游戏：true
已绑定账号跳过：true
```

---

## 十五、必须补的测试

新增或修改测试：

```text
tests/test_client_batch_store.py
tests/test_client_direct_login.py
tests/test_gui_group_settings.py
tests/test_window_manager.py
```

重点测试：

```text
1. 创建批次、追加绑定、保存、重新加载
2. 批次 A 和批次 B 隔离
3. 当前批次排列只使用当前批次 hwnd
4. 当前批次登录只使用当前批次 cdp_port/login_url
5. 当前批次关闭只关闭当前批次 pid
6. 起始端口和端口范围预检
7. 程序重开后从 sessions 文件恢复绑定
8. pid 不存在时标记 pid_missing
9. cdp_port 不通时标记 cdp_unavailable
10. hwnd 失效时标记 hwnd_invalid
11. URL 完整直登判断
12. 日志脱敏
```

运行测试：

```bash
py -3.14-32 -m compileall -q main.py douluo_launcher tests tools
py -3.14-32 -m unittest discover -s tests -v
```

---

## 十六、禁止事项

本次开发禁止：

```text
不要做并发
不要重构整个项目
不要改掉原 OCR / 通行证兜底流程
不要把客户端直登改回 Chrome / Edge / Playwright 普通浏览器登录
不要使用 Playwright connect_over_cdp
不要自动接管所有 X5Game.exe
不要全局扫描后自动排列所有 X5Game.exe
不要全局扫描后自动关闭所有 X5Game.exe
不要只靠窗口标题修复绑定
不要强制替换 login.php URL 域名
不要在日志输出完整 token/sign/cookie/IMEI/session/openid/login.php URL
```

---

## 十七、推荐开发顺序

### 第一阶段：批次数据层

```text
client_batch_store.py
client_direct_sessions.json
创建批次
追加绑定
切换当前批次
保存 / 加载
```

### 第二阶段：端口配置和预检

```text
起始端口配置
端口范围展示
端口占用检测
准备前确认
```

### 第三阶段：GUI 接入当前批次

```text
准备客户端
追加准备
排列本批客户端
执行客户端登录
清空本批绑定
关闭本批客户端
```

### 第四阶段：修复本批窗口

```text
程序重开后加载 sessions
根据 pid / cdp_port / hwnd 修复
不自动接管未知 X5Game.exe
```

### 第五阶段：live 脚本增强

```text
--offset
--account-range
--base-port
--only-include-in-all
--exclude-existing
--batch-name
--dry-run
```

注意：本次优先完成第一阶段到第四阶段，第五阶段可放后面。

---

## 十八、最终验收场景

### 场景 A：已有 9 个客户端

```text
桌面1已有9个 X5Game.exe
端口9222~9230已占用
```

准备桌面2：

```text
base_port=9231
account_range=10-40
count=31
```

预期结果：

```text
准备31个成功
端口9231~9261
不影响桌面1的9个
排列只排列31个
登录只登录31个
关闭本批只关闭31个
```

### 场景 B：关闭上号器后恢复

```text
关闭上号器程序
X5Game.exe 不关闭
重新打开上号器
```

预期结果：

```text
从 client_direct_sessions.json 恢复批次
不自动接管其他 X5Game.exe
修复本批窗口成功
可以继续排列本批客户端
可以继续执行客户端登录
```

### 场景 C：旧 pid 已关闭

```text
sessions 里有绑定
但某个 X5Game.exe 被手动关了
```

预期结果：

```text
状态标记 客户端已关闭
不会误接管另一个 X5Game.exe
不会用标题乱匹配
```

---

## 十九、最终原则

```text
X5Game.exe 可以全局扫描展示，但不能全局自动接管。
真正能操作的，只有当前批次绑定记录里的 pid / hwnd / cdp_port。
```
