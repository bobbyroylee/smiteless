#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless - persistent tray app.
;
; Sits in the system tray with a right-click menu:
;   Open overlay | Item widget | Settings | Auto-open at champ select (toggle) | Reload | Exit
; It auto-opens the overlay at champ select and the floating item widget in-game (while
; auto-open is on and the client is up). Hotkeys: Ctrl+Alt+X = overlay, Ctrl+Alt+B = item
; widget (both global). The windows are Python (smiteoverlay.py / smitewidget.py /
; smitesettings.py); this script is just the persistent shell.
; ============================================================

; --- CONFIG -------------------------------------------------
PY := "python"                  ; Python 3 + Pillow. Set to your python.exe if not on PATH.
PYW := RegExReplace(PY, "i)python(\.exe)?$", "pythonw$1")   ; windowless python -> no console flash
if (InStr(PYW, "\") && !FileExist(PYW))                     ; full path that doesn't exist -> fall back
    PYW := PY
SCRIPTS := A_ScriptDir          ; the .py files live in core/ ui/ tools/ under this dir
TRAY_PID := ProcessExist()
; ------------------------------------------------------------

; Heartbeat anchor: hold the "Global\SmitelessTray" mutex for this tray's whole life. Every
; surface (overlay/widget/loading/death/profile/settings) polls it and self-closes when it
; disappears, so force-closing Smiteless leaves no orphan windows. (The Python tray already
; holds this mutex; this makes the AHK tray hold it too.)
DllCall("CreateMutexW", "Ptr", 0, "Int", 0, "WStr", "Global\SmitelessTray")

NOAUTO := EnvGet("USERPROFILE") "\.claude\smiteless_noautoopen"   ; present = auto-open OFF
SETTINGS := EnvGet("USERPROFILE") "\.claude\smiteless_settings.json"

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

if FileExist(SCRIPTS "\assets\smiteless.ico")
    TraySetIcon(SCRIPTS "\assets\smiteless.ico")
A_IconTip := "Smiteless"

tray := A_TrayMenu
tray.Delete()                                   ; replace the default AHK menu
MENU_OVERLAY := Tr("Open overlay", "Abrir overlay")
MENU_PROFILE := Tr("Profile / home", "Perfil / início")
MENU_WIDGET := Tr("Item widget", "Widget de itens")
MENU_COACH := Tr("Coach", "Coach")
MENU_ASK_COACH := Tr("Ask coach", "Perguntar ao coach")
MENU_HIDE_COACH := Tr("Hide coach", "Ocultar coach")
MENU_SETTINGS := Tr("Settings", "Configurações")
MENU_NOTES := Tr("Patch notes", "Notas da atualização")
MENU_AUTO := Tr("Auto-open at champ select", "Abrir automaticamente na seleção de campeão")
MENU_RELOAD := Tr("Reload", "Recarregar")
MENU_EXIT := Tr("Exit", "Sair")
tray.Add(MENU_OVERLAY, (*) => OpenSmiteless(false))
tray.Add(MENU_PROFILE, (*) => OpenProfile())
tray.Add(MENU_WIDGET, (*) => OpenWidget())
tray.Add(MENU_COACH, (*) => OpenCoach())
tray.Add(MENU_ASK_COACH, (*) => AskCoach())
tray.Add(MENU_HIDE_COACH, (*) => HideCoach())
loginMenu := Menu()
tray.Add(Tr("Riot login", "Login Riot"), loginMenu)
tray.Add(MENU_SETTINGS, (*) => OpenSettings())
tray.Add(MENU_NOTES, (*) => OpenNotes())
tray.Add()
tray.Add(MENU_AUTO, ToggleAuto)
tray.Add()
tray.Add(MENU_RELOAD, (*) => Reload())
tray.Add(MENU_EXIT, (*) => ExitApp())
tray.Default := MENU_OVERLAY                      ; double-click the tray icon
RefreshAutoCheck()
StartCoach()
OnExit(StopCoach)

; Ctrl+Alt+X opens the overlay; Ctrl+Alt+B opens the item widget; Ctrl+Alt+C asks/cancels coach.
^!x::OpenSmiteless(false)
^!b::OpenWidget()
^!c::AskCoach()

OpenSmiteless(autoMode := false) {
    global PYW, SCRIPTS
    waitFlag := autoMode ? " --wait" : ""       ; auto-open stays hidden until champs are present
    Run('"' PYW '" "' SCRIPTS '\ui\smiteoverlay.py"' waitFlag, , "Hide")
}

OpenWidget() {
    global PYW, SCRIPTS                           ; small floating in-game item helper (single-instance)
    Run('"' PYW '" "' SCRIPTS '\ui\smitewidget.py"', , "Hide")
}

OpenProfile() {
    global PYW, SCRIPTS                           ; the home / profile window
    Run('"' PYW '" "' SCRIPTS '\ui\smiteprofile.py"', , "Hide")
}

OpenSettings() {
    global PYW, SCRIPTS
    Run('"' PYW '" "' SCRIPTS '\ui\smitesettings.py"', , "Hide")
}

OpenNotes() {
    global PYW, SCRIPTS                           ; the patch notes / what's new window
    Run('"' PYW '" "' SCRIPTS '\ui\smitenotes.py"', , "Hide")
}

StartCoach() {
    global PYW, SCRIPTS, TRAY_PID
    Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" coach serve --owner-pid ' TRAY_PID, , "Hide")
}

OpenCoach() {
    global PYW, SCRIPTS
    Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" coach show', , "Hide")
}

AskCoach() {
    global PYW, SCRIPTS
    Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" coach toggle', , "Hide")
}

HideCoach() {
    global PYW, SCRIPTS
    Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" coach hide', , "Hide")
}

CoachToken() {
    endpoint := EnvGet("USERPROFILE") "\.claude\cache\smiteless_coach_endpoint.json"
    try {
        if RegExMatch(FileRead(endpoint, "UTF-8"), '"token"\s*:\s*"([^"]+)"', &m)
            return m[1]
    }
    return ""
}

StopCoach(*) {
    global PYW, SCRIPTS
    token := CoachToken()
    if (token != "")
        Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" coach shutdown --endpoint-token="' token '"', , "Hide")
}

; --- "Riot login" submenu: one item per saved account session (managed in Settings). ---
ACCIDX := EnvGet("USERPROFILE") "\.claude\smiteless_accounts\index.json"
g_loginSig := "?"
BuildLoginMenu() {
    global loginMenu, ACCIDX, g_loginSig
    names := []
    try {
        txt := FileRead(ACCIDX, "UTF-8")
        pos := 1
        while (p := RegExMatch(txt, '"name"\s*:\s*"([^"]+)"', &m, pos)) {
            names.Push(m[1])
            pos := p + m.Len(0)
        }
    }
    sig := ""
    for n in names
        sig .= n "|"
    if (sig = g_loginSig)
        return
    g_loginSig := sig
    loginMenu.Delete()
    if (names.Length = 0) {
        loginMenu.Add("Set up in Settings…", (*) => OpenSettings())
        return
    }
    for n in names
        loginMenu.Add(n, LoginPick)
}
LoginPick(item, *) {
    global PYW, SCRIPTS
    Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" login "' item '"', , "Hide")
}
BuildLoginMenu()
SetTimer(BuildLoginMenu, 15000)

ToggleAuto(ItemName, *) {
    global NOAUTO
    if FileExist(NOAUTO)
        FileDelete(NOAUTO)                       ; enable auto-open
    else
        FileAppend("off", NOAUTO)                ; disable auto-open
    RefreshAutoCheck()
}

RefreshAutoCheck() {
    global NOAUTO, MENU_AUTO
    if FileExist(NOAUTO)
        A_TrayMenu.Uncheck(MENU_AUTO)
    else
        A_TrayMenu.Check(MENU_AUTO)
}

; Auto-open watcher: only while auto-open is on AND the client/game is up. Polls the LCU
; gameflow phase via phasecheck.py (async) and opens the overlay once per active session.
g_smiteOpened := false
g_widgetOpened := false
g_queueOpened := false
SmiteWatch() {
    global g_smiteOpened, g_widgetOpened, g_queueOpened, PYW, SCRIPTS, NOAUTO
    if FileExist(NOAUTO)                         ; auto-open disabled
        return
    if (!ProcessExist("LeagueClient.exe") && !ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_smiteOpened := false
        g_widgetOpened := false
        g_queueOpened := false
        return
    }
    out := A_Temp "\smiteless_phase.txt"
    ph := ""
    try ph := Trim(FileRead(out), " `t`r`n")     ; strip CR/LF (Trim's default omits them)
    Run('"' PYW '" "' SCRIPTS '\smiteless_main.py" phase "' out '"', , "Hide")   ; writes phase to file (no console)
    ; "Loading" = the loading screen (:2999 is answering but the game clock hasn't started).
    ; It counts as an ACTIVE session (the loading scout belongs there) but NOT as in-game —
    ; the item widget and death brief must not paint over the loading screen.
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "Loading" || ph = "InProgress" || ph = "Reconnect")
    ingame := (ph = "InProgress" || ph = "Reconnect")
    if (active) {
        if (!g_smiteOpened) {
            g_smiteOpened := true
            OpenSmiteless(true)
            ; LOADING SCOUT (ten splash cards) — spawns at champ select, covers the load, fades
            ; the instant the game starts. Self-gates on the `loading_scout` setting (default on).
            Run('"' PYW '" "' SCRIPTS '\ui\smiteload.py"', , "Hide")
            ; AUTO-MUTE — armed at champ select, sends /fullmute all the instant the game
            ; clock starts. Self-gates on the `auto_mute` setting (default on).
            Run('"' PYW '" "' SCRIPTS '\core\lolmute.py"', , "Hide")
        }
    } else {
        g_smiteOpened := false                   ; any non-active phase re-arms for the next game
    }
    ; QUEUE CALL — the lobby is the last moment "should I play this one?" can change
    ; anything, so it opens there and closes itself as soon as the phase moves on.
    if (ph = "Lobby") {
        if (!g_queueOpened) {
            g_queueOpened := true
            Run('"' PYW '" "' SCRIPTS '\ui\smitequeue.py"', , "Hide")
        }
    } else {
        g_queueOpened := false
    }
    if (ingame) {                                ; the floating item helper is in-game only
        if (!g_widgetOpened) {
            g_widgetOpened := true
            OpenWidget()
            Run('"' PYW '" "' SCRIPTS '\ui\smitedead.py"', , "Hide")   ; fullscreen death brief
            ; loading-screen scout overlay RETIRED — see DraftBoard live scout.
        }
    } else {
        g_widgetOpened := false
    }
}
SetTimer(SmiteWatch, 4000)
