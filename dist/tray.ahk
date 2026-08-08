#Requires AutoHotkey v2.0
#SingleInstance Force

; ============================================================
; Smiteless tray - the BUNDLED launcher (compiled to Smiteless.exe and shipped in the
; installer). Unlike the dev smiteless.ahk (which runs `python ui\*.py`), this drives the
; frozen app: app\SmitelessApp.exe <overlay|widget|settings|phase|update>. No Python or
; AutoHotkey needs to be installed on the user's machine.
;
; Install layout (A_ScriptDir = %LOCALAPPDATA%\Smiteless):
;   Smiteless.exe            <- this
;   VERSION
;   app\SmitelessApp.exe     <- the frozen Python app
;   assets\smiteless.ico
; ============================================================

APP := A_ScriptDir "\app\SmitelessApp.exe"
ICO := A_ScriptDir "\assets\smiteless.ico"
NOAUTO := EnvGet("USERPROFILE") "\.claude\smiteless_noautoopen"   ; present = auto-open OFF
NOHOME := EnvGet("USERPROFILE") "\.claude\smiteless_nohomeonstart" ; present = open profile/home at startup OFF
UPDATED_MARK := A_ScriptDir "\.updated_version"
SETTINGS := EnvGet("USERPROFILE") "\.claude\smiteless_settings.json"   ; read to gate auto-accept
TRAY_PID := ProcessExist()

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

if FileExist(ICO)
    TraySetIcon(ICO)
A_IconTip := "Smiteless"

tray := A_TrayMenu
tray.Delete()
MENU_OVERLAY := Tr("Open overlay", "Abrir overlay")
MENU_PROFILE := Tr("Profile / home", "Perfil / início")
MENU_WIDGET := Tr("Item widget", "Widget de itens")
MENU_COACH := Tr("Coach", "Coach")
MENU_ASK_COACH := Tr("Ask coach", "Perguntar ao coach")
MENU_HIDE_COACH := Tr("Hide coach", "Ocultar coach")
MENU_AUTO := Tr("Auto-open at champ select", "Abrir automaticamente na seleção de campeão")
MENU_UPDATES := Tr("Check for updates", "Buscar atualizações")
MENU_RELOAD := Tr("Reload", "Recarregar")
MENU_EXIT := Tr("Exit", "Sair")
tray.Add(MENU_OVERLAY, (*) => Launch("overlay"))
tray.Add(MENU_PROFILE, (*) => Launch("profile"))
tray.Add(MENU_WIDGET, (*) => Launch("widget"))
tray.Add(MENU_COACH, (*) => Launch("coach show"))
tray.Add(MENU_ASK_COACH, (*) => Launch("coach toggle"))
tray.Add(MENU_HIDE_COACH, (*) => Launch("coach hide"))
loginMenu := Menu()
tray.Add(Tr("Riot login", "Login Riot"), loginMenu)
tray.Add(Tr("Settings", "Configurações"), (*) => Launch("settings"))
tray.Add()
tray.Add(MENU_AUTO, ToggleAuto)
tray.Add(Tr("Usage stats", "Estatísticas de uso"), (*) => Launch("stats"))
tray.Add(Tr("Patch notes", "Notas da atualização"), (*) => Launch("notes"))
tray.Add(MENU_UPDATES, (*) => Launch("update --force"))
tray.Add()
tray.Add(MENU_RELOAD, (*) => Reload())
tray.Add(MENU_EXIT, (*) => ExitApp())
tray.Default := MENU_OVERLAY
RefreshAutoCheck()
ShowPostUpdate()
Launch("coach serve --owner-pid " TRAY_PID)
OnExit(StopCoach)

; Global hotkeys: Ctrl+Alt+X = overlay, Ctrl+Alt+B = item widget, Ctrl+Alt+C = coach
^!x::Launch("overlay")
^!b::Launch("widget")
^!c::Launch("coach toggle")

Launch(cmd) {
    global APP
    Run('"' APP '" ' cmd, , "Hide")
}

StopCoach(*) {
    token := CoachToken()
    if (token != "")
        Launch('coach shutdown --endpoint-token="' token '"')
}

CoachToken() {
    endpoint := EnvGet("USERPROFILE") "\.claude\cache\smiteless_coach_endpoint.json"
    try {
        if RegExMatch(FileRead(endpoint, "UTF-8"), '"token"\s*:\s*"([^"]+)"', &m)
            return m[1]
    }
    return ""
}

; --- "Riot login" submenu: one item per saved account session (managed in Settings). ---
; Rebuilt from ~\.claude\smiteless_accounts\index.json on a timer, only when it changes.
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
        loginMenu.Add("Set up in Settings…", (*) => Launch("settings"))
        return
    }
    for n in names
        loginMenu.Add(n, LoginPick)
}
LoginPick(item, *) {
    Launch('login "' item '"')
}
BuildLoginMenu()
SetTimer(BuildLoginMenu, 15000)

ToggleAuto(*) {
    global NOAUTO
    if FileExist(NOAUTO)
        FileDelete(NOAUTO)
    else
        FileAppend("off", NOAUTO)
    RefreshAutoCheck()
}

RefreshAutoCheck() {
    global NOAUTO, MENU_AUTO
    if FileExist(NOAUTO)
        A_TrayMenu.Uncheck(MENU_AUTO)
    else
        A_TrayMenu.Check(MENU_AUTO)
}

ShowPostUpdate() {
    global UPDATED_MARK
    if !FileExist(UPDATED_MARK)
        return
    ver := ""
    try ver := Trim(FileRead(UPDATED_MARK), " `t`r`n")
    try FileDelete(UPDATED_MARK)
    if (ver != "") {
        TrayTip("Updated to " ver, "Smiteless updated", 1)
    }
}

OpenHomeOnStartup() {
    global NOHOME
    if FileExist(NOHOME)
        return
    Launch("profile")
}

AutoUpdateOnLaunch() {
    global APP
    ; Always attempt background update apply on startup. If already current/offline, it exits quietly.
    Run('"' APP '" update --apply', , "Hide")
}

; Update notification: poll GitHub in the BACKGROUND and pop a tray balloon when a newer
; version exists - on launch AND every few minutes (so it notifies mid-session, not just at
; boot). Entirely IN-PROCESS (WinHttp straight to the GitHub API - no app spawn, no cursor
; flash). It renames the menu item to "Update to vX"; that click runs the one-click installer.
g_updateVer := ""
g_updLabel := MENU_UPDATES
CheckUpdate() {
    global g_updateVer, g_updLabel
    tag := ""
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("GET", "https://api.github.com/repos/bobbyroylee/smiteless/releases/latest", false)
        req.SetRequestHeader("User-Agent", "Smiteless-Tray")
        req.SetRequestHeader("Accept", "application/vnd.github+json")
        req.SetTimeouts(4000, 4000, 4000, 4000)
        req.Send()
        if (req.Status = 200 && RegExMatch(req.ResponseText, '"tag_name"\s*:\s*"([^"]+)"', &m))
            tag := m[1]
    }
    if (tag = "")
        return                                     ; offline / rate-limited -> try again next tick
    cur := "0.0.0"
    try cur := Trim(FileRead(A_ScriptDir "\VERSION"), " `t`r`n")
    if (!VerNewer(tag, cur))
        return                                     ; up to date
    ver := tag
    if (ver != g_updateVer) {
        g_updateVer := ver
        newLabel := Tr("Update to ", "Atualizar para ") ver
        try A_TrayMenu.Rename(g_updLabel, newLabel)
        g_updLabel := newLabel
        A_IconTip := "Smiteless  -  update " ver " available"
        TrayTip("Version " ver " is ready. Right-click the gold S in your tray, then '"
            . newLabel "'.", "Smiteless update available", 1)
    }
}

VerNewer(a, b) {
    ; true if version a > version b ("v0.2.44" vs "0.2.43"); junk parts count as 0
    pa := StrSplit(Trim(a, "vV `t`r`n"), "."), pb := StrSplit(Trim(b, "vV `t`r`n"), ".")
    loop Max(pa.Length, pb.Length) {
        na := 0, nb := 0
        try na := Integer(A_Index <= pa.Length ? pa[A_Index] : 0)
        try nb := Integer(A_Index <= pb.Length ? pb[A_Index] : 0)
        if (na != nb)
            return na > nb
    }
    return false
}
SetTimer(CheckUpdate, -12000)                  ; first check ~12s after launch
SetTimer(CheckUpdate, 5 * 60 * 1000)           ; then every 5 minutes
SetTimer(AutoUpdateOnLaunch, -7000)            ; auto-apply update attempt on launch
SetTimer((*) => Launch("keycheck"), -20000)    ; expired Riot dev key? -> paste-a-new-one prompt
SetTimer(OpenHomeOnStartup, -9000)             ; open profile/home shortly after startup
SetTimer(AutoAcceptTick, 1200)                 ; poll ready-check and auto-accept if enabled

AutoAcceptTick() {
    ; Auto-accept entirely IN-PROCESS via the League client's local API - no app launch, so
    ; there's no busy-cursor flash (spawning the windowed app every poll was the flicker).
    if (!AutoAcceptOn())
        return
    if (!ProcessExist("LeagueClientUx.exe") && !ProcessExist("LeagueClient.exe"))
        return
    r := LcuReq("GET", "/lol-matchmaking/v1/ready-check")
    if (InStr(r, '"state":"InProgress"') && InStr(r, '"playerResponse":"None"'))
        LcuReq("POST", "/lol-matchmaking/v1/ready-check/accept")
}

AutoAcceptOn() {
    global SETTINGS
    try {
        return RegExMatch(FileRead(SETTINGS), '"auto_accept"\s*:\s*true') > 0
    }
    return false                                   ; no settings file / never enabled -> off
}

; ---- talk to the League client's local API (LCU) directly, so the tray never has to spawn
;      the app just to poll. Reads the lockfile for the port+password, ignores the client's
;      self-signed cert, and uses HTTP Basic auth. ----
LcuLockfile() {
    for d in StrSplit("FCDEGH", "") {
        p := d ":\Riot Games\League of Legends\lockfile"
        if FileExist(p)
            return p
    }
    return ""
}

LcuReq(method, path) {
    lf := LcuLockfile()
    if (lf = "")
        return ""
    try {
        parts := StrSplit(FileRead(lf), ":")
        port := parts[3], pw := parts[4]
    } catch
        return ""
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open(method, "https://127.0.0.1:" port path, false)
        req.Option[4] := 0x3300                    ; SslErrorIgnoreFlags - accept the self-signed cert
        req.SetRequestHeader("Authorization", "Basic " LcuB64("riot:" pw))
        req.SetRequestHeader("Accept", "application/json")
        if (method = "POST")
            req.SetRequestHeader("Content-Type", "application/json")
        req.SetTimeouts(1000, 1000, 1000, 1000)
        req.Send()
        return req.Status "`n" req.ResponseText
    } catch
        return ""
}

LcuB64(s) {
    n := StrPut(s, "UTF-8") - 1
    buf := Buffer(n)
    StrPut(s, buf, "UTF-8")
    flags := 0x40000001                            ; CRYPT_STRING_BASE64 | CRYPT_STRING_NOCRLF
    sz := 0
    DllCall("crypt32\CryptBinaryToStringW", "Ptr", buf, "UInt", n, "UInt", flags, "Ptr", 0, "UInt*", &sz)
    out := Buffer(sz * 2)
    DllCall("crypt32\CryptBinaryToStringW", "Ptr", buf, "UInt", n, "UInt", flags, "Ptr", out, "UInt*", &sz)
    return RTrim(StrGet(out, "UTF-16"), "`r`n")
}

; Current gameflow phase, read entirely IN-PROCESS (no app spawn -> no cursor flash).
; Mirrors tools/phasecheck.py: the live-client port answering means a game/replay is running
; (gameflow says "None" during replays), else ask the LCU.
TrayPhase() {
    try {
        req := ComObject("WinHttp.WinHttpRequest.5.1")
        req.Open("GET", "https://127.0.0.1:2999/liveclientdata/gamestats", false)
        req.Option[4] := 0x3300                    ; self-signed cert
        req.SetTimeouts(600, 600, 600, 600)
        req.Send()
        if (req.Status = 200)
            return "InProgress"
    }
    r := LcuReq("GET", "/lol-gameflow/v1/gameflow-phase")
    if (r = "")
        return ""
    body := Trim(SubStr(r, InStr(r, "`n") + 1), ' "`r`n')
    return body                                    ; e.g. ChampSelect / InProgress / Lobby / None
}

; Auto-open watcher: overlay at champ select, item widget in-game (gated by auto-open).
; A single blip ("" = unreachable, or a momentary None while LeagueClientUx restarts) must
; NOT count as "game over" - that used to relaunch things / pop the profile MID-GAME. The
; end of a game is only believed after 2 consecutive definite non-game reads.
g_overlayOpened := false
g_widgetOpened := false
g_queueOpened := false
g_wasInGame := false
g_endStreak := 0
SmiteWatch() {
    global g_overlayOpened, g_widgetOpened, g_queueOpened, g_wasInGame, g_endStreak, NOAUTO
    autoOpen := !FileExist(NOAUTO)
    if (!ProcessExist("LeagueClient.exe") && !ProcessExist("LeagueClientUx.exe") && !ProcessExist("League of Legends.exe")) {
        g_overlayOpened := false
        g_widgetOpened := false
        g_queueOpened := false
        g_wasInGame := false
        g_endStreak := 0
        SetTimer(SmiteWatch, -9000)                 ; client closed -> check back later
        return
    }
    ph := TrayPhase()
    if (ph = "") {                                  ; unreachable (lag/teamfight/UX restart) -> hold state
        SetTimer(SmiteWatch, -4000)
        return
    }
    active := (ph = "ChampSelect" || ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    ingame := (ph = "GameStart" || ph = "InProgress" || ph = "Reconnect")
    if (active && autoOpen) {
        if (!g_overlayOpened) {
            g_overlayOpened := true
            Launch("overlay --wait")
            Launch("load")     ; spawn at CHAMP SELECT so it's already waiting when loading begins
            Launch("mute")     ; AUTO-MUTE: armed here, fires the instant the game clock starts
        }                      ; (spawned at the in-game flip it often arrived after loading ended)
    } else if (!active) {
        g_overlayOpened := false
    }
    ; QUEUE CALL - the lobby is the only phase where "should I play this one?" is still
    ; actionable, so it opens there and closes itself the moment you leave (self-gates on
    ; its setting). Once per visit to the lobby, never mid-queue.
    if (ph = "Lobby") {
        if (autoOpen && !g_queueOpened) {
            g_queueOpened := true
            Launch("queue")
        }
    } else {
        g_queueOpened := false
    }
    if (ingame) {
        g_endStreak := 0
        g_wasInGame := true
        if (autoOpen && !g_widgetOpened) {
            g_widgetOpened := true
            Launch("widget")
            Launch("dead")                          ; fullscreen death brief (self-gates on its setting)
            Launch("load")                          ; backstop only - single-instance; exits fast if load's over
        }
    } else {
        g_endStreak += 1
        if (g_endStreak >= 2) {                     ; ~2 consecutive definite reads = really over
            g_widgetOpened := false
            if (g_wasInGame) {
                g_wasInGame := false
                Launch("profile")
            }
        }
    }
    ; adaptive cadence: brisk while a session is live, relaxed while idle in the client.
    ; The poll is fully in-process now (WinHttp), so there's no spawn and no cursor cost.
    SetTimer(SmiteWatch, active ? -2500 : -5000)
}
SetTimer(SmiteWatch, -2500)
