#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; SmitelessSetup.exe - self-contained installer (compiled from this script with the whole
; app embedded as payload.zip). Needs nothing pre-installed: Python, Pillow and AutoHotkey
; are all inside the payload.
;
;   SmitelessSetup.exe              show the install window (normal use)
;   SmitelessSetup.exe /upgrade     silent reinstall over the existing copy (used by the updater)
;   SmitelessSetup.exe /uninstall   remove Smiteless
;
; Installs to %LOCALAPPDATA%\Smiteless and makes Desktop + Start Menu + Startup shortcuts.
; ============================================================

APPNAME := "Smiteless"
LOCAL_ROOT := KnownFolder(0x001C) ; CSIDL_LOCAL_APPDATA
PROFILE_ROOT := KnownFolder(0x0028) ; CSIDL_PROFILE
if (!LOCAL_ROOT || !PROFILE_ROOT) {
    MsgBox("Smiteless could not resolve the current Windows user folders safely.",
        APPNAME, "Iconx")
    ExitApp(1)
}
TARGET := LOCAL_ROOT "\" APPNAME
REGKEY := "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\" APPNAME
CLAUDE_ROOT := PROFILE_ROOT "\.claude"
CACHE_ROOT := CLAUDE_ROOT "\cache"
TEMP_ROOT := FullPath(A_Temp)
SETTINGS := CLAUDE_ROOT "\smiteless_settings.json"

; Complete uninstall owns only these exact children. Never add .claude, cache, the user profile,
; LocalAppData or Temp themselves to these lists.
CLAUDE_FILES := [
    "smiteless_accounts.json", "smiteless_ban.log", "smiteless_board_pos.json",
    "smiteless_dead.log", "smiteless_draft.log", "smiteless_gamemon.json",
    "smiteless_last_riot_id.txt", "smiteless_load.log", "smiteless_logins.bin",
    "smiteless_mute.log", "smiteless_noautoopen", "smiteless_nohomeonstart",
    "smiteless_overlay.log", "smiteless_pick.log", "smiteless_queue.log",
    "smiteless_settings.json", "smiteless_widget_pos.json"
]
CLAUDE_DIRS := ["smiteless_accounts"]
CACHE_FILES := [
    "lol_fit.json", "lol_lp_history.json", "lolrole.json", "scout_snapshot.json",
    "scout_snapshot.json.lock", "smitecard.png", "smiteless_coach_endpoint.json",
    "smiteless_coach_tools.jsonl", "smiteless_coach_tools.jsonl.old",
    "smiteless_jgcal.jsonl", "smiteless_proactive_intents.jsonl",
    "smiteless_proactive_intents.jsonl.old", "smiteless_proactive_widget.json",
    "smiteless_widget.log"
]
CACHE_DIRS := ["counterstats", "ddragon", "icons", "matchups", "opgg", "riot", "ugg"]
TEMP_DIRS := ["smiteless_audio"]

KnownFolder(csidl) {
    buf := Buffer(32768 * 2, 0)
    result := DllCall("Shell32\SHGetFolderPathW", "Ptr", 0, "Int", csidl,
        "Ptr", 0, "UInt", 0, "Ptr", buf.Ptr, "Int")
    return result = 0 ? RTrim(StrGet(buf, "UTF-16"), "\") : ""
}

FullPath(path) {
    needed := DllCall("Kernel32\GetFullPathNameW", "Str", path, "UInt", 0,
        "Ptr", 0, "Ptr", 0, "UInt")
    if (!needed)
        return ""
    buf := Buffer((needed + 1) * 2, 0)
    if (!DllCall("Kernel32\GetFullPathNameW", "Str", path, "UInt", needed + 1,
            "Ptr", buf.Ptr, "Ptr", 0, "UInt"))
        return ""
    return RTrim(StrGet(buf, "UTF-16"), "\")
}

SamePath(left, right) {
    left := FullPath(left), right := FullPath(right)
    return left != "" && right != "" && StrLower(left) = StrLower(right)
}

AllowedChild(root, relative, allowlist) {
    if (!relative || InStr(relative, "..") || InStr(relative, ":")
            || SubStr(relative, 1, 1) = "\")
        return ""
    found := false
    for allowed in allowlist {
        if (relative = allowed) {
            found := true
            break
        }
    }
    if (!found)
        return ""
    root := FullPath(root)
    target := FullPath(root "\" relative)
    return root != "" && target != ""
        && SubStr(StrLower(target), 1, StrLen(root) + 1) = StrLower(root "\")
        ? target : ""
}

DeleteAllowedFile(root, relative, allowlist) {
    target := AllowedChild(root, relative, allowlist)
    if (!target)
        return false
    try FileDelete(target)
    return true
}

DeleteAllowedDir(root, relative, allowlist) {
    target := AllowedChild(root, relative, allowlist)
    if (!target || SamePath(target, root))
        return false
    try DirDelete(target, true)
    return true
}

InstallTargetIsSafe() {
    global TARGET, LOCAL_ROOT, APPNAME
    return SamePath(TARGET, LOCAL_ROOT "\" APPNAME) && !SamePath(TARGET, LOCAL_ROOT)
}

UiLang() {
    global SETTINGS
    try {
        if RegExMatch(FileRead(SETTINGS, "UTF-8"), '"ui_lang"\s*:\s*"pt_BR"')
            return "pt_BR"
    }
    return "en"
}
Tr(en, pt) {
    return UiLang() = "en" ? en : pt
}

mode := "gui"
silentUi := false
for a in A_Args {
    if (a = "/S" || a = "/silent") {
        silentUi := true
        if (mode = "gui")
            mode := "silent"
    } else if (a = "/upgrade")
        mode := "silent"
    else if (a = "/uninstall")
        mode := "uninstall"
}

if (mode = "uninstall") {
    Uninstall(silentUi)
    ExitApp()
} else if (mode = "silent") {
    if (!DoInstall(true, true))       ; upgrade path: relaunch the tray after replacing files
        ExitApp(1)
    ExitApp()
}

; ---------- normal GUI install ----------
g := Gui("+AlwaysOnTop -MaximizeBox -MinimizeBox", APPNAME " " Tr("Setup", "Instalação"))
g.BackColor := "0x11131A"
g.SetFont("s10 cWhite", "Segoe UI")
g.MarginX := 22, g.MarginY := 18
g.SetFont("s15 bold c0xC8AA6E")
g.Add("Text", , "Smiteless")
g.SetFont("s10 cWhite")
g.Add("Text", "y+8 w430", Tr("A League of Legends champ-select and in-game overlay.",
    "Um overlay para a seleção de campeões e durante as partidas de League of Legends."))
g.Add("Text", "y+12 w430 c0x9B988E",
    Tr("This installs the app runtime into your account folder, adds a desktop shortcut, and starts it with Windows. Voice coaching downloads its local model only after you opt in. Run League in Borderless mode.",
       "Isto instala o runtime do aplicativo na pasta da sua conta, adiciona um atalho à área de trabalho e inicia com o Windows. O coach de voz baixa o modelo local somente após sua autorização. Execute o League no modo Sem Bordas."))
g.SetFont("s9 c0x9B988E")
g.Add("Text", "y+12 w430", Tr("Installs to:  ", "Instala em:  ") TARGET)
btn := g.Add("Button", "y+18 w120 h34 Default", Tr("Install", "Instalar"))
btn.SetFont("s10 bold")
cancel := g.Add("Button", "x+10 yp w90 h34", Tr("Cancel", "Cancelar"))
status := g.Add("Text", "xm y+14 w430 c0x9B988E", "")
btn.OnEvent("Click", GuiInstall)
cancel.OnEvent("Click", (*) => ExitApp())
g.OnEvent("Close", (*) => ExitApp())
g.Show()

GuiInstall(*) {
    global g, btn, cancel, status, TARGET, APPNAME
    btn.Enabled := false, cancel.Enabled := false
    status.Value := Tr("Installing...", "Instalando...")
    if (!DoInstall(true, false)) {
        status.Value := Tr("Installation failed; the application was not started.",
            "A instalação falhou; o aplicativo não foi iniciado.")
        btn.Text := Tr("Retry", "Tentar novamente"), btn.Enabled := true
        cancel.Enabled := true
        MsgBox(Tr("Smiteless could not install its application files. The application was not started.",
            "O Smiteless não conseguiu instalar os arquivos do aplicativo. O aplicativo não foi iniciado."),
            APPNAME, "Iconx")
        return
    }
    status.Value := Tr("Done!  Smiteless is starting and will run with Windows from now on.",
        "Pronto! O Smiteless está iniciando e será executado com o Windows de agora em diante.")
    btn.Text := Tr("Finish", "Concluir"), btn.Enabled := true
    btn.OnEvent("Click", (*) => ExitApp())
    MsgBox(Tr("Smiteless is installed and running.`n`nLook for the gold 'S' icon near your clock (click the ^ arrow if you don't see it). Press Ctrl+Alt+X any time to open it.",
        "O Smiteless está instalado e em execução.`n`nProcure o ícone dourado 'S' perto do relógio (clique na seta ^ se não o encontrar). Pressione Ctrl+Alt+X para abri-lo."),
        APPNAME, "Iconi")
    ExitApp()
}

DoInstall(launch, upgraded := false) {
    global TARGET, REGKEY, APPNAME
    if (!InstallTargetIsSafe())
        return false
    ; stop any running copy so files aren't locked
    RunWait(A_ComSpec ' /c taskkill /F /IM Smiteless.exe /IM SmitelessApp.exe >nul 2>nul', , "Hide")
    Sleep(400)
    DirCreate(TARGET)
    ; Remove the exact legacy helper directory left by pre-Whisper versions. It is never used by
    ; the local runtime and must not survive an in-place upgrade.
    try DirDelete(TARGET "\app\stt", true)
    ; extract the embedded payload (Expand-Archive reads the Compress-Archive zip reliably)
    tmp := A_Temp "\smiteless_payload.zip"
    FileInstall("payload.zip", tmp, 1)
    psfile := A_Temp "\smiteless_extract.ps1"
    try FileDelete(psfile)
    FileAppend("Expand-Archive -LiteralPath '" tmp "' -DestinationPath '" TARGET "' -Force", psfile)
    extractCode := RunWait('powershell -NoProfile -ExecutionPolicy Bypass -File "' psfile '"', , "Hide")
    try FileDelete(psfile)
    try FileDelete(tmp)
    if (extractCode != 0)
        return false
    ; keep a copy of this installer for clean uninstall
    try FileCopy(A_ScriptFullPath, TARGET "\Uninstall.exe", 1)
    ; shortcuts (Desktop, Startup, Start Menu)
    ico := TARGET "\assets\smiteless.ico"
    exe := TARGET "\Smiteless.exe"
    FileCreateShortcut(exe, A_Desktop "\Smiteless.lnk", TARGET, , APPNAME, ico)
    FileCreateShortcut(exe, A_Startup "\Smiteless.lnk", TARGET, , APPNAME, ico)
    DirCreate(A_Programs "\" APPNAME)
    FileCreateShortcut(exe, A_Programs "\" APPNAME "\Smiteless.lnk", TARGET, , APPNAME, ico)
    FileCreateShortcut(TARGET "\Uninstall.exe", A_Programs "\" APPNAME "\Uninstall Smiteless.lnk",
        TARGET, "/uninstall", "Uninstall " APPNAME, ico)
    ; Add/Remove Programs entry
    ver := "1.0.0"
    try ver := Trim(FileRead(TARGET "\VERSION"), " `t`r`n")
    if (upgraded) {
        try FileDelete(TARGET "\.updated_version")
        try FileAppend(ver, TARGET "\.updated_version")
    }
    RegWrite(APPNAME, "REG_SZ", REGKEY, "DisplayName")
    RegWrite('"' TARGET '\Uninstall.exe" /uninstall', "REG_SZ", REGKEY, "UninstallString")
    RegWrite(ico, "REG_SZ", REGKEY, "DisplayIcon")
    RegWrite(ver, "REG_SZ", REGKEY, "DisplayVersion")
    RegWrite("bobbyroylee", "REG_SZ", REGKEY, "Publisher")
    RegWrite(TARGET, "REG_SZ", REGKEY, "InstallLocation")
    RegWrite(1, "REG_DWORD", REGKEY, "NoModify")
    RegWrite(1, "REG_DWORD", REGKEY, "NoRepair")
    if (launch) {
        ; If the expected exe is missing (AV/quarantine or extraction issue), try common fallback paths
        if (!FileExist(exe)) {
            alt := TARGET "\app\SmitelessApp\SmitelessApp.exe"
            if (FileExist(alt)) {
                exe := alt
            } else {
                MsgBox(Tr("Installation finished but the launcher exe wasn't found.`n`nThis can happen if antivirus quarantined files or extraction failed.`nPlease check ",
                    "A instalação terminou, mas o executável do inicializador não foi encontrado.`n`nIsso pode ocorrer se o antivírus colocou arquivos em quarentena ou se a extração falhou.`nVerifique ") TARGET, APPNAME, "Iconi")
                return false
            }
        }
        Run('"' exe '"', TARGET)
    }
    return true
}

Uninstall(silent := false) {
    global TARGET, REGKEY, APPNAME, CLAUDE_ROOT, CACHE_ROOT, TEMP_ROOT
    global CLAUDE_FILES, CLAUDE_DIRS, CACHE_FILES, CACHE_DIRS, TEMP_DIRS
    if (!InstallTargetIsSafe()) {
        if (!silent)
            MsgBox(Tr("Smiteless refused an unsafe uninstall path.",
                "O Smiteless recusou um caminho de desinstalaÃ§Ã£o inseguro."), APPNAME, "Iconx")
        return false
    }
    ; Every frozen coach, capture and Whisper worker runs as SmitelessApp.exe. Kill the tray
    ; and those exact application processes before removing model locks, endpoints or runtime.
    RunWait(A_ComSpec ' /c taskkill /F /IM Smiteless.exe /IM SmitelessApp.exe >nul 2>nul', , "Hide")
    Sleep(400)
    try FileDelete(A_Desktop "\Smiteless.lnk")
    try FileDelete(A_Startup "\Smiteless.lnk")
    try DirDelete(A_Programs "\" APPNAME, true)
    try RegDeleteKey(REGKEY)

    ; Settings, coach IPC/session state and Smiteless caches under .claude are exact children.
    ; The .claude and cache parents are deliberately preserved, including unrelated content.
    for relative in CLAUDE_FILES
        DeleteAllowedFile(CLAUDE_ROOT, relative, CLAUDE_FILES)
    for relative in CLAUDE_DIRS
        DeleteAllowedDir(CLAUDE_ROOT, relative, CLAUDE_DIRS)
    for relative in CACHE_FILES
        DeleteAllowedFile(CACHE_ROOT, relative, CACHE_FILES)
    for relative in CACHE_DIRS
        DeleteAllowedDir(CACHE_ROOT, relative, CACHE_DIRS)
    for relative in TEMP_DIRS
        DeleteAllowedDir(TEMP_ROOT, relative, TEMP_DIRS)
    CleanupLegacyAudioCache()

    ; remove the install folder. Uninstall.exe runs from INSIDE it, so a detached batch
    ; retries the already-validated exact %LOCALAPPDATA%\Smiteless path until this exe exits.
    ; This removes runtime, compatible/versioned models, partial downloads and model locks.
    bat := A_Temp "\smiteless_uninstall.bat"
    try FileDelete(bat)
    FileAppend('@echo off`r`n'
        . ':retry`r`n'
        . 'rmdir /s /q "' TARGET '" 2>nul`r`n'
        . 'if exist "' TARGET '" ( ping 127.0.0.1 -n 2 >nul & goto retry )`r`n'
        . 'del "%~f0"`r`n', bat)
    ; Run cmd from Temp, not from TARGET inherited by the installed Uninstall.exe. Windows cannot
    ; remove a process's current directory even after the uninstaller itself has exited.
    Run(A_ComSpec ' /c "' bat '"', TEMP_ROOT, "Hide")
    if (!silent)
        MsgBox(APPNAME Tr(" has been removed.", " foi removido."), APPNAME, "Iconi")
    return true
}

CleanupLegacyAudioCache() {
    global TEMP_ROOT
    ; Pre-Phase-3 builds placed only these two anchored Smiteless namespaces directly in Temp.
    ; Resolve and compare every enumerated file's parent before deleting it; never delete Temp.
    patterns := ["smiteless_salli_v1_*.mp3", "smiteless_drake_v7_*.wav"]
    for pattern in patterns {
        Loop Files, TEMP_ROOT "\" pattern, "F" {
            full := FullPath(A_LoopFileFullPath)
            if (!SamePath(FullPath(A_LoopFileDir), TEMP_ROOT))
                continue
            name := A_LoopFileName
            safe := RegExMatch(name, "^smiteless_salli_v1_[A-Za-z0-9_-]+\.mp3$")
                || RegExMatch(name, "^smiteless_drake_v7_[A-Za-z0-9_-]+\.wav$")
            if (safe && full)
                try FileDelete(full)
        }
    }
}
