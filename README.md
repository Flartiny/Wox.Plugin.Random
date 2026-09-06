# Wox.Plugin.Random

[Wox](https://www.woxlauncher.com/) 随机数生成插件（Python 全功能插件）。支持多条可配置的生成规则（Profile）、Profile 内防重复、以及系统预设规则（如部署服务可用的随机端口）。

## 功能

- **多种生成类型**：整数、小数、字符串、UUID v4、端口
- **Profile（规则档案）**：每条规则可独立设置类型、范围（Min/Max）、小数位、长度、字符集、防重复开关，在 Wox 设置界面中以表格方式增删改
- **防重复**：开启后同一 Profile 内绝不生成重复值；历史持久化在插件目录 `data/used_values.json`，重启 Wox 依然有效；值域耗尽时自动清空历史并重新开始
- **系统预设**：
  - 可用端口（部署服务）：1024–65535 随机端口，并实际探测本机端口可绑定后才返回
  - UUID v4
  - 6 位数字验证码
  - 16 位强密码（字母+数字）
- **生成即复制**：回车生成后自动复制到剪贴板（可在设置中关闭），并通过通知展示

## 使用

| 输入 | 行为 |
|---|---|
| `rand` | 列出所有 Profile（含系统预设），回车生成并复制 |
| `rand 订单` | 按名称过滤 Profile |
| `rand history` | 选择 Profile 查看历史生成值（可复制） |
| `rand history 订单` | 直接查看指定 Profile 的历史 |
| `rand reset` / `rand reset 订单` | 清空 Profile 的防重复历史 |

触发关键字：`rand`、`random`。

## 设置

在 Wox 设置 → 插件 → Random 中：

- **生成规则（Profile）表格**：名称 / 类型 / 最小值 / 最大值 / 小数位 / 长度 / 字符集 / 自定义字符 / 防重复
- **显示系统预设规则**：关闭后只显示自定义 Profile
- **生成后自动复制**：默认开启

## 开发

```bash
uv sync --all-groups   # 安装依赖（含 pytest）
uv run pytest          # 运行测试
```

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

> 注意：`wox-plugin` SDK 由 Wox 的 Python 宿主环境提供，插件本体无需额外安装第三方依赖。
