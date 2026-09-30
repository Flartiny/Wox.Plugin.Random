# Wox.Plugin.Random

[Wox](https://www.woxlauncher.com/) 随机数生成插件（Python 全功能插件）。支持多条可配置的生成规则（Profile）、Profile 内防重复、以及系统预设规则（如部署服务可用的随机端口）。

## 功能

- **多种生成类型**：整数、小数、字符串、UUID v4、端口
- **Profile（规则档案）**：每条规则可独立设置类型、范围（Min/Max）、小数位、长度、字符集，在 Wox 设置界面中以表格方式增删改
- **防重复**：每个 Profile 独立开关（设置表格中勾选，或在结果上用"切换防重复"动作）；开启后同一 Profile 内绝不生成重复值，历史持久化在插件目录 `data/used_values.json`，重启 Wox 依然有效；值域耗尽时自动清空历史并重新开始
- **系统预设模板**（`rand preset` 命令，用于快速创建 Profile）：
  - 可用端口（部署服务）：1024–65535 随机端口，并实际探测本机端口可绑定后才返回
  - UUID v4
  - 6 位数字验证码
  - 16 位强密码（字母+数字）

> 预设只是模板：同一个预设可以创建多条 Profile（比如两台服务器各建一条"可用端口"），每条的防重复历史完全独立。
- **生成即复制**：回车生成后自动复制到剪贴板（可在设置中关闭），并通过通知展示

## 使用

| 输入 | 行为 |
|---|---|
| `rand` | 列出所有 Profile，回车生成并复制 |
| `rand 订单` | 按名称过滤 Profile |
| `rand preset` | 从预设模板创建新 Profile（同名自动编号） |
| `rand history` | 选择 Profile 查看历史生成值（可复制） |
| `rand history 订单` | 直接查看指定 Profile 的历史 |
| `rand reset` / `rand reset 订单` | 清空 Profile 的防重复历史 |

Profile 结果上还有两个次级动作：**切换防重复**（无需打开设置页）和**重置历史**。

触发关键字：`rand`、`random`。

## 设置

在 Wox 设置 → 插件 → Random 中：

- **生成规则（Profile）表格**：名称 / 类型 / 最小值 / 最大值 / 小数位 / 长度 / 字符集 / 自定义字符 / 防重复
- **生成后自动复制**：默认开启

## 开发

```bash
uv sync --all-groups   # 安装依赖（含 pytest）
uv run pytest          # 运行测试
python package.py      # 生成 wox.plugin.Random.wox
```

发布时将 `wox.plugin.Random.wox` 作为 GitHub Release asset 上传；Wox Store 条目应使用该文件的 `releases/latest/download/wox.plugin.Random.wox` 地址。

代码结构：

- `plugin.json` — 插件元数据、命令、设置定义（表格 Profile、开关）
- `main.py` — 插件入口：query 分发（生成 / history / reset）、结果与 Action
- `generator.py` — 纯生成引擎（无 Wox 依赖，含端口可用性探测）
- `storage.py` — 防重复历史的持久化存储
- `presets.py` — 系统预设规则
- `lang/` — 中英文翻译

### 安装到 Wox（本地开发）

Wox 的插件管理器（WPM）加载本地 dev 插件时**只认插件目录下的 `dist/` 子目录**（这是为 Node 插件构建产物设计的），Python 插件不需要编译，但同样需要 `dist/`。本仓库用 `build.py` 把源码同步过去：

```bash
python build.py        # 每次改完源码执行一次；Wox 会监听 dist/ 变更并自动重载
```

首次安装：在 Wox 里执行 `wpm dev.add <插件目录路径>`（或设置里的 WPM 界面添加），之后运行 `wpm dev.reload` 或重启 Wox 即可加载。防重复历史保存在 `dist/data/`，重新 build 不会丢失。

> 实现细节：Wox 的 Python 宿主重载插件时只清理入口模块（`main`）的缓存，`main.py` 会在导入时主动清理 `generator/presets/storage` 的模块缓存，保证每次重载都使用 dist 里的最新代码，无需重启 Wox。

> 注意：`wox-plugin` SDK 由 Wox 的 Python 宿主环境提供，插件本体无需额外安装第三方依赖。

## 许可证

[MIT License](LICENSE)
