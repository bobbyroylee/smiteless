#!/usr/bin/env python3
"""selftest.py - one-command health check for Smiteless.

Verifies every external dependency the overlay relies on, so you can tell at a glance
what's working - handy after a Riot dev-key rotation (they expire every 24h) or a new
patch (in case op.gg changes shape).

  python selftest.py
"""
import sys, os, time, json, ssl, urllib.request, urllib.error
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in ("core", "ui", "tools"):            # cross-folder flat imports
    sys.path.insert(0, os.path.join(_ROOT, _d))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OK, FAIL, SKIP = "PASS", "FAIL", "skip"
results = []


def check(name, fn):
    try:
        status, detail = fn()
    except Exception as e:
        status, detail = FAIL, f"{type(e).__name__}: {e}"
    results.append((name, status, detail))


def c_pillow():
    import PIL
    from PIL import Image  # noqa: F401
    return OK, f"Pillow {PIL.__version__}"


def c_ddragon():
    import lolbuild as lb
    dd = lb.ddragon()
    n = len(dd["id2name"])
    return (OK, f"patch {dd['ver']}, {n} champs") if n > 100 else (FAIL, f"only {n} champs cached")


def c_opgg():
    import lolbuild as lb
    dd = lb.ddragon()
    d = lb.opgg(dd["name2id"]["yasuo"], "mid")
    if d and "summary" in d:
        return OK, f"Yasuo mid WR {d['summary']['average_stats']['win_rate'] * 100:.1f}%"
    return FAIL, "no data (op.gg shape changed or blocked?)"


def c_riot_key():
    import lolscout as ls, lolbuild as lb
    key = ls.read_key()
    if not key:
        return SKIP, "no ~/.riot_api_key -> player scout disabled (overlay still works)"
    # MUST send a browser User-Agent: Riot's API is behind Cloudflare, which 403s
    # (error 1010) a bare Python urllib UA. The real scout (lolscout._get) sends lb.UA.
    req = urllib.request.Request(
        "https://na1.api.riotgames.com/lol/status/v4/platform-data",
        headers={"X-Riot-Token": key, "User-Agent": lb.UA})
    try:
        with urllib.request.urlopen(req, timeout=8, context=ssl.create_default_context()) as r:
            json.load(r)
        return OK, f"valid (key ...{key[-4:]})"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return FAIL, "rejected (401/403) - regenerate at developer.riotgames.com"
        return FAIL, f"HTTP {e.code}"


def _llm_health_result(selected, found):
    import llmcli
    selected = llmcli.normalize_provider(selected)
    states = "; ".join(
        f"{llmcli.provider_label(provider)}="
        f"{os.path.basename(found[provider]) if found.get(provider) else 'missing'}"
        for provider in llmcli.PROVIDERS
    )
    if found.get(selected):
        return OK, f"selected {llmcli.provider_label(selected)}; {states}"
    alternatives = [llmcli.provider_label(p) for p in llmcli.PROVIDERS
                    if p != selected and found.get(p)]
    action = (f"select installed {'/'.join(alternatives)} in Settings"
              if alternatives else f"install {llmcli.provider_label(selected)} CLI")
    return FAIL, (f"selected {llmcli.provider_label(selected)} is missing -> {action}; "
                  f"{states}")


def c_llm_cli():
    import llmcli
    import smiteconfig as cfg
    selected = cfg.load().get("llm_provider", cfg.LLM_PROVIDER_DEFAULT)
    return _llm_health_result(selected, llmcli.availability())


def c_coach_service_health():
    """Read-only coordinator/provider/worker health; never starts a provider or model."""
    import lolcoachipc
    import llmcli
    import smiteconfig as cfg

    settings = cfg.load()
    selected = llmcli.normalize_provider(settings.get("llm_provider"))
    endpoint = lolcoachipc.read_endpoint()
    if not endpoint:
        return SKIP, (f"selected {llmcli.provider_label(selected)}; coordinator not running; "
                      "worker unavailable")
    try:
        status = lolcoachipc.request({"type": "status"}, timeout=2, endpoint=endpoint)
    except lolcoachipc.IpcError as exc:
        return FAIL, f"selected {llmcli.provider_label(selected)}; coordinator unreachable: {exc}"
    worker = status.get("stt_worker") or {}
    if not status.get("ok") or status.get("provider") != selected:
        return FAIL, (f"selected {llmcli.provider_label(selected)}; coordinator reported "
                      f"{status.get('provider') or 'unknown'}")
    return OK, (f"selected {llmcli.provider_label(selected)}; coordinator={status.get('state')}; "
                f"manual={'on' if status.get('enabled') else 'off'}; "
                f"worker={'loaded' if worker.get('model_loaded') else 'unloaded'}")


def c_coach_readiness_health():
    """Report model/device/compute/microphone/TTS without download, load or capture."""
    import smiteaudio
    import smiteconfig as cfg
    import smitestt

    settings = cfg.load()
    try:
        configuration = smitestt.runtime_configuration(settings)
    except smitestt.SttError as exc:
        return FAIL, f"selected STT configuration unavailable: {exc.code}; no CPU fallback"
    readiness = smitestt.readiness()
    model = readiness.get("model") or {}
    runtime = readiness.get("runtime") or {}
    voices = ", ".join(
        f"{locale}={smiteaudio.voice_for_locale(locale)}/{smiteaudio.culture_for_locale(locale)}"
        for locale in ("en", "pt_BR"))
    detail = (f"model={model.get('state') or 'unknown'}; device={configuration['device']}; "
              f"compute={configuration['compute_type']}; policy={configuration['load_policy']}; "
              f"microphone={'ready' if readiness.get('microphone') else 'unavailable'}; "
              f"worker=unloaded; voices {voices}")
    if not all(runtime.get(name) for name in ("faster-whisper", "ctranslate2", "sounddevice")):
        return FAIL, "local Whisper runtime incomplete; " + detail
    if model.get("state") in ("invalid", "corrupt", "unavailable"):
        return FAIL, detail
    if not model.get("ready"):
        return SKIP, detail + "; one-time model download required"
    return OK, detail


def c_llm_providers():
    """Deterministic contracts for Claude/Codex discovery, dispatch and failures."""
    import subprocess
    from unittest import mock
    import claudecli as claude
    import codexcli as codex
    import llmcli
    import llmprocess

    prompt = "Give one short, generic matchup tip."
    calls = []

    class FakeProcess:
        def __init__(self, args, fake_stdout="", fake_stderr="", code=0, write_last=None,
                     timeout_once=False, **kwargs):
            self.args = args
            self.stdout_text = fake_stdout
            self.stderr_text = fake_stderr
            self.returncode = code
            self.pid = 4242
            self.write_last = write_last
            self.timeout_once = timeout_once
            self.timed_out = False
            calls.append((args, kwargs, self))

        def communicate(self, input=None, timeout=None):
            self.input = input
            if self.timeout_once and not self.timed_out:
                self.timed_out = True
                raise subprocess.TimeoutExpired(self.args, timeout)
            if self.write_last is not None:
                path = self.args[self.args.index("--output-last-message") + 1]
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(self.write_last)
            return self.stdout_text, self.stderr_text

    bad = []
    with mock.patch.object(claude.os.path, "exists", return_value=False), \
            mock.patch.object(claude.shutil, "which", return_value=r"C:\bin\claude.exe"):
        claude_found = claude.find_claude()
    with mock.patch.object(codex.shutil, "which", return_value=r"C:\bin\codex.exe"):
        codex_found = codex.find_codex()
    if claude_found != r"C:\bin\claude.exe" or codex_found != r"C:\bin\codex.exe":
        bad.append("independent discovery")

    with mock.patch.object(claude, "call_claude", return_value=("claude", None)) as ccall, \
            mock.patch.object(codex, "call_codex", return_value=("codex", None)) as xcall:
        if llmcli.call(prompt, "claude", allow_web=True) != ("claude", None):
            bad.append("Claude dispatch")
        if xcall.called:
            bad.append("Claude failure could fail over to Codex")
        if llmcli.call(prompt, "codex", allow_web=True) != ("codex", None):
            bad.append("Codex dispatch")
        if ccall.call_count != 1 or xcall.call_count != 1:
            bad.append("provider dispatch count")

    calls.clear()
    with mock.patch.object(claude, "find_claude", return_value="claude.exe"), \
            mock.patch.object(claude.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, fake_stdout="Claude answer", **kw)):
        got = claude.call_claude(prompt, allow_tools="WebSearch,WebFetch", timeout=3)
    if got != ("Claude answer", None):
        bad.append("Claude success contract")
    else:
        args, kwargs, process = calls[-1]
        if process.input != prompt or "--allowedTools" not in args \
                or kwargs.get("shell") is not None:
            bad.append("Claude args/stdin")

    calls.clear()
    with mock.patch.object(codex, "find_codex", return_value="codex.exe"), \
            mock.patch.object(codex.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, fake_stdout="progress must be ignored",
                                  write_last="Codex answer", **kw)):
        got = codex.call_codex(prompt, timeout=3, allow_web=True)
    if got != ("Codex answer", None):
        bad.append("Codex last-message contract")
    else:
        args, kwargs, process = calls[-1]
        required = ("exec", "--ephemeral", "read-only", "--cd",
                    "--output-last-message", "-")
        if process.input != prompt or any(value not in args for value in required) \
                or kwargs["cwd"] != args[args.index("--cd") + 1]:
            bad.append("Codex args/stdin")

    cases = (
        ("auth", dict(fake_stdout="authentication_error"), "auth/API error"),
        ("limit", dict(fake_stderr="rate limit exceeded"), "limit"),
        ("exit", dict(fake_stdout="must not become a tip", code=7), "must not become a tip"),
        ("empty", dict(), "no text"),
        ("missing output", dict(fake_stdout="progress only"), "no text"),
    )
    for name, behavior, expected in cases:
        calls.clear()
        with mock.patch.object(codex, "find_codex", return_value="codex.exe"), \
                mock.patch.object(codex.subprocess, "Popen",
                                  side_effect=lambda args, _b=behavior, **kw: FakeProcess(
                                      args, **_b, **kw)):
            text, error = codex.call_codex(prompt, timeout=3)
        if text is not None or expected not in (error or ""):
            bad.append(f"Codex {name} failure")

    calls.clear()
    killed = []
    with mock.patch.object(codex, "find_codex", return_value="codex.exe"), \
            mock.patch.object(codex.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, timeout_once=True, **kw)), \
            mock.patch.object(llmprocess.subprocess, "run",
                              side_effect=lambda *a, **kw: killed.append((a, kw))):
        got = codex.call_codex(prompt, timeout=1)
    if got != (None, "timed out") or not killed:
        bad.append("Codex timeout/tree termination")

    claude_cases = (
        ("auth", dict(fake_stdout="authentication_error"), "auth/API error"),
        ("limit", dict(fake_stderr="usage limit reached"), "limit"),
        ("exit", dict(fake_stderr="bad invocation", code=7), "bad invocation"),
        ("empty", dict(), "no text"),
    )
    for name, behavior, expected in claude_cases:
        calls.clear()
        with mock.patch.object(claude, "find_claude", return_value="claude.exe"), \
                mock.patch.object(claude.subprocess, "Popen",
                                  side_effect=lambda args, _b=behavior, **kw: FakeProcess(
                                      args, **_b, **kw)):
            text, error = claude.call_claude(prompt, timeout=3)
        if text is not None or expected not in (error or ""):
            bad.append(f"Claude {name} failure")

    calls.clear()
    killed = []
    with mock.patch.object(claude, "find_claude", return_value="claude.exe"), \
            mock.patch.object(claude.subprocess, "Popen",
                              side_effect=lambda args, **kw: FakeProcess(
                                  args, timeout_once=True, **kw)), \
            mock.patch.object(llmprocess.subprocess, "run",
                              side_effect=lambda *a, **kw: killed.append((a, kw))):
        got = claude.call_claude(prompt, timeout=1)
    if got != (None, "timed out") or not killed:
        bad.append("Claude timeout/tree termination")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, "Claude/Codex discovery, dispatch, stdin, output and failures are isolated"


def c_llm_integration():
    """Provider config, matchup/coach dispatch and health behavior without live inference."""
    import tempfile
    from unittest import mock
    import lolcoach
    import lolmatchup
    import llmcli
    import smiteconfig as cfg

    bad = []
    real_path = cfg.PATH
    with tempfile.TemporaryDirectory(prefix="smiteless-llm-fixture-") as tmp:
        cfg.PATH = os.path.join(tmp, "settings.json")
        try:
            cases = ((None, "claude"), ("claude", "claude"), ("codex", "codex"),
                     ("other", "claude"))
            for raw_value, expected in cases:
                raw = {} if raw_value is None else {"matchup_tip_provider": raw_value}
                with open(cfg.PATH, "w", encoding="utf-8") as handle:
                    json.dump(raw, handle)
                loaded = cfg.load()
                if loaded["llm_provider"] != expected or loaded["matchup_tip_provider"] != expected:
                    bad.append(f"config normalization {raw_value!r}")

            migration_cases = (
                ({"matchup_tip_provider": "codex"}, "codex"),
                ({"llm_provider": "codex"}, "codex"),
                ({"llm_provider": "claude", "matchup_tip_provider": "codex"}, "claude"),
                ({"llm_provider": "invalid", "matchup_tip_provider": "codex"}, "claude"),
            )
            for raw, expected in migration_cases:
                with open(cfg.PATH, "w", encoding="utf-8") as handle:
                    json.dump(raw, handle)
                if cfg.load()["llm_provider"] != expected:
                    bad.append(f"llm_provider migration {raw!r}")

            with open(cfg.PATH, "w", encoding="utf-8") as handle:
                json.dump({"matchup_tip_provider": "codex", "matchup_tips": False}, handle)
            saved = cfg.save({"board_size": 80})
            if saved.get("llm_provider") != "codex" \
                    or saved.get("matchup_tip_provider") != "codex" \
                    or saved.get("matchup_tips") is not False:
                bad.append("partial save did not preserve provider/toggle")

            dd = {
                "norm": lambda value: "".join(c for c in value.lower() if c.isalnum()),
                "name2id": {"yasuo": 1, "syndra": 2},
                "id2name": {1: "Yasuo", 2: "Syndra"},
            }
            tip_path = os.path.join(tmp, "tip.txt")
            with mock.patch.object(lolmatchup.lb, "ddragon", return_value=dd), \
                    mock.patch.object(lolmatchup, "written_tip",
                                      return_value="Written guide tip"), \
                    mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                    mock.patch.object(lolmatchup.llmcli, "call") as call_mock:
                got = lolmatchup.generate_tip(
                    "Yasuo", "Yasuo", "Syndra", "Syndra", "mid", "16.15")
            if got != ("Written guide tip", None) or call_mock.called:
                bad.append("written tip did not precede CLI")

            with open(tip_path, "w", encoding="utf-8") as handle:
                handle.write("Cached guide tip")
            with mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                    mock.patch.object(lolmatchup.llmcli, "call") as call_mock:
                cached = lolmatchup.get_tip("Yasuo", "Syndra", "mid", "16.15")
            if cached != "Cached guide tip" or call_mock.called:
                bad.append("cache did not precede CLI")

            for provider in llmcli.PROVIDERS:
                if os.path.exists(tip_path):
                    os.remove(tip_path)
                with mock.patch.object(lolmatchup.cfg, "load",
                                       return_value={"llm_provider": provider}), \
                        mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                        mock.patch.object(lolmatchup.llmcli, "call",
                                          return_value=(f"{provider} tip", None)) as call_mock:
                    text, error = lolmatchup._generate_tip_llm(
                        "Yasuo", "Yasuo", "Syndra", "Syndra", "mid", "16.15")
                if (text, error) != (f"{provider} tip", None) \
                        or call_mock.call_args.args[1] != provider:
                    bad.append(f"matchup {provider} dispatch")

                if os.path.exists(tip_path):
                    os.remove(tip_path)
                with mock.patch.object(lolmatchup.cfg, "load",
                                       return_value={"llm_provider": provider}), \
                        mock.patch.object(lolmatchup, "_file", return_value=tip_path), \
                        mock.patch.object(lolmatchup.llmcli, "call",
                                          return_value=(None, f"{provider} unavailable")):
                    text, error = lolmatchup._generate_tip_llm(
                        "Yasuo", "Yasuo", "Syndra", "Syndra", "mid", "16.15")
                if text is not None or not error or os.path.exists(tip_path):
                    bad.append(f"matchup {provider} error cached")

            with mock.patch.object(lolcoach.cfg, "load",
                                   return_value={"llm_provider": "codex"}), \
                    mock.patch.object(lolcoach.llmcli, "call",
                                      return_value=("coach", None)) as coach_call:
                coach_got = lolcoach._call_ai("generic coach prompt")
            if coach_got != ("coach", None) or coach_call.call_args.args[1] != "codex":
                bad.append("coach configured provider")
        finally:
            cfg.PATH = real_path

    for selected in llmcli.PROVIDERS:
        for mask in range(4):
            found = {
                "claude": ("claude.exe" if mask & 1 else None),
                "codex": ("codex.exe" if mask & 2 else None),
            }
            status, detail = _llm_health_result(selected, found)
            expected = OK if found[selected] else FAIL
            if status != expected or "Claude=" not in detail or "Codex=" not in detail:
                bad.append(f"health {selected}/{mask}")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, "config, written/cache precedence, matchup/coach dispatch and health matrix"


def c_glyphs():
    import glyphcheck
    bad = glyphcheck.check()
    if bad:
        return FAIL, bad[0] + (f" (+{len(bad) - 1} more)" if len(bad) > 1 else "")
    return OK, "no text-blind symbol draws (tofu tripwire)"


def c_tagspec():
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(_ROOT, "tools", "tagcheck.py")],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        return OK, "tag fixtures conform to docs/TAGS.md"
    tail = (r.stdout or r.stderr).strip().splitlines()
    return FAIL, tail[-1] if tail else "tagcheck failed"


def c_queuecall():
    """The QUEUE CALL verdict engine, on fixtures that must each land on one verdict —
    it reads your live history in the lobby, so a silent logic break would just look
    like 'it always says GO'."""
    import lolqueue as lq
    want = {"stop": "STOP", "last": "LAST ONE", "wait": "WAIT"}
    got = {k: lq.call(lq.demo(k))["verdict"] for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lq.call([])["verdict"] != "GO":
        return FAIL, "empty history must fall through to GO"
    return OK, "stop / last-one / wait fixtures each land on their verdict"


def c_reentry():
    """The RE-ENTRY verdict engine (the 90s guard after you respawn). Fires from a state
    machine inside a live game, so a logic break is otherwise invisible until it silently
    says HOLD forever — or never."""
    import lolreentry as lre
    want = {"hold": "HOLD", "clear": "CLEAR", "reset": "RESET"}
    got = {k: lre._verdict(lre.demo(k))["verdict"] for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lre.WINDOW != 90.0:
        return FAIL, f"window is {lre.WINDOW}s — it must match the death_cluster tag's 90s"
    g = lre.Guard()                              # dead -> alive must arm; no data must not
    if g.observe(None, None) is not None or g.armed_until is not None:
        return FAIL, "guard armed itself with no game data"
    return OK, "hold / clear / reset fixtures each land on their verdict"


def c_bleed():
    """The BLEED verdict engine (the first-14-minutes health guard). Same shape of risk as
    RE-ENTRY: a broken branch either screams every wave or never fires once, and neither is
    visible without playing a game."""
    import lolbleed as lbl
    want = {"bleed": "BLEED", "dive": "BLEED", "banked": "BLEED",
            "healthy": None, "accounted": None, "alone": None, "noread": None}
    got = {k: (lbl._verdict(lbl.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lbl.WINDOW != 14 * 60.0:
        return FAIL, f"window is {lbl.WINDOW}s — it must match the early_bleeding tag's 14:00"
    return OK, "3 warning + 4 silent fixtures each land where they should"


def c_closer():
    """The CLOSER (the post-20:00 win-conversion director). Two things must hold forever:
    every verdict branch is reachable, and it is SILENT in any game you are not winning —
    a closeout coach talking during a losing game is worse than no coach."""
    import lolclose as lc
    want = {"end": "END", "siege": "SIEGE", "close": "CLOSE", "closeinhib": "CLOSE",
            "quietclose": "CLOSE", "hold": "HOLD", "giveback": "HOLD", "bank": "BANK",
            "behind": None, "early": None, "thin": None, "winning_fight": "BANK"}
    got = {k: (lc._verdict(lc.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    if lc.LEAD_MIN != 2000.0:
        return FAIL, f"lead bar is {lc.LEAD_MIN} — it must match the threw_ahead tag's 2000g"
    # never contradict a positive fight read: tempo saying TAKE and the closer saying HOLD
    # on the same frame is the app arguing with itself.
    for e in (900.0, 3000.0, 12000.0):
        d = lc.demo("hold")
        d["e"] = e
        if (lc._verdict(d) or {}).get("verdict") == "HOLD":
            return FAIL, f"HOLDs while fight_edge says +{e:.0f} — contradicts the tempo card"
    # the structure map is COUNT-based on purpose (turrets can only fall front-to-back), so
    # a Riot rename of the turret indices must not change the depth read.
    ev = [{"EventName": "TurretKilled", "EventTime": 600 + i,
           "TurretKilled": f"Turret_T2_C_{5 - i:02d}_A"} for i in range(3)]
    ev.append({"EventName": "InhibKilled", "EventTime": 900, "InhibKilled": "Barracks_T2_C1"})
    st = lc.structures(ev, "ORDER")
    if st["them"]["turrets"].get("C") != 3 or lc.steps_to_inhib(st["them"])["C"] != 0:
        return FAIL, f"structure map misread their mid: {st['them']['turrets']}"
    oi = lc.open_inhibs(st["them"], 1000.0)
    if not oi or oi[0][0] != "C" or abs(oi[0][1] - 200.0) > 0.5:
        return FAIL, f"inhibitor clock wrong: {oi}"
    if lc.open_inhibs(st["them"], 1201.0):
        return FAIL, "inhibitor never closes — it respawns 5:00 after the kill"
    g = lc.Guard()                               # no data must not arm anything
    if g.observe(None, None) is not None or g.peak != 0.0:
        return FAIL, "guard armed itself with no game data"
    return OK, "12 verdict fixtures + structure map + inhib clock all correct"


def c_gold():
    """The GOLD CLOCK (core/lolgold) — the first-ten farm read. Three things must hold
    forever, and none of them are visible without playing a game: the minion SCHEDULE is
    exact (it is the denominator for every number the surface prints), the bar is still the
    weak_first_ten tag's own, and it is SILENT for the roles whose CS is not the story."""
    import lolgold as lg, lollive as ll
    # --- the schedule. Wave k spawns at 1:05 + 30(k-1) and is only counted once it has
    #     ARRIVED (mid meets at 1:30, side lanes at 1:38). Off by one wave = every number
    #     the card prints is wrong, quietly.
    for role, trav in lg.LANE_ARRIVE.items():
        for k in (1, 3, 7, 18, 26):
            at = lg.WAVE_FIRST + lg.WAVE_EVERY * (k - 1) + trav
            if lg.waves_by(at - 0.01, role) != k - 1 or lg.waves_by(at, role) != k:
                return FAIL, f"{role}: wave {k} is not counted at its {at:.0f}s arrival"
    if lg.waves_by(90.0, "mid") != 1 or lg.waves_by(89.9, "mid") != 0:
        return FAIL, "mid lane does not meet at 1:30"
    if lg.waves_by(98.0, "adc") != 1 or lg.waves_by(97.9, "adc") != 0:
        return FAIL, "the side lanes do not meet at 1:38"
    if lg.offered(600.0, "mid") != (114, 2250.0):
        return FAIL, f"mid is offered {lg.offered(600.0, 'mid')} by 10:00, not (114, 2250)"
    # every minion value is flat until 15:00 — that is the whole reason this can be exact
    # rather than modelled, so the last wave inside the window must still spawn before it.
    last = lg.waves_by(lg.WINDOW, "mid")
    if lg.WAVE_FIRST + lg.WAVE_EVERY * (last - 1) >= 15 * 60:
        return FAIL, f"wave {last} spawns at/after 15:00 — minion gold is no longer flat"
    for t in range(0, 900, 13):                  # the cannon clock can never look backwards
        nc = lg.next_cannon(float(t), "mid")
        if nc[0] < 0 or nc[1] % 3 or nc[1] <= lg.waves_by(float(t), "mid"):
            return FAIL, f"cannon clock wrong at {t}s: {nc}"
    # --- the bars are the tag's, and gold-per-CS is DERIVED from lollive, never re-typed
    if lg.BAR_CS10 != 55 or lg.FIRST_TEN != 600.0:
        return FAIL, f"bar is {lg.BAR_CS10} CS at {lg.FIRST_TEN}s — must match weak_first_ten"
    probe = ll.est_gold({"scores": {"creepScore": 100}}, 300.0) - ll.est_gold({"scores": {}}, 300.0)
    if abs(lg.cs_gold() * 100 - probe) > 1e-6:
        return FAIL, f"gold-per-CS ({lg.cs_gold()}) has drifted from lollive.est_gold"
    # --- every verdict branch is reachable and lands where it should
    want = {"pace": "PACE", "behind": "PACE", "miss": "MISS", "cannon": "CANNON",
            "roaming": "PACE", "unrecoverable": "MISS", "onpace_miss": "PACE",
            "jungle": None, "support": None, "early": None, "late": None}
    got = {k: (lg._verdict(lg.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    # a kill-fed lane is NOT a weak first ten — the tag needs the gold bar missed too, and
    # scolding a roaming mid for his CS is how you teach somebody to stop roaming.
    if (lg._verdict(lg.demo("roaming")) or {}).get("under"):
        return FAIL, "a 30-CS mid with three kills read as under the farm bar"
    # a live objective verdict always outranks a dropped wave
    if (lg._verdict(dict(lg.demo("miss"), tempo_urgent=True)) or {}).get("quiet") is not True:
        return FAIL, "MISS talks over a live tempo verdict"
    # --- the guard: never bill a wave lost on the grey screen, never speak while dead
    g, billed = lg.Guard(), 0
    for t in range(0, 700):
        dead = 240 <= t <= 330
        cs = int(lg.offered(float(min(t, 240)), "mid")[0] * 0.90)
        me = {"riotId": "M#1", "team": "ORDER", "position": "MIDDLE", "isDead": dead,
              "level": 6, "championName": "Ahri",
              "scores": {"creepScore": cs, "kills": 0, "assists": 0, "deaths": 0}}
        c = g.observe({}, {"activePlayer": {"riotId": "M#1"}, "allPlayers": [me],
                           "gameData": {"gameTime": float(t)}, "events": {"Events": []}})
        if dead and c:
            return FAIL, f"the gold clock spoke at {t}s while the player was dead"
        if c and c["verdict"] == "MISS" and 240 <= t <= 400:
            billed += 1
    if billed:
        return FAIL, f"billed {billed} MISS cards for waves lost while dead"
    if g.observe({}, None) is not None or lg.Guard().observe({}, {}) is not None:
        return FAIL, "guard produced a card with no game data"
    return OK, "wave schedule exact, bar matches the tag, 11 fixtures + dead-wave rule hold"


def c_ward():
    """The WARD CLOCK (core/lolward) — the live vision war for jungle + support. Four things
    must hold forever and none of them are visible without playing a game: it is SILENT until
    the live feed has proven it reports a vision score at all (otherwise it accuses a support
    who has warded all game of being dark), it never bills you for dark time you spent on the
    grey screen, its bar is lolprofile's own, and it stays quiet for the roles the profile has
    never graded on vision."""
    import lolward as lw, lolprofile as lp, loltempo as lt, smitei18n as i18n
    # --- ONE BRAIN: the bar is lolprofile's, the pit sides are loltempo's. Both are read at
    #     runtime rather than re-typed, so a change on either side can't silently diverge.
    if lw.vpm_bar("support") != lp.VPM_BAR["UTILITY"] or lw.vpm_bar("jungle") != lp.VPM_BAR["JUNGLE"]:
        return FAIL, f"vision bar {lw._BAR['v']} has drifted from lolprofile.VPM_BAR"
    if set(lw.ROLE_POS.values()) != set(lp.VPM_BAR):
        return FAIL, "the roles this speaks for aren't the roles low_vision is evaluated for"
    if lw.OBJ_SIDE != lt._OBJ_SIDE:
        return FAIL, f"pit sides {lw.OBJ_SIDE} have drifted from loltempo._OBJ_SIDE"
    # --- None and 0.0 are NOT the same: one is 'hasn't warded', one is 'not being reported',
    #     and coaching on the second is the whole reason the arming tripwire exists.
    if lw.ward_score({"scores": {"wardScore": 0}}) != 0.0:
        return FAIL, "a reported vision score of 0 was collapsed to 'no data'"
    for bad in ({}, {"scores": {}}, {"scores": {"wardScore": None}}, {"scores": {"wardScore": "x"}},
                {"scores": {"wardScore": float("nan")}}, None):
        if lw.ward_score(bad) is not None:
            return FAIL, f"ward_score invented a number from {bad!r}"
    if lw.feed_live([{"scores": {"wardScore": 0}}] * 10) or not lw.feed_live(
            [{"scores": {"wardScore": 0}}] * 9 + [{"scores": {"wardScore": 3.5}}]):
        return FAIL, "the feed tripwire arms on an all-zero game (or won't arm on a live one)"
    if lw.ctrl_wards({"items": [{"itemID": 2055, "count": 2}, {"itemID": 3340, "count": 1}]}) != 2:
        return FAIL, "control wards are counted by slot instead of by stack count"
    # --- the counterpart is the same role or it is nothing: a wrong comparison is worse than
    #     no comparison, so an ambiguous lobby must drop the segment rather than guess.
    en = [{"position": "UTILITY", "scores": {"creepScore": 20}},
          {"position": "JUNGLE", "scores": {"creepScore": 120}},
          {"position": "MIDDLE", "scores": {"creepScore": 140}}]
    if lw.counterpart({"position": "UTILITY"}, en) is not en[0]:
        return FAIL, "counterpart didn't match support to support"
    if lw.counterpart({"position": "JUNGLE"}, en) is not en[1]:
        return FAIL, "counterpart didn't match jungler to jungler"
    nop = [{"scores": {"creepScore": 15}}, {"scores": {"creepScore": 15}}]
    if lw.counterpart({"position": "UTILITY"}, nop) is not None:
        return FAIL, "counterpart guessed between two equally plausible players"
    smite = [{"scores": {"creepScore": 90},
              "summonerSpells": {"summonerSpellOne": {"displayName": "Smite"}}},
             {"scores": {"creepScore": 90}}]
    if lw.counterpart({"position": "JUNGLE"}, smite) is not smite[0]:
        return FAIL, "counterpart ignored the smite fallback when positions are missing"
    # --- the pit window is lollive's own flags, plus a tail; scuttle is not a pit.
    if lw.pit_window([{"label": "Scuttle", "secs": 20, "urgent": True}]) is not None:
        return FAIL, "scuttle read as a pit"
    if lw.pit_window([{"label": "Drake", "secs": 60, "setup": True}]) is None:
        return FAIL, "an open setup window didn't register as a pit"
    if lw.pit_window([{"label": "Baron", "secs": -(lw.PIT_TAIL + 5), "up": True}]) is not None:
        return FAIL, "a pit stayed open forever after the objective spawned"
    # --- every verdict branch is reachable and lands where it should
    want = {"row": "WARD", "under": "WARD", "pit": "PIT", "pitup": "PIT", "pitshort": "WARD",
            "pitfight": "WARD", "dark": "DARK", "darkquiet": "WARD", "pink": "PINK",
            "pinkquiet": "WARD", "jungle": "WARD", "adc": None, "mid": None,
            "notarmed": None, "nofield": None, "early": None, "nocounterpart": "WARD"}
    got = {k: (lw._verdict(lw.demo(k)) or {}).get("verdict") for k in want}
    bad = [f"{k}: got {v}, want {want[k]}" for k, v in got.items() if v != want[k]]
    if bad:
        return FAIL, "; ".join(bad)
    for k in ("pitfight", "pitshort", "darkquiet", "pinkquiet", "row", "under"):
        if not (lw._verdict(lw.demo(k)) or {}).get("quiet"):
            return FAIL, f"{k} took the directive card when it should be a quiet row"
    if (lw._verdict(lw.demo("nocounterpart")) or {}).get("them") is not None:
        return FAIL, "an unknown counterpart still produced a head-to-head number"
    # --- the guard, driven through whole games. A support who wards on a normal cadence must
    #     never be accused; one who stops must be caught; and neither must be billed for the
    #     seconds he spent dead.
    def game(vs_at, dead=lambda t: False, pinks=lambda t: 0, role="UTILITY", n=1500,
             trink=3340, gold=300.0):
        g, out = lw.Guard(), []
        for t in range(n):
            me = {"riotId": "M#1", "team": "ORDER", "position": role, "isDead": dead(t),
                  "level": 9, "championName": "Nautilus",
                  "items": ([{"itemID": 2055, "count": pinks(t)}] if pinks(t) else [])
                           + [{"itemID": trink, "slot": 6}],
                  "scores": {"creepScore": 10, "kills": 0, "assists": 3, "deaths": 0,
                             "wardScore": vs_at(t)}}
            foe = {"riotId": "E#1", "team": "CHAOS", "position": role, "level": 9,
                   "scores": {"creepScore": 12, "wardScore": 0.02 * t}}
            out.append((t, g.observe({}, {"activePlayer": {"riotId": "M#1",
                                                            "currentGold": gold},
                                          "allPlayers": [me, foe],
                                          "gameData": {"gameTime": float(t)},
                                          "events": {"Events": []}})))
        return g, out
    _g, warder = game(lambda t: 0.03 * t)                  # a ward alive basically always
    if any(c and not c.get("quiet") for _t, c in warder):
        return FAIL, "a support warding all game was still handed a card"
    if not any(c for _t, c in warder):
        return FAIL, "a normal support game produced no vision row at all"
    _g, stops = game(lambda t: 0.03 * min(t, 400))         # ...who stops warding at 6:40
    darks = [t for t, c in stops if c and c.get("verdict") == "DARK"]
    if not darks or darks[0] < 400 + lw.DARK_SECS:
        return FAIL, f"DARK fired at {darks[:1]} — before the score had actually been flat"
    # dead time is FROZEN, not reset and not accrued: 200s on the grey screen must neither
    # hand out a free window nor bill a death two other guards already own.
    _g, dd_ = game(lambda t: 0.03 * min(t, 300), dead=lambda t: 320 <= t < 520)
    if any(c for t, c in dd_ if 320 <= t < 520):
        return FAIL, "the ward clock spoke while the player was dead"
    # He went dark at 5:00 and died at 5:20, so 20s of dark is banked when he respawns at
    # 8:40. FROZEN means the card is due exactly DARK_SECS-20 later; ACCRUED would fire the
    # instant he stands up, RESET would cost him a full extra window.
    dark_after = [t for t, c in dd_ if c and c.get("verdict") == "DARK"]
    due = 520 + (lw.DARK_SECS - 20)
    if not dark_after:
        return FAIL, "a support who went dark before dying was never told after he respawned"
    if dark_after[0] < due - 5:
        return FAIL, f"DARK at {dark_after[0]}s, due {due:.0f} — dark time accrued while dead"
    if dark_after[0] > due + 5:
        return FAIL, f"DARK at {dark_after[0]}s, due {due:.0f} — the clock RESET on death"
    # the arming tripwire: a whole game with no vision score reported anywhere is total silence
    _g, quiet = game(lambda t: None)
    if any(c for _t, c in quiet):
        return FAIL, "spoke about vision in a game where :2999 reported no vision score"
    # a carried control ward is said ONCE per stock — one card window (it holds the slot for
    # CARD_SECS so it can be read), never a second one for the same ward.
    pkg, pk = game(lambda t: 0.03 * t, pinks=lambda t: 1 if t > 200 else 0)
    on = [t for t, c in pk if c and c.get("verdict") == "PINK"]
    windows = sum(1 for a, b in zip([-99] + on, on) if b - a > 1)
    if windows != 1:
        return FAIL, f"the carried-control-ward card opened {windows} windows for one ward"
    if not on or abs(len(on) - lw.CARD_SECS) > 1:
        return FAIL, f"the PINK card held the slot for {len(on)}s, not {lw.CARD_SECS:.0f}s"
    if max(c.get("calls") or 0 for _t, c in pk if c) != 1:
        return FAIL, "calls counts frames instead of card windows (a voice line would stutter)"
    # laners are never graded on vision here, exactly as lolprofile never grades them
    for pos in ("TOP", "MIDDLE", "BOTTOM"):
        if any(c for _t, c in game(lambda t: 0.0, role=pos, n=800)[1]):
            return FAIL, f"the ward clock spoke to a {pos} laner"
    # malformed payloads must never crash the widget's poll thread
    g = lw.Guard()
    for junk in (None, {}, {"allPlayers": []}, {"activePlayer": {}, "allPlayers": [{}]},
                 {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1"}],
                  "gameData": {"gameTime": "soon"}},
                 {"activePlayer": {"riotId": "M#1"}, "allPlayers": [{"riotId": "M#1"}],
                  "gameData": {"gameTime": float("nan")}},
                 {"activePlayer": {"riotId": "M#1"},
                  "allPlayers": [{"riotId": "M#1", "position": "UTILITY", "items": [{}],
                                  "scores": {"wardScore": "?"}}],
                  "gameData": {"gameTime": 600.0}}):
        if g.observe({}, junk) is not None:
            return FAIL, f"produced a card from a malformed payload: {junk!r}"
    # --- v0.9.69: the trinket read, the deadline, the pink LEDGER and the recall buy prompt.
    #     All four change what the card SAYS, so each is checked on the text and not just on
    #     a verdict name.
    for iid, want in ((3340, "yellow"), (3363, "farsight"), (3364, "sweeper")):
        if lw.trinket({"items": [{"itemID": 2055}, {"itemID": iid, "slot": 6}]}) != want:
            return FAIL, f"trinket {iid} read as something else"
    if lw.trinket({"items": [{"itemID": 2055}]}) is not None:
        return FAIL, "an empty trinket slot must read None, not a guess"
    for junk in (None, {}, {"items": None}, {"items": [None]}, {"items": [{"itemID": "x"}]}):
        if lw.trinket(junk) is not None or lw.ctrl_wards(junk):
            return FAIL, f"the inventory read invented something from {junk!r}"
    sw = lw._verdict(lw.demo("pitsweeper"))
    sweep_copy = i18n.t(lw._HOW["sweeper"])
    if sweep_copy not in sw["sub"]:
        return FAIL, "a sweeper wasn't told to take theirs first"
    fs = lw._verdict(lw.demo("pitfarsight"))
    farsight_copy = i18n.t(lw._HOW["farsight"])
    if farsight_copy not in fs["sub"] or sweep_copy in fs["sub"]:
        return FAIL, "a farsight was told to sweep, which it cannot do"
    if lw._HOW.get("yellow"):
        return FAIL, "a plain yellow trinket adds a clause that says nothing"
    # the DEADLINE: named while there is still one, and never once the fight has started
    dl = lw._verdict(lw.demo("pitdeadline"))
    import lollive as ll
    want_by = lw._mmss(lw.demo("pitdeadline")["gt"] + 68 - ll.ALERT_LEAD)
    if want_by not in dl["line"]:
        return FAIL, f"the deadline isn't spawn minus lollive's own lead ({want_by})"
    for k in ("pit", "pitup"):                       # inside the fight there is no deadline
        if want_by in (lw._verdict(lw.demo(k)) or {})["line"]:
            return FAIL, f"{k} printed a deadline that has already passed"
    # the LEDGER, and its absence when there is nothing to report
    placed_copy = i18n.tf("{placed} of {bought} placed", placed=1, bought=2)
    if placed_copy not in lw._verdict(lw.demo("pink"))["sub"]:
        return FAIL, "the PINK card lost the buy/place ledger"
    share_copy = i18n.tf("control ward on you {percent}% of the game", percent=42)
    if share_copy not in lw._verdict(lw.demo("dark"))["sub"]:
        return FAIL, "the share-of-game control-ward number is gone"
    if "%" in lw._verdict(lw.demo("noledger"))["sub"]:
        return FAIL, "a percentage was printed before there was a sample for one"
    for pct, lo, hi in ((-1.0, 0, 0), (5.0, 100, 100)):       # never out of range, ever
        d = dict(lw.demo("pink"), have_pct=pct)
        if not lo <= lw._verdict(d)["have_pct"] <= hi:
            return FAIL, f"have_pct {pct} escaped 0-100"
    # the buy prompt: only in a recall window, only if affordable, never while carrying
    buy_copy = i18n.tf("+{gold}g control ward", gold=lw.CTRL_GOLD)
    if buy_copy not in lw._verdict(lw.demo("base"))["row"]:
        return FAIL, "a recall window is the one moment the buy must lead the row"
    for k in ("basebroke", "basecarrying", "row"):
        if buy_copy in lw._verdict(lw.demo(k))["row"]:
            return FAIL, f"{k} was sold a control ward it doesn't need or can't afford"

    # --- and the purchase ledger against the truth, over a whole game: two bought, one
    #     placed, and the share-of-game number inside the possible.
    lg, frames = game(lambda t: 0.03 * t,
                      pinks=lambda t: 1 if (200 <= t < 500 or t >= 900) else 0)
    if (lg.bought, lg.placed) != (2, 1):
        return FAIL, f"the pink ledger says {lg.bought} bought / {lg.placed} placed, want 2/1"
    pcts = [c["have_pct"] for _t, c in frames if c and c.get("have_pct") is not None]
    if not pcts or min(pcts) < 0 or max(pcts) > 100:
        return FAIL, f"share-of-game out of range: {min(pcts or [0])}..{max(pcts or [0])}"
    if pcts[-1] > 60:                       # carried for 600 of 1500s -> can't read as most
        return FAIL, f"share-of-game reads {pcts[-1]}% for a ward carried 40% of the game"
    if any(c["have_pct"] is not None for t, c in frames if c and t < 60):
        return FAIL, "a percentage was printed in the first minute of watching"

    # --- the legend must actually CONTAIN the section: PIL draws past a canvas silently, so
    #     an overrun vanishes off the bottom of the card instead of raising.
    return OK, ("24 fixtures, arming tripwire, dead-time freeze, trinket + deadline + pink "
                "ledger + 6 simulated games hold")


def c_out():
    """THE OUT (core/lolout) — the losing game. This is the highest-consequence verdict in
    the whole app: CALL IT tells a player their game is over, and a CALL IT on a winnable
    game is the single worst thing Smiteless could ever put on screen. So the guards here
    are mostly about what it must NOT do — plus the structural promise that it and the
    CLOSER are one read of the same map and can never both be talking."""
    import lolout as lo, lolclose as lc, lollive as ll
    import random

    # --- 1. every branch is reachable and lands where it should
    want = {"baron": "OUT", "baron_lost": "SURVIVE", "elder": "OUT", "soul": "OUT",
            "ace": "OUT", "scale": "OUT", "structure": "OUT", "survive": "SURVIVE",
            "survive_vote": "SURVIVE", "call": "CALL IT", "call_nexus": "CALL IT",
            "call_blocked": "OUT", "call_early": "SURVIVE", "call_thin": "SURVIVE",
            "clawback": "OUT", "ahead": None, "even": None, "early": None, "tempo": "OUT"}
    if set(want) != set(lo.DEMOS):
        return FAIL, f"fixture list drifted: {sorted(set(want) ^ set(lo.DEMOS))}"
    cards = {k: lo._verdict(lo.demo(k)) for k in want}
    bad = [f"{k}: got {(cards[k] or {}).get('verdict')}, want {want[k]}"
           for k in want if (cards[k] or {}).get("verdict") != want[k]]
    if bad:
        return FAIL, "; ".join(bad)

    # --- 2. ONE MAP: the bar it calls "behind" is the bar the CLOSER calls "ahead", and the
    #        two can never speak on the same frame. Two coaches arguing about one game is
    #        the failure this whole mirror design exists to make impossible.
    if lo.BEHIND_MIN != lc.LEAD_MIN:
        return FAIL, f"behind bar {lo.BEHIND_MIN} != the CLOSER's lead bar {lc.LEAD_MIN}"
    rnd = random.Random(90071)
    for _ in range(4000):
        gt = rnd.uniform(0.0, 45 * 60.0)
        lead = rnd.uniform(-15000.0, 15000.0)
        oc = lo.demo("structure"); oc.update(gt=gt, lead=lead, trough=lead)
        cc = lc.demo("bank"); cc.update(gt=gt, lead=lead, peak=lead)
        if lo._verdict(oc) is not None and lc._verdict(cc) is not None:
            return FAIL, f"both guards speak at {gt:.0f}s / {lead:+.0f}g"
    for lead in (-1999.0, -500.0, 0.0, 8000.0):          # inside the bar = not behind, ever
        c = lo.demo("call"); c.update(lead=lead, trough=lead)
        if lo._verdict(c) is not None:
            return FAIL, f"speaks at {lead:+.0f}g, which is not behind"

    # --- 3. CALL IT is the one that has to be hard. Fuzz the whole state space and assert
    #        the four preconditions hold on EVERY firing, and that it stays rare.
    calls = total = 0
    for _ in range(6000):
        ctx = {"gt": rnd.uniform(0.0, 45 * 60.0), "lead": rnd.uniform(-16000.0, 4000.0),
               "e": rnd.uniform(-9000.0, 4000.0), "bodies": rnd.choice([-2.0, -1.0, 0.0, 1.0]),
               "our_open_inhibs": rnd.choice([[], [("C", 120.0)], [("C", 90.0), ("L", 200.0)]]),
               "nexus_turret": rnd.random() < 0.15, "their_deepest": rnd.randint(0, 3),
               "baron_secs": rnd.choice([None, -5.0, 30.0, 200.0]),
               "drake_secs": rnd.choice([None, 10.0, 80.0, 240.0]),
               "elder": rnd.random() < 0.2, "my_drakes": rnd.randint(0, 4),
               "their_death_cost": rnd.uniform(20.0, 60.0),
               "scale_gap": rnd.uniform(-0.8, 0.8), "my_items": rnd.randint(0, 6),
               "dead_enemies": rnd.randint(0, 5), "role": rnd.choice(list(lo._HOLD)),
               "tempo_urgent": rnd.random() < 0.3, "vote_now": rnd.random() < 0.3}
        ctx["trough"] = min(ctx["lead"], ctx["lead"] - rnd.uniform(0.0, 6000.0))
        card = lo._verdict(ctx)
        if card is None:
            continue
        total += 1
        # the row is ONE line in the widget and must never carry a wrapped sentence
        row = " · ".join(lo.row_bits(card))
        if len(row) > 64 or "—" in row:
            return FAIL, f"quiet row is not a row: {row!r}"
        if not card.get("line") or not card.get("sub"):
            return FAIL, f"a {card['verdict']} card with no instruction on it"
        if card["verdict"] != "CALL IT":
            continue
        calls += 1
        if ctx["gt"] < lo.CALL_FROM:
            return FAIL, f"CALL IT at {ctx['gt']:.0f}s — before the 20:00 bar"
        if ctx["lead"] > -lo.CALL_GOLD:
            return FAIL, f"CALL IT at {ctx['lead']:+.0f}g — above the write-off deficit"
        if not (ctx["our_open_inhibs"] or ctx["nexus_turret"]):
            return FAIL, "CALL IT while nothing of yours is even open"
        if lo._immediate(ctx) is not None:
            return FAIL, "CALL IT while a live objective out is on the board"
        if card.get("quiet"):
            return FAIL, "CALL IT hid itself in a quiet row"
    if not total or not calls:
        return FAIL, "the fuzz never reached a verdict / a write-off — the bars are wrong"

    # --- 3b. THE NUMBER THAT MATTERS: how often a write-off is WRONG. The fuzz above says
    #         the four facts always hold; it cannot say whether a game with those four facts
    #         still comes back. So: simulate whole games as a gold random walk with a
    #         per-game drift (some teams recover, most don't), let structures fall out of a
    #         sustained deficit the way they actually do, and count the CALL ITs that were
    #         later contradicted by the game returning to even. A change that loosens the
    #         bars shows up here as a jump in retractions, which is the only way this
    #         verdict can rot without anybody noticing.
    fired = retracted = games = 0
    for g in range(600):
        drift, lead, deep, inhib_at = rnd.gauss(-70.0, 110.0), 0.0, 0, None
        walk, said = [], []
        for t in range(90):                      # 45 minutes at one tick every 30s
            lead += drift + rnd.gauss(0.0, 430.0)
            walk.append(lead)
            if lead <= -3000.0 and deep < 3 and rnd.random() < 0.15:
                deep += 1
            if deep >= 3 and lead <= -6000.0 and inhib_at is None and rnd.random() < 0.20:
                inhib_at = t
            open_inhib = ([("C", 300.0 - (t - inhib_at) * 30.0)]
                          if inhib_at is not None and t - inhib_at < 10 else [])
            v = lo._verdict({
                "gt": 30.0 * t, "lead": lead, "trough": min(walk), "their_deepest": deep,
                "e": lead * 0.55 + rnd.gauss(0.0, 800.0), "bodies": 0.0,
                "our_open_inhibs": open_inhib, "nexus_turret": False,
                "baron_secs": (30.0 if (t > 40 and rnd.random() < 0.12) else None),
                "drake_secs": None, "elder": False, "my_drakes": 0,
                "their_death_cost": 25.0 + t * 0.35, "scale_gap": 0.0, "my_items": 0,
                "dead_enemies": 0, "role": "mid", "tempo_urgent": False, "vote_now": False})
            if v and v.get("verdict") == "CALL IT":
                said.append(t)
        games += 1
        if said:
            fired += 1
            # "came back" = the same bar the app itself uses to stop calling you behind
            if max(walk[said[0] + 1:] or [walk[-1]]) >= -lo.BEHIND_MIN:
                retracted += 1
    if not fired:
        return FAIL, "600 simulated games and the write-off never fired — it is unreachable"
    if fired / float(games) > 0.45:
        return FAIL, (f"the write-off fires in {fired / games:.0%} of simulated games — it is "
                      f"supposed to be the rare call, not the default one")
    wrong = retracted / float(fired)
    if wrong > 0.05:
        return FAIL, (f"{wrong:.0%} of write-offs were contradicted by the game coming back "
                      f"— the bars are too loose to tell a player their game is over")

    # --- 4. the promises the copy makes. A write-off always shows the deficit that justified
    #        it; an OUT always names something; nothing ever claims a comeback it can't show.
    call = cards["call"]
    if "-9.2k" not in call["sub"] or not any(word in call["sub"] for word in ("inhib", "inib")):
        return FAIL, f"the write-off doesn't show its receipt: {call['sub']}"
    for k in ("baron", "elder", "soul", "ace", "scale", "structure"):
        if not (cards[k].get("tag") or "").strip():
            return FAIL, f"the {k} out has no row tag"
    for k, c in cards.items():
        if c and c.get("won_txt") and c["won"] < lo.WON_MIN:
            return FAIL, f"{k} claims a comeback under the {lo.WON_MIN:.0f}g bar"
    if cards["clawback"].get("evidence") is None or cards["structure"].get("evidence"):
        return FAIL, "the clawed-back receipt is attached to the wrong cards"

    # --- 5. ONE BRAIN with champ select: the same power-curve table and the same bar grade
    #        the comps in the lobby ("YOU OUTSCALE") and in game ("time is on your side").
    if lo._scale_gap() != ll.SCALE_GAP:
        return FAIL, "THE OUT's scaling bar has drifted from lollive.SCALE_GAP"
    try:
        import smitecard as sc
        if sc._SCALE_W is not ll.SCALE_W:
            return FAIL, "champ select grades scaling off a second, private curve table"
    except Exception:
        pass                                 # no Pillow here: the table check is enough
    if ll.comp_scale({}, [{"championName": "NotAChampion"}]) is not None:
        return FAIL, "comp_scale invents a curve for champions it cannot resolve"
    if ll.team_lead([], [], 600.0) != 0.0:
        return FAIL, "an empty team is not an even game"
    a = [{"scores": {"creepScore": 90, "kills": 3}}]
    b = [{"scores": {"creepScore": 40}}]
    if abs(ll.team_lead(a, b, 900.0) + ll.team_lead(b, a, 900.0)) > 1e-6:
        return FAIL, "the team lead is not symmetric — one side is being read differently"

    # --- 6. junk in the context can't crash the board or fake a verdict
    for junk in ({}, {"gt": None, "lead": None}, {"gt": "x"}, {"gt": 1500.0, "lead": -5000.0,
                 "our_open_inhibs": None, "their_deepest": None, "scale_gap": None,
                 "my_items": None, "role": "not-a-role", "baron_secs": None}):
        try:
            lo._verdict(junk)
        except (TypeError, ValueError):
            if junk.get("gt") == "x":
                continue                     # a non-numeric clock is the caller's bug
            return FAIL, f"a junk context crashed the board: {junk}"
    g = lo.Guard()                           # no data must not arm anything
    if g.observe(None, None) is not None or g.trough != 0.0:
        return FAIL, "guard armed itself with no game data"

    # --- 7. END TO END, off a real-shaped :2999 payload. Everything above tests the math;
    #        this tests the WIRING, which is where the bug actually was — the first cut read
    #        the ENEMY's fallen turrets for "how deep are they into you", so a team whose own
    #        base was already open got told nothing of theirs was. No fixture can catch that.
    def _p(i, team, champ, cs, pos=""):
        return {"riotId": f"P{i}#NA1", "summonerName": f"P{i}", "team": team, "level": 13,
                "championName": champ, "isDead": False, "respawnTimer": 0, "position": pos,
                "items": [], "scores": {"creepScore": cs, "kills": 2, "deaths": 3,
                                        "assists": 3, "wardScore": 10.0}}

    def _payload(gt, events):
        allies = [_p(i, "ORDER", c, 90, "MIDDLE" if i == 1 else "") for i, c in
                  enumerate(["Aatrox", "Elise", "Ahri", "Jinx", "Thresh"], 1)]
        enemies = [_p(i, "CHAOS", c, 190) for i, c in
                   enumerate(["Darius", "Nidalee", "Syndra", "Caitlyn", "Nautilus"], 6)]
        return {"activePlayer": {"riotId": "P1#NA1", "championStats": {"moveSpeed": 380}},
                "allPlayers": allies + enemies, "gameData": {"gameTime": gt},
                "events": {"Events": [e for e in events if e["EventTime"] <= gt]}}

    dd = {"name2id": {"aatrox": 266, "jinx": 222, "darius": 122, "caitlyn": 51},
          "norm": lambda s: (s or "").lower().replace(" ", ""), "id2name": {}, "item_data": {},
          "id2tags": {266: ["Fighter"], 222: ["Marksman"], 122: ["Fighter"], 51: ["Marksman"]}}
    # ORDER (us) loses all three mid turrets, then the inhibitor behind them
    evs = [{"EventName": "TurretKilled", "EventTime": 600.0 + i,
            "TurretKilled": f"Turret_T1_C_{5 - i:02d}_A"} for i in range(3)]
    evs.append({"EventName": "InhibKilled", "EventTime": 1250.0, "InhibKilled": "Barracks_T1_C1"})
    gd = lo.Guard()
    seen = {}
    for gt in (600.0, 900.0, 1000.0, 1300.0):
        c = gd.observe(dd, _payload(gt, evs))
        seen[gt] = None if not c else c["verdict"]
        if c and "nothing of yours is open" in c.get("line", ""):
            return FAIL, f"at {gt:.0f}s it read OUR fallen turrets as theirs — base is open"
    if seen[600.0] is not None:
        return FAIL, "it spoke before 15:00 off a live payload"
    if seen[900.0] != "SURVIVE" or seen[1000.0] != "SURVIVE":
        return FAIL, f"live payload before the inhibitor fell: {seen}"
    if seen[1300.0] != "CALL IT":
        return FAIL, f"20:00+, 10k down, mid inhibitor open -> {seen[1300.0]}, not CALL IT"
    if gd.trough > -9000.0:
        return FAIL, f"the trough never tracked the deficit: {gd.trough:.0f}"
    dead = _payload(1300.0, evs)
    dead["allPlayers"][0]["isDead"] = True
    if gd.observe(dd, dead) is not None:
        return FAIL, "the widget guard talked over the death screen"
    if (lo.read(dd, dead, while_dead=True) or {}).get("verdict") != "CALL IT":
        return FAIL, "the death brief's own read went silent exactly when it is needed"

    # --- 8. the legend is drawn into a fixed canvas that is then cropped to its own last
    #        line, so a new section that overruns it vanishes off the bottom instead of
    #        raising. THE OUT is now the last section — check its rows actually landed.
    try:
        import smitewidget as sw_
        leg = sw_._render_legend()
        band = leg.crop((0, leg.height - 30, leg.width, leg.height - 4))
        if not any(sum(px) > 150 for px in list(band.getdata())):
            return FAIL, "the legend's last THE OUT row fell off the bottom of its canvas"
    except Exception:
        pass                                 # not on Windows / no Win32: skip the render
    return OK, (f"19 fixtures + 10k fuzzed states + 600 simulated games + a live payload "
                f"end to end: {wrong:.0%} of write-offs come back, mirrors the CLOSER exactly")


def c_onefix():
    """THE ONE FIX (core/lolfix) — the leak board that prices your habits in your own LP and
    names the single one to work on. Two risks, neither visible without weeks of real games:
    the pricing could assert a number off a sample that can't carry it (the app's whole
    credibility rests on the opposite), and the ledger it reads from is written by a merge
    that has to stay idempotent and in time order or the splits quietly rot."""
    import json
    import tempfile
    import lolfix as lf
    import lolprofile as lp
    lf.selftest()                                # 12 invariants, every render state

    # The board and the review page must name the leaks identically — one catalogue.
    if {t: m["label"] for t, m in lf.LEAKS.items()} != lp._BEHAVIOR_TAGS:
        return FAIL, "the leak catalogue and the review page's tag labels have diverged"
    # ... and every leak's live guard must be a surface that actually ships.
    have = {"THE GOLD CLOCK": "lolgold", "BLEED": "lolbleed", "RE-ENTRY": "lolreentry",
            "THE CLOSER": "lolclose", "THE WARD CLOCK": "lolward"}
    for t, m in lf.LEAKS.items():
        if m["guard"] not in have:
            return FAIL, f"{t} points at '{m['guard']}', which is not a shipped guard"
        __import__(have[m["guard"]])
    # ... and the tags it prices are exactly the ones behavior_read can emit.
    src = open(os.path.join(_ROOT, "core", "lolprofile.py"), encoding="utf-8").read()
    body = src.split("def behavior_read", 1)[-1].split("\ndef ", 1)[0]
    emitted = {t for t in lf.LEAKS if f'"{t}"' in body}
    if emitted != set(lf.LEAKS):
        return FAIL, f"behavior_read never emits {sorted(set(lf.LEAKS) - emitted)}"

    # The ledger writer, against a temp file: out-of-order backfill, re-recording, and cap.
    real = lp._BEHAVIOR_FILE
    tmp = os.path.join(tempfile.mkdtemp(), "ledger.json")
    try:
        lp._BEHAVIOR_FILE = tmp
        rows = [{"mid": f"M{i}", "ts": i * 1000, "hits": [], "ev": ["early_bleeding"],
                 "win": True} for i in range(6)]
        lp._ledger_put(list(reversed(rows[3:])))        # backfill arrives NEWEST-first
        lp._ledger_put(rows[:3])
        got = [g["mid"] for g in json.load(open(tmp, encoding="utf-8"))["games"]]
        if got != [r["mid"] for r in rows]:
            return FAIL, f"ledger not in time order after an out-of-order backfill: {got}"
        lp._ledger_put([{"mid": "M2", "ts": 2000, "hits": ["early_bleeding"],
                         "ev": ["early_bleeding"], "win": False}])
        led = json.load(open(tmp, encoding="utf-8"))["games"]
        if len(led) != 6 or led[2]["hits"] != []:
            return FAIL, "re-recording a game must be a no-op, not a second row"
        lp._ledger_put([{"mid": f"B{i}", "ts": 10_000 + i, "hits": [], "ev": [], "win": True}
                        for i in range(lp.LEDGER_KEEP + 40)])
        led = json.load(open(tmp, encoding="utf-8"))["games"]
        if len(led) != lp.LEDGER_KEEP or led != sorted(led, key=lambda g: g["ts"]):
            return FAIL, f"ledger cap/order broke at {len(led)} rows"
    finally:
        lp._BEHAVIOR_FILE = real

    # A priced pick must survive being read through the profile's own board entry point.
    b = lf.board(lf.demo("priced"), lp=(20, 20, True))
    if not b["pick"] or b["pick"]["state"] != "priced" or not lf.commitment(b):
        return FAIL, "the priced fixture lost its pick through the public board()"
    if lf.board(lf.demo("thin"))["pick"] is not None:
        return FAIL, "a board under the sample bar must never name a fix"
    return OK, ("12 board guards, catalogue matches the review page + five live guards, "
                "ledger merge is idempotent and time-ordered")


def c_pool():
    """THE POOL (core/lolpool) — your champion pool priced in your own LP. The risk here is
    specific and it is the one every "your best champion" stat in existence gets wrong: with
    six or nine champions on the page, testing each one against your own baseline finds a
    "proven" winner in pools that are pure noise. If that correction ever comes off, this
    surface starts confidently telling people to abandon champions at random — so the guard
    suite MEASURES the false-positive rate rather than trusting the arithmetic. The second risk
    is divergence: the profile page and the champ-select recommender now share this read, and
    they must never disagree about a champion again."""
    import lolpool as lpl
    import lolfit as fit
    import lolprofile as lp
    lpl.selftest()                     # 15 guard groups + a 1,200-pool fuzz

    # ONE BRAIN: lolfit's veto IS lolpool's 'bench'. Checked in both directions on a record
    # shaped like the real cache, because a one-way check would miss the recommender vetoing
    # something the page calls fine (the exact bug this refactor exists to make impossible).
    rec = {"baseline": 80, "recent": ["sett"],
           "champs": {"sett": {"g": 24, "w": 14, "avg": 84}, "ornn": {"g": 16, "w": 9, "avg": 80},
                      "darius": {"g": 14, "w": 2, "avg": 58}, "garen": {"g": 9, "w": 5, "avg": 74},
                      "gwen": {"g": 3, "w": 0, "avg": 55}}}
    bd = fit.pool_board(rec)
    if not bd:
        return FAIL, "lolfit could not build a pool board from a normal-looking record"
    for name in rec["champs"]:
        benched = lpl.champ_note(bd, name)[0] == "bench"
        vetoed = fit.verdict(rec, name)[0] == "veto"
        if benched != vetoed:
            return FAIL, (f"{name}: the page says bench={benched} and the recommender says "
                          f"veto={vetoed} — the two reads have diverged again")
    if fit.verdict(rec, "darius")[0] != "veto":
        return FAIL, "a 2W-12L champion must still be vetoed out of the recommendations"
    if fit.verdict(rec, "gwen")[0] == "veto":
        return FAIL, "0-3 is not a sample and must never veto a champion"
    # ... and a MAIN is never vetoed, however bad the run. This is the old pool coach's one
    # good idea and the recommender must inherit it, not just the profile page.
    slumping = {"champs": {"sett": {"g": 30, "w": 7, "avg": 62},
                           "ornn": {"g": 14, "w": 9, "avg": 84}}, "baseline": 78, "recent": []}
    if fit.verdict(slumping, "sett")[0] == "veto":
        return FAIL, "the recommender vetoed the account's main on a bad run"
    if lpl.champ_note(fit.pool_board(slumping), "sett")[0] != "slump":
        return FAIL, "a main on a bad run must read as a slump, not a verdict"

    # The profile's entry point must produce a board off the FULL champion list. Handing it the
    # six champions the page draws would delete the tail the width claim is about.
    champs = [dict(c, wr=round(c["w"] / c["g"] * 100)) for c in lpl.demo("spread")]
    b = lp.pool_board(champs)
    if not b or not b.get("ready"):
        return FAIL, "lolprofile.pool_board did not produce a ready board from a real pool"
    if (b["width"] or {}).get("state") != "priced":
        return FAIL, f"the spread pool lost its width claim through lolprofile: {b['width']}"
    if b["pool_n"] != len(champs):
        return FAIL, f"the board saw {b['pool_n']} of {len(champs)} champions — the tail was cut"
    if len(lp.pool_board(champs[:3])["rows"]) != 3:
        return FAIL, "a truncated pool must still build, just with less to say"
    # Junk and empties can reach this from a half-written cache; none of it may raise.
    for junk in (None, [], [{}], {"sett": None}, [{"champ": "Sett", "g": 0, "w": 0}]):
        if lp.pool_board(junk) is None:
            return FAIL, f"lolprofile.pool_board raised on {junk!r} instead of saying nothing"

    # Every surface that draws this must be able to import it, and the renderer must reach the
    # board through the key lolprofile actually writes.
    import smitecard as sc
    src = open(os.path.join(_ROOT, "core", "lolprofile.py"), encoding="utf-8").read()
    if '"pool":' not in src or "def pool_board" not in src:
        return FAIL, "lolprofile no longer writes the 'pool' key the profile card reads"
    # ... and it must stay self-profile only: pricing another player's champions in YOUR LP,
    # against YOUR baseline, is a number about nobody.
    if 'None if other else pool_board' not in src:
        return FAIL, "THE POOL is being built for other players' profiles too"
    if "def _coach(" in src:
        return FAIL, "the superseded pool coach is back — two brains for one champion again"
    csrc = open(os.path.join(_ROOT, "core", "smitecard.py"), encoding="utf-8").read()
    if 'p.get("coach")' in csrc:
        return FAIL, "the profile card still draws the removed coach"
    for fn in ("headline", "notes", "width_note", "row_note", "champ_note", "short_note"):
        if not callable(getattr(lpl, fn, None)):
            return FAIL, f"lolpool.{fn} is missing — a surface will crash drawing the board"
    if not sc._profile_headline({"pool": b, "champs": [], "n": 57, "wr": 50, "session": {}}):
        return FAIL, "the profile headline went empty with a priced pool board"
    if "THE POOL" not in sc._profile_headline({"pool": b, "champs": [], "n": 57, "wr": 50,
                                               "session": {}}):
        return FAIL, "a priced pool board did not reach the profile headline"

    # The champ-select note is drawn on ONE unwrapped line. It must be ellipsized to fit rather
    # than clipped mid-word — the bug this feature surfaced, which the team scout's roster line
    # had been quietly hitting for releases.
    from PIL import Image, ImageDraw
    dm = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    fnt = sc.font(9)
    for txt in ("⚠ Darius: -93 LP / 10 on it (2W-12L)", "team: " + "  ".join(["Sett A·12"] * 4),
                "short", "", "x" * 400):
        for w in (40, 90, 148, 340):
            cut = sc._ellipsize(dm, txt, fnt, w)
            if dm.textlength(cut, font=fnt) > w:
                return FAIL, f"_ellipsize returned {cut!r}, still wider than {w}px"
            if txt and cut and cut != txt and not cut.endswith("…"):
                return FAIL, f"_ellipsize cut {txt!r} to {cut!r} without saying so"
    if sc._ellipsize(dm, "fits", fnt, 4000) != "fits":
        return FAIL, "_ellipsize must leave a string that already fits completely alone"
    # ... and the strip must read in priority order, not reversed by the right-anchored draw.
    kinds = [k for k, _t in lpl.notes(b)]
    if kinds and kinds[0] not in ("queue", "bench", "spread", "slump", "quiet"):
        return FAIL, f"the session strip led with an unknown note kind: {kinds}"
    return OK, ("15 guard groups + 1,200-pool fuzz; false positives measured, not assumed; "
                "page and recommender share one read")


def c_frozen():
    """Every core/ and ui/ module must be in dist\\build.ps1's $hidden list. PyInstaller only
    follows STATIC imports, and this app is full of deliberate lazy ones (`import lolfit` inside
    a function, so champ select doesn't pay for it at startup). A module it misses ships an exe
    that raises ImportError the first time the feature is used — i.e. a release named after a
    feature that isn't in it. CLAUDE.md has carried this rule as a reminder for releases; this
    makes it a tripwire instead of a habit."""
    import re
    ps1 = os.path.join(_ROOT, "dist", "build.ps1")
    src = open(ps1, encoding="utf-8").read()
    if "$hidden = @(" not in src:
        return FAIL, "build.ps1 no longer declares a $hidden list — this guard has gone blind"
    # Paren-depth scan with comments stripped. Splitting on the first ")" would stop inside a
    # trailing comment — "# ...off the client (LCU)" ends a line with one — and a guard that
    # reads half the list is worse than no guard, because it fails on modules that ARE there.
    rest, blk, depth = src.split("$hidden = @(", 1)[1], [], 1
    for line in rest.splitlines():
        code = line.split("#", 1)[0]
        depth += code.count("(") - code.count(")")
        blk.append(code)
        if depth <= 0:
            break
    hidden = set(re.findall(r'"([^"]+)"', "\n".join(blk)))
    if len(hidden) < 30:
        return FAIL, f"only parsed {len(hidden)} entries out of $hidden — the guard is blind"
    mods = {f[:-3] for d in ("core", "ui")
            for f in os.listdir(os.path.join(_ROOT, d))
            if f.endswith(".py") and not f.startswith("_")}
    missing = sorted(mods - hidden)
    if missing:
        return FAIL, (f"not in build.ps1 $hidden: {', '.join(missing)} — the frozen exe can "
                      f"crash on import")
    stale = sorted(h for h in hidden
                   if h.startswith(("lol", "smite")) and h not in mods
                   and not os.path.exists(os.path.join(_ROOT, "tools", f"{h}.py")))
    if stale:
        return FAIL, f"build.ps1 $hidden names modules that no longer exist: {', '.join(stale)}"
    return OK, f"all {len(mods)} core/ + ui/ modules are frozen into the build"


def c_mute():
    """AUTO-MUTE. It used to TYPE `/fullmute all` into the game and could never tell whether
    that landed - so it claimed success for four releases while muting nobody. It now writes
    the client's own settings, which means the state is READABLE, and this check reads it.
    A key Riot renames must fail here rather than silently do nothing."""
    import lolmute as lm, lolgame as lg
    from unittest import mock

    # Run deterministic layout contracts BEFORE any machine/League checks. A developer's
    # current HKL must never hide a broken AltGr chord, mutex, timing gate or LCU layer.
    bad = []
    hkl = 0x0416
    layout_calls = []
    window_hkl = lm._game_keyboard_layout(
        123,
        get_window_thread=lambda hwnd, _pid: layout_calls.append(("thread", hwnd)) or 77,
        get_keyboard_layout=lambda thread_id:
            layout_calls.append(("layout", thread_id)) or hkl,
    )
    if window_hkl != hkl or layout_calls != [("thread", 123), ("layout", 77)]:
        bad.append("League window thread HKL")

    support_scans = {
        lm.VK_RETURN: 0x1C, lm.VK_ESCAPE: 0x01, lm.VK_SHIFT: 0x2A,
        lm.VK_CONTROL: 0x1D, lm.VK_MENU: 0x38,
    }

    def mapped(vk, _kind, _hkl):
        return support_scans.get(vk, {0x51: 0x10, 0xBF: 0x35}.get(vk, vk & 0x7F))

    direct, problem = lm.resolve_chord(
        "/", hkl, vk_key_scan=lambda _ch, _hkl: 0xBF, map_virtual=mapped)
    if problem or direct.scan != 0x35 or direct.modifiers:
        bad.append("direct slash layout")

    altgr, problem = lm.resolve_chord(
        "/", hkl, vk_key_scan=lambda _ch, _hkl: (0x06 << 8) | 0x51,
        map_virtual=mapped)
    if problem or altgr.scan != 0x10 \
            or altgr.modifiers != (lm.MOD_CONTROL | lm.MOD_ALT):
        bad.append("PT-BR Ctrl+Alt+Q slash")

    shifted, problem = lm.resolve_chord(
        "A", hkl, vk_key_scan=lambda _ch, _hkl: (0x01 << 8) | 0x41,
        map_virtual=mapped)
    if problem or shifted.modifiers != lm.MOD_SHIFT:
        bad.append("Shift character")

    failure_cases = (
        ("VkKeyScanExW -1", lambda _ch, _hkl: -1, mapped),
        ("zero scan", lambda _ch, _hkl: 0x41, lambda *_args: 0),
        ("unknown modifiers", lambda _ch, _hkl: (0x08 << 8) | 0x41, mapped),
    )
    for name, vk_scan, map_scan in failure_cases:
        chord, problem = lm.resolve_chord("x", hkl, vk_key_scan=vk_scan,
                                          map_virtual=map_scan)
        if chord is not None or problem is None:
            bad.append(name)

    events = []
    lm._emit_chord(
        lm.KeyChord("/", 0x51, 0x10, lm.MOD_CONTROL | lm.MOD_ALT),
        ((lm.MOD_SHIFT, 0x2A), (lm.MOD_CONTROL, 0x1D), (lm.MOD_ALT, 0x38)),
        key_fn=lambda scan, down: events.append((scan, down)), hold=0)
    expected = [(0x1D, True), (0x38, True), (0x10, True), (0x10, False),
                (0x38, False), (0x1D, False)]
    if events != expected:
        bad.append(f"AltGr chord order {events!r}")

    cleanup = []

    def failing_key(scan, down):
        cleanup.append((scan, down))
        if scan == 0x10 and down:
            raise RuntimeError("fixture")

    try:
        lm._emit_chord(
            lm.KeyChord("/", 0x51, 0x10, lm.MOD_CONTROL | lm.MOD_ALT),
            ((lm.MOD_SHIFT, 0x2A), (lm.MOD_CONTROL, 0x1D), (lm.MOD_ALT, 0x38)),
            key_fn=failing_key, hold=0)
    except RuntimeError:
        pass
    if cleanup[-2:] != [(0x38, False), (0x1D, False)]:
        bad.append("modifier cleanup after exception")

    problem = lm.LayoutProblem(hkl, "/", 0x51, 0x06, 0, "fixture incompatible")
    with mock.patch.object(lm, "_validated_game_window", return_value=123), \
            mock.patch.object(lm, "_game_keyboard_layout", return_value=hkl), \
            mock.patch.object(lm, "_resolve_command", return_value=(None, problem)), \
            mock.patch.object(lm, "_key") as key_mock:
        result = lm.send_fullmute()
    if result.status != lm.SEND_LAYOUT_INCOMPATIBLE or key_mock.called:
        bad.append("pre-resolution emitted input on failure")

    if lm._typed_layer_remains_armed(lm.SendResult(lm.SEND_LAYOUT_INCOMPATIBLE)) \
            or not lm._typed_layer_remains_armed(lm.SendResult(lm.SEND_TRANSIENT)) \
            or lm._typed_layer_remains_armed(lm.SendResult(lm.SEND_OK)):
        bad.append("typed-layer disarm classification")

    # Exercise main's session state: structural incompatibility applies LCU first and sends
    # once; a transient focus/idle/input failure remains armed and retries in the safe window.
    with mock.patch.object(lm.cfg, "load", return_value={"auto_mute": True}), \
            mock.patch.object(lm, "_single_instance", return_value=True), \
            mock.patch.object(lm, "apply", return_value=(True, "fixture")) as apply_mock, \
            mock.patch.object(lm.cfg, "tray_gone", side_effect=[False, True]), \
            mock.patch.object(lm, "game_time", return_value=4.0), \
            mock.patch.object(lm, "send_fullmute",
                              return_value=lm.SendResult(
                                  lm.SEND_LAYOUT_INCOMPATIBLE, "fixture")) as send_mock, \
            mock.patch.object(lm.time, "monotonic", return_value=0.0), \
            mock.patch.object(lm.time, "sleep"):
        lm.main()
    if apply_mock.call_count != 1 or send_mock.call_count != 1:
        bad.append("incompatible session did not preserve LCU/disarm typing")

    with mock.patch.object(lm.cfg, "load", return_value={"auto_mute": True}), \
            mock.patch.object(lm, "_single_instance", return_value=True), \
            mock.patch.object(lm, "apply", return_value=(True, "fixture")), \
            mock.patch.object(lm.cfg, "tray_gone", side_effect=[False, False, True]), \
            mock.patch.object(lm, "game_time", side_effect=[4.0, 5.0]), \
            mock.patch.object(lm, "send_fullmute",
                              return_value=lm.SendResult(lm.SEND_TRANSIENT, "focus")) \
                    as send_mock, \
            mock.patch.object(lm.time, "monotonic", return_value=0.0), \
            mock.patch.object(lm.time, "sleep"):
        lm.main()
    if send_mock.call_count != 2:
        bad.append("transient failure disarmed typed layer")

    if bad:
        return FAIL, "; ".join(bad)

    if lm.FIRE_AT < 3.0:
        return FAIL, f"firing at gameTime {lm.FIRE_AT}s - too early, the client eats the keys"
    # SAFETY, not tuning. Typing is only safe while you're parked in the fountain: clicking to
    # move takes focus off League's chat box, and a character that misses it becomes a keybind
    # ('f' in "fullmute" = Flash). v0.9.56's 25s "confirming" resend cast Flash mid-walk. There
    # must be exactly one attempt, and it must stop before you're out on the map.
    if hasattr(lm, "CONFIRM_AT"):
        return FAIL, "a second mute attempt is back - it types while you're moving and casts Flash"
    if getattr(lm, "LATE_LIMIT", 999) > 30.0:
        return FAIL, f"still typing at gameTime {lm.LATE_LIMIT}s - you're on the map by then"
    # THE bug that broke it in a real game: the v0.9.55 rewrite dropped the single-instance
    # mutex, the tray re-spawns on any phase flap, and THREE copies typed into one chat box in
    # the same second. Interleaved character by character that is garbage, not a command - and
    # the log said TYPED three times, so it looked like success. Never again.
    if not hasattr(lm, "_single_instance"):
        return FAIL, "no single-instance guard - concurrent copies will interleave into garbage"
    # Prove the SEMANTICS on a throwaway mutex. Grabbing the real one would make this check
    # fail exactly when auto-mute is running properly, which is the wrong way round.
    probe = "Global\\SmitelessSelftestProbe"
    if not lm._single_instance(probe) or lm._single_instance(probe):
        return FAIL, "the single-instance guard doesn't actually exclude a second copy"
    if not hasattr(lm, "_SEND_LOCK"):
        return FAIL, "no in-process send lock - two threads could interleave the command"
    if not hasattr(lm, "player_dead"):
        return FAIL, "no death-window retry - a missed fountain attempt would never recover"
    # The real machine is diagnostic only: incompatible layouts are a supported, safely
    # disarmed state, while the deterministic matrix above proves all behavior.
    real_hkl = int(lm._u32.GetKeyboardLayout(0) or 0)
    real_command, real_problem = lm._resolve_command(real_hkl)
    if real_problem:
        layout_detail = "typed layer safely unavailable: " + lm._problem_detail(real_problem)
    else:
        slash = next(chord for chord in real_command.chords if chord.char == "/")
        layout_detail = (f"{lm._layout_label(real_hkl)}, '/' scan=0x{slash.scan:02x}, "
                         f"modifiers=0x{slash.modifiers:02x}")
    detail = (f"direct/Shift/PT-BR AltGr/incompatible fixtures pass; {layout_detail}; "
              f"{lm.CMD!r} pre-resolved")
    if not lg._lcu():
        return OK, detail + "; client down, settings layer unverified"
    st = lm.read_state()
    if st is None:
        return FAIL, "the client no longer exposes " + ", ".join(
            f"{g}.{k}" for g, ks in lm.MUTED.items() for k in ks)
    on = all(st.get(f"{g}.{k}") == v for g, ks in lm.MUTED.items() for k, v in ks.items())
    return OK, detail + f"; settings {'MUTED' if on else 'unmuted'}"


def c_muteguard():
    """The input guard that makes auto-mute's typing safe to sit through. It must tell YOUR
    hands apart from our injected keys (via the LLKHF_INJECTED / LLMHF_INJECTED flags) — if it
    can't, it either aborts on its own keystrokes and never mutes, or misses yours and lets a
    keypress shred the command. Mouse MOVEMENT must be ignored: the cursor is never still, and
    moving it doesn't defocus League's chat box; only a click does."""
    import lolmute as lm
    G = lm._InputGuard
    import ctypes
    from ctypes import wintypes

    def fire(kind, wparam, flags):
        g = G()
        idx, mask, skip = ((2, G._LLKHF_INJECTED, ()) if kind == "kb"
                           else (3, G._LLMHF_INJECTED, G._HARMLESS_MOUSE))
        proc = g._make(mask, idx, skip)
        buf = (wintypes.DWORD * 8)(*([0] * 8))
        buf[idx] = flags
        proc(0, wparam, ctypes.cast(ctypes.pointer(buf), ctypes.c_void_p).value)
        return g.interrupted

    cases = [("real keypress", "kb", 0x0100, 0x00, True),
             ("our injected key", "kb", 0x0100, 0x10, False),
             ("mouse move", "ms", 0x0200, 0x00, False),
             ("mouse wheel", "ms", 0x020A, 0x00, False),
             ("real left click", "ms", 0x0201, 0x00, True),
             ("real right click", "ms", 0x0204, 0x00, True),
             ("our injected click", "ms", 0x0201, 0x01, False)]
    bad = [n for n, k, w, f, want in cases if fire(k, w, f) != want]
    if bad:
        return FAIL, "input guard wrong on: " + ", ".join(bad)
    # The live half only means anything if YOU aren't typing during it — otherwise it's your
    # keyboard tripping the guard, which is the guard working. Skip it rather than cry wolf.
    if lm.idle_ms() < 400:
        return OK, "discrimination matrix passes (live check skipped - you're using the keyboard)"
    with G() as g:                                   # and it must not trip on our own typing
        time.sleep(0.1)
        hkl = int(lm._u32.GetKeyboardLayout(0) or 0)
        sh = lm._u32.MapVirtualKeyExW(lm.VK_SHIFT, 0, hkl)
        for _ in range(8):
            lm._tap_scan(sh, 0.02)
            time.sleep(0.02)
        time.sleep(0.15)
        self_trip = g.interrupted
    if g._hooks:
        return FAIL, "low-level hooks left installed after the guard exited"
    if self_trip and lm.idle_ms() > 400:
        return FAIL, "the guard trips on our OWN injected keys - it would abort every time"
    return OK, "tells your keys/clicks from ours; ignores mouse movement; hooks released"


def c_fit():
    """PERSONAL FIT: the recommender's read of YOUR results. It must veto only on real evidence
    (losing three in a row is not proof), demote champs you play below your own standard, and
    promote ones you're good on but haven't touched — the rotation answer to getting bored.
    A veto firing on thin data would silently delete good picks, so the bar is checked here."""
    import lolfit as fit
    rec = {"baseline": 83, "recent": ["yasuo", "hecarim", "khazix"],
           "champs": {"loser": {"g": 10, "w": 1, "avg": 60},      # 10%: proven bad
                      "unlucky": {"g": 3, "w": 0, "avg": 80},     # 0-3 but no sample -> no veto
                      "cold": {"g": 5, "w": 3, "avg": 65},        # wins, plays it badly
                      "neglected": {"g": 6, "w": 4, "avg": 95},   # good + not in recent -> fresh
                      "onegood": {"g": 1, "w": 1, "avg": 120},    # one game is not a champion
                      "yasuo": {"g": 16, "w": 8, "avg": 64}}}
    want = {"loser": "veto", "unlucky": None, "cold": "cold", "neglected": "fresh",
            "onegood": None}
    bad = [f"{k}: got {fit.verdict(rec, k)[0]}, want {v}"
           for k, v in want.items() if fit.verdict(rec, k)[0] != v]
    if bad:
        return FAIL, "; ".join(bad)
    for k in want:
        kind, why = fit.verdict(rec, k)
        if kind and not why:
            return FAIL, f"{k} returned a {kind} verdict with no evidence line"
    dd = {"id2name": {1: "loser", 2: "neglected", 3: "cold"}}
    order, notes = fit.apply(rec, dd, [1, 2, 3])
    if 1 in order:
        return FAIL, "a vetoed champion survived into the recommendations"
    if order[0] != 2:
        return FAIL, "a fresh champion was not promoted above a cold one"
    if not notes.get(1) or not notes.get(2):
        return FAIL, "apply() dropped the evidence notes the panel prints"
    return OK, "vetoes only on real samples; cold demoted, fresh promoted, evidence attached"


def c_runes():
    """ADAPTIVE RUNES: the enemy comp decides which op.gg page to import. This must fire ONLY
    on an unambiguous comp — a wrong call silently imports the wrong keystone for a whole game,
    which is worse than always taking the most-played page."""
    import lolrunes as lr
    want = {"tank": 1,      # 3 tanks -> the Conqueror page
            "squish": 0,    # all squishy -> Electrocute is already right, don't touch it
            "mixed": 0,     # one tank -> no call
            "early": 0,     # under 3 locked -> refuse to read a comp off two picks
            "thin": 0}      # the fitting page has a 9-game sample -> never import a meme
    bad = []
    for k, idx in want.items():
        dd, opts, en = lr.demo(k)
        got, why = lr.choose(dd, opts, en)
        if got != idx:
            bad.append(f"{k}: page {got}, want {idx}")
        elif got != 0 and not why:
            bad.append(f"{k}: switched pages with no evidence line")
        elif got == 0 and why:
            bad.append(f"{k}: claimed a reason while keeping the default")
    if bad:
        return FAIL, "; ".join(bad)
    if not (lr.SUSTAINED & {"Conqueror"}) or not (lr.BURST & {"Electrocute"}):
        return FAIL, "the keystone classes lost their anchors"
    if lr.SUSTAINED & lr.BURST:
        return FAIL, f"a keystone is in BOTH classes: {lr.SUSTAINED & lr.BURST}"
    return OK, "switches only on a clear comp, cites op.gg's own sample, ignores thin pages"


def c_new_i18n():
    """New v0.9.55-v0.9.69 surfaces must switch copy without changing their internal
    contracts. Exercise the same deterministic fixtures in both languages."""
    import ast
    import collections
    import string

    import loldraft as draft
    import lolbleed as bleed, lolclose as close, lolfit as fit, lolrunes as runes
    import lolfix as fix, lolpool as pool, lolout as out
    import lolgold as gold, lolward as ward
    import smitei18n as i18n

    # Audit the source literal rather than the imported dict so a duplicate key cannot be
    # silently overwritten before this test sees it.
    catalog_path = os.path.join(_ROOT, "core", "i18n_pt_BR.py")
    source = open(catalog_path, encoding="utf-8").read()
    tree = ast.parse(source, filename=catalog_path)
    catalog = next((node.value for node in tree.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "MESSAGES"
                            for target in node.targets)), None)
    if not isinstance(catalog, ast.Dict):
        return FAIL, "PT-BR catalog is not a literal MESSAGES dict"
    literal_keys = [key.value for key in catalog.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)]
    duplicates = sorted(key for key, count in collections.Counter(literal_keys).items()
                        if count > 1)
    if duplicates:
        return FAIL, f"duplicate PT-BR catalog keys: {duplicates[:3]}"
    formatter = string.Formatter()
    placeholder_errors = []
    for msgid, translated in i18n.PT_BR_MESSAGES.items():
        source_fields = collections.Counter(
            (field, spec, conversion) for _text, field, spec, conversion
            in formatter.parse(msgid) if field is not None)
        translated_fields = collections.Counter(
            (field, spec, conversion) for _text, field, spec, conversion
            in formatter.parse(translated) if field is not None)
        if source_fields != translated_fields:
            placeholder_errors.append(msgid)
    if placeholder_errors:
        return FAIL, f"PT-BR placeholder mismatch: {placeholder_errors[:3]}"

    def localized_guards():
        gold_kinds = ("pace", "behind", "miss", "cannon", "roaming", "unrecoverable",
                      "onpace_miss", "jungle", "support", "early", "late")
        ward_kinds = ("row", "under", "pit", "pitup", "pitshort", "pitfight",
                      "pitdeadline", "pitsweeper", "pitfarsight", "dark", "darkquiet",
                      "pink", "pinkquiet", "noledger", "base", "basebroke",
                      "basecarrying", "jungle", "adc", "mid", "notarmed", "nofield",
                      "early", "nocounterpart")
        return ({kind: gold._verdict(gold.demo(kind)) for kind in gold_kinds},
                {kind: ward._verdict(ward.demo(kind)) for kind in ward_kinds})

    def contract(card):
        if card is None:
            return None
        presentation = {"line", "sub", "row", "bits", "evidence"}
        return {key: value for key, value in card.items() if key not in presentation}

    previous = i18n.lang()
    try:
        i18n.set_lang("en")
        bleed_en = bleed._verdict(bleed.demo("bleed"))
        close_en = close._verdict(close.demo("end"))
        gold_en, ward_en = localized_guards()
        rec = {"baseline": 83, "recent": [],
               "champs": {"main": {"g": 24, "w": 15, "avg": 86},
                          "loser": {"g": 10, "w": 1, "avg": 60}}}
        fit_en = fit.verdict(rec, "loser")
        fix_en = fix.board(fix.demo("priced"), lp=(20, 20, True))
        fix_head_en = fix.headline(fix_en)
        pool_en = pool.board(pool.demo("spread"), lp=(20, 20, True))
        pool_head_en, pool_width_en = pool.headline(pool_en), pool.width_note(pool_en["width"])
        out_en = {kind: out._verdict(out.demo(kind))
                  for kind in ("baron", "scale", "survive_vote", "call", "clawback")}
        dd, opts, enemies = runes.demo("tank")
        rune_en = runes.choose(dd, opts, enemies)
        demo_names = ("Sett", "Kha'Zix", "Ahri", "Jinx", "Thresh",
                      "Darius", "Graves", "Zed", "Caitlyn", "Lux")
        demo_dd = {
            "norm": lambda value: "".join(c for c in value.lower() if c.isalnum()),
            "name2id": {},
        }
        demo_dd["name2id"] = {
            demo_dd["norm"](name): idx + 1 for idx, name in enumerate(demo_names)
        }
        draft_en = draft._demo_scout(demo_dd)

        i18n.set_lang("pt_BR")
        bleed_pt = bleed._verdict(bleed.demo("bleed"))
        close_pt = close._verdict(close.demo("end"))
        gold_pt, ward_pt = localized_guards()
        rec.pop("_pool", None)  # cached presentation belongs to the locale that built it
        fit_pt = fit.verdict(rec, "loser")
        fix_pt = fix.board(fix.demo("priced"), lp=(20, 20, True))
        fix_head_pt = fix.headline(fix_pt)
        pool_pt = pool.board(pool.demo("spread"), lp=(20, 20, True))
        pool_head_pt, pool_width_pt = pool.headline(pool_pt), pool.width_note(pool_pt["width"])
        out_pt = {kind: out._verdict(out.demo(kind))
                  for kind in ("baron", "scale", "survive_vote", "call", "clawback")}
        rune_pt = runes.choose(dd, opts, enemies)
        draft_pt = draft._demo_scout(demo_dd)
        bad = []
        if bleed_en["verdict"] != "BLEED" or bleed_pt["verdict"] != "BLEED":
            bad.append("BLEED internal verdict changed with locale")
        if not bleed_en["line"].startswith("BACK OFF") or not bleed_pt["line"].startswith("RECUE"):
            bad.append("BLEED copy did not switch EN/PT")
        if close_en["verdict"] != "END" or close_pt["verdict"] != "END":
            bad.append("CLOSER internal verdict changed with locale")
        if not close_en["line"].startswith("END IT") or not close_pt["line"].startswith("TERMINE"):
            bad.append("CLOSER copy did not switch EN/PT")
        for name, english, portuguese in (("GOLD", gold_en, gold_pt),
                                          ("WARD", ward_en, ward_pt)):
            for kind in english:
                if contract(english[kind]) != contract(portuguese[kind]):
                    bad.append(f"{name} {kind} contract changed with locale")
                    break
        for kind, verdict in (("miss", "MISS"), ("cannon", "CANNON"), ("behind", "PACE")):
            if not gold_en[kind]["line"].startswith(verdict) \
                    or not gold_pt[kind]["line"].startswith(verdict):
                bad.append(f"GOLD {verdict} internal ID changed with locale")
        for kind, verdict in (("pit", "PIT"), ("dark", "DARK"),
                              ("pink", "PINK"), ("row", "WARD")):
            if not ward_en[kind]["line"].startswith(verdict) \
                    or not ward_pt[kind]["line"].startswith(verdict):
                bad.append(f"WARD {verdict} internal ID changed with locale")
        if gold_en["miss"]["line"] == gold_pt["miss"]["line"] \
                or "onda" not in gold_pt["miss"]["line"] \
                or gold_en["cannon"]["sub"] == gold_pt["cannon"]["sub"]:
            bad.append("GOLD card/plan copy did not switch EN/PT")
        if ward_en["pit"]["line"] == ward_pt["pit"]["line"] \
                or "dragão" not in ward_pt["pit"]["line"] \
                or ward_en["pink"]["sub"] == ward_pt["pink"]["sub"]:
            bad.append("WARD card/objective copy did not switch EN/PT")
        if len(gold_en["behind"]["bits"]) != len(gold_pt["behind"]["bits"]) \
                or len(ward_en["under"]["bits"]) != len(ward_pt["under"]["bits"]):
            bad.append("GOLD/WARD quiet-row segment shape changed with locale")
        if fit_en[0] != "veto" or fit_pt[0] != "veto" \
                or "W-" not in fit_en[1] or "V-" not in fit_pt[1]:
            bad.append("personal-fit evidence did not switch EN/PT")
        fix_contract = lambda b: (
            b["n"], b["ready"], b["pick"]["tag"], b["pick"]["state"], b["pick"]["lp10"],
            [(r["tag"], r["state"], r["n_ev"], r["n_hit"], r["lp10"], r["recent"])
             for r in b["rows"]])
        if fix_contract(fix_en) != fix_contract(fix_pt):
            bad.append("THE ONE FIX contract changed with locale")
        elif fix_head_en == fix_head_pt \
                or "PDL" not in fix_head_pt \
                or fix_en["pick"]["fix"] == fix_pt["pick"]["fix"]:
            bad.append("THE ONE FIX copy did not switch EN/PT")
        pool_contract = lambda b: (
            b["n"], b["pool_n"], b["ready"], b["verdict"], b["bar"],
            (b.get("queue") or {}).get("champ"), (b.get("bench") or {}).get("champ"),
            [(r["champ"], r["state"], r["g"], r["w"], r["lp10"]) for r in b["rows"]],
            ((b.get("width") or {}).get("state"), (b.get("width") or {}).get("lp10")))
        if pool_contract(pool_en) != pool_contract(pool_pt):
            bad.append("THE POOL contract changed with locale")
        elif pool_head_en == pool_head_pt \
                or "PDL / 10 partidas" not in pool_width_pt \
                or "LP / 10 games" not in pool_width_en:
            bad.append("THE POOL copy/units did not switch EN/PT")
        out_contract = lambda card: None if card is None else {
            key: card.get(key) for key in ("verdict", "tone", "quiet", "lead", "won")}
        for kind in out_en:
            if out_contract(out_en[kind]) != out_contract(out_pt[kind]):
                bad.append(f"THE OUT {kind} contract changed with locale")
                break
        if out_en["baron"]["line"] == out_pt["baron"]["line"] \
                or not out_pt["baron"]["line"].startswith("SAÍDA") \
                or not out_pt["call"]["line"].startswith("ENCERRE") \
                or "recup." not in out_pt["clawback"]["won_txt"]:
            bad.append("THE OUT cards/receipts did not switch EN/PT")
        if rune_en[0] != 1 or rune_pt[0] != 1 or "frontline locked" not in rune_en[1] \
                or "linha de frente" not in rune_pt[1]:
            bad.append("adaptive-rune evidence did not switch EN/PT")
        if i18n.t("ESCAPE KEY") == "ESCAPE KEY" or i18n.t("Back off.") == "Back off." \
                or i18n.t("Ward it.") == "Ward it.":
            bad.append("new Settings/TTS catalog entries are missing")
        if i18n.t("Gold clock (farm pace, first 10 min)").startswith("Gold") \
                or i18n.t("Ward clock (the vision war, jg / sup)").startswith("Ward") \
                or i18n.t("GOLD CLOCK — THE FIRST TEN MINUTES").startswith("GOLD"):
            bad.append("GOLD/WARD Settings or legend catalog entries are missing")
        if i18n.t("AI provider:") == "AI provider:" \
                or "coach" not in i18n.t(
                    "Used by the coach and as the matchup-tip fallback. The selected local "
                    "CLI is authoritative; failures never switch providers automatically."):
            bad.append("matchup provider Settings copy did not switch PT/EN")
        mute_copy = i18n.t(
            "Each game, Smiteless safely types Riot's own /fullmute all while the League "
            "window is focused. That per-game layer hides chat and ping markers. Separately, "
            "it writes League's own settings to hide ally/all chat and mute ping audio, then "
            "reads them back; those settings persist until disabled. If the League window's "
            "keyboard layout cannot produce the command safely, typing stays off for that "
            "session while the verified settings layer remains active.")
        if "Em cada partida" not in mute_copy or "camada verificada" not in mute_copy:
            bad.append("auto-mute two-layer Settings copy did not switch PT/EN")
        if "main · 140k pts" not in draft_en["allies"][0]["t"][0][0] \
                or "principal · 140 mil pts" not in draft_pt["allies"][0]["t"][0][0] \
                or draft_en["allies"][0]["n"] != "You" \
                or draft_pt["allies"][0]["n"] != "Você" \
                or "7W in last 10" not in draft_en["allies"][0]["t"][1][0] \
                or "7V nas últimas 10" not in draft_pt["allies"][0]["t"][1][0] \
                or not draft_pt["allies"][0]["tip"].startswith("Respeite") \
                or draft_en["plan"][0].startswith("O inimigo") \
                or not draft_pt["plan"][0].startswith("O inimigo"):
            bad.append("DraftBoard demo tags/plan did not switch EN/PT")
        if bad:
            return FAIL, "; ".join(bad)
        return OK, ("catalog unique/placeholders valid; BLEED, CLOSER, GOLD, WARD, ONE FIX, "
                    "POOL, OUT, fit, runes, DraftBoard demo and Settings/TTS switch PT/EN")
    finally:
        i18n.set_lang(previous)


def c_maxelo():
    """MAX ELO arms a list of setting keys by name. A typo there is invisible - the switch
    would look armed and quietly leave a feature off - so every key must be a real toggle."""
    import smiteconfig as cfg
    unknown = [k for k in cfg.MAX_ELO_ON if k not in cfg.BOOLS]
    if unknown:
        return FAIL, f"MAX_ELO_ON names settings that don't exist: {unknown}"
    for k in ("auto_accept", "auto_ban", "auto_mute", "re_entry", "tempo_coach"):
        if k not in cfg.MAX_ELO_ON:
            return FAIL, f"MAX_ELO_ON is missing {k!r} - that's a climb feature"
    import lolimport as limp
    if not (hasattr(limp, "auto_pick") and hasattr(limp, "pick_watch_update")):
        return FAIL, "the champ auto-lock is missing - MAX ELO can't hold your pool"
    return OK, f"{len(cfg.MAX_ELO_ON)} climb toggles, all real; auto-lock present"


def c_autolock():
    """MAX ELO's auto-LOCK, against a simulated champ-select session. This can't be triggered
    on demand in a real client, and a break means you find out by getting a champion you didn't
    ask for, mid-draft, with no way back. So every branch runs here every time."""
    import lolbuild as lb, lolimport as limp
    dd = lb.ddragon()
    YAS, YONE = dd["name2id"]["yasuo"], dd["name2id"]["yone"]
    real, real_log, real_own = limp._lcu_json, limp._picklog, limp.pickable_ids
    # smiteless_pick.log is a DIAGNOSTIC — it exists to answer "why didn't my champ lock".
    # Fixture runs writing fake LOCKED lines into it makes it useless for that, so they don't.
    limp._picklog = lambda *a, **k: None

    class Fake:                                  # PATCH sets intent; completed (or POST) locks
        def __init__(self, bans=(), locked=(), in_progress=True):
            self.act = {"id": 7, "actorCellId": 0, "type": "pick", "isInProgress": in_progress,
                        "completed": False, "championId": 0}
            self.bans, self.locked = list(bans), list(locked)

        def __call__(self, method, path, payload=None, timeout=5):
            if method == "GET":
                other = [{"id": 9, "actorCellId": 3, "type": "pick", "completed": True,
                          "championId": c} for c in self.locked]
                return {"localPlayerCellId": 0, "timer": {"adjustedTimeLeftInPhase": 27000},
                        "bans": {"myTeamBans": self.bans, "theirTeamBans": []},
                        "myTeam": [], "actions": [[self.act], other]}
            if method == "PATCH":
                self.act["championId"] = payload.get("championId", 0)
                self.act["completed"] = self.act["completed"] or bool(payload.get("completed"))
            if method == "POST" and path.endswith("/complete"):
                self.act["completed"] = True
            return {}

    def lock(fake, pool, settle=True, owned=None):
        limp._lcu_json = fake
        limp.pickable_ids = (lambda *a, **k: owned) if owned is not None else (lambda *a, **k: None)
        limp._PICK_HOVER.update(action=None, cid=0, ts=0.0)
        limp._PICK_FAIL.clear()
        limp.auto_pick(dd, pool)                 # tick 1: hover only, never a lock
        if settle:
            limp._PICK_HOVER["ts"] -= limp.PICK_SETTLE_S + 0.1
        return limp.auto_pick(dd, pool)          # tick 2: the lock

    try:
        cases = [("main free", Fake(), [YAS, YONE], YAS),
                 ("main banned -> backup", Fake(bans=[YAS]), [YAS, YONE], YONE),
                 ("main taken -> backup", Fake(locked=[YAS]), [YAS, YONE], YONE),
                 ("both gone", Fake(bans=[YAS], locked=[YONE]), [YAS, YONE], None),
                 ("not my turn", Fake(in_progress=False), [YAS, YONE], None),
                 ("no pool", Fake(), [], None)]
        bad = [n for n, f, pool, want in cases if lock(f, pool) != want]
        if lock(Fake(), [YAS, YONE], settle=False) is not None:
            bad.append("locked before the hover settled")
        # OWNERSHIP. Dropping the mastery gate made the pool merit-only, which includes
        # champions you don't own — the client refuses those, and v0.9.59 retried one every
        # second until the timer ran out and the draft picked for you. The top pick being
        # unowned must fall straight through to the next one.
        if lock(Fake(), [YAS, YONE], owned={YONE}) != YONE:
            bad.append("an unowned top pick must skip to the next champion")
        if lock(Fake(), [YAS, YONE], owned=set()) is not None:
            bad.append("owning nothing on the list must lock nothing")
        if lock(Fake(), [YAS, YONE], owned={YAS, YONE}) != YAS:
            bad.append("owning both must still take the best one")
        # FLIP-FLOP. The pool is rebuilt every poll and suggest_champs treats an ally's champ as
        # unavailable — and our own hover IS an ally pick, so hovering A promoted B and hovering
        # B promoted A. It oscillated once a second and never locked. auto_pick must COMMIT to
        # its target: a pool that reorders underneath it changes nothing.
        f = Fake()
        limp._lcu_json = f
        limp.pickable_ids = lambda *a, **k: {YAS, YONE}
        limp._PICK_HOVER.update(action=None, cid=0, ts=0.0)
        limp._PICK_FAIL.clear()
        limp.auto_pick(dd, [YAS, YONE])          # commits to Yasuo
        first = f.act["championId"]
        for i in range(6):                       # pool flips order under it, once a "second"
            limp.auto_pick(dd, ([YONE, YAS] if i % 2 == 0 else [YAS, YONE]))
        if f.act["championId"] != first:
            bad.append("target changed when the pool reordered (the flip-flop is back)")
        limp._PICK_HOVER["ts"] -= limp.PICK_SETTLE_S + 0.1
        if limp.auto_pick(dd, [YONE, YAS]) != first:
            bad.append("did not lock the champion it committed to")
        limp._PICK_HOVER.update(action=None, cid=0, ts=0.0)
        limp._PICK_FAIL.clear()
    finally:
        limp._lcu_json, limp._picklog, limp.pickable_ids = real, real_log, real_own
    if bad:
        return FAIL, "auto-lock wrong on: " + "; ".join(bad)
    return OK, "hover-then-lock, ban/taken fallback to backup, stands down when both are gone"


def c_lcu():
    import lolgame as lg, lolbuild as lb
    lc = lg._lcu()
    if not lc:
        return SKIP, "League client not running"
    port, hdr = lc
    ph = lb.http(f"https://127.0.0.1:{port}/lol-gameflow/v1/gameflow-phase",
                 headers=hdr, timeout=4, insecure=True)
    return OK, f"connected - phase = {ph}"


def c_coach_context():
    """Phase 1 fixtures: exclusivity, privacy, evidence, timeout and determinism."""
    import tempfile
    import threading
    import lolcoachcontext as cc
    import lolgame
    import lollive
    import lolload
    import lolqueue
    import phasecheck
    from unittest import mock

    all_sections = {
        "profile": {"recent_games": [{"in_game_performance_grade": "A"}]},
        "queue": {"verdict": "WAIT"},
        "draft": {"self_champion": "Ahri"},
        "loading": {"enemies": [{"champion": "Zed", "tags": [
            {"text": "off-champ", "evidence_scope": "this_game"},
            {"text": "3W heater", "evidence_scope": "account_history"}]}]},
        "live": {"game_time": 901, "events": [{"kind": "DragonKill"}]},
        "postgame": {"recent_games": [{"in_game_performance_grade": "S"}]},
    }
    expected = {
        "None": {"profile"}, "Lobby": {"profile", "queue"},
        "Matchmaking": {"queue"}, "ReadyCheck": {"queue"},
        "ChampSelect": {"draft"}, "Loading": {"draft", "loading"},
        "GameStart": {"draft", "loading"}, "InProgress": {"live"},
        "Reconnect": {"live"}, "WaitingForStats": {"postgame"},
        "PreEndOfGame": {"postgame"}, "EndOfGame": {"postgame"},
    }
    dd = {"id2name": {1: "Annie", 2: "Olaf"}, "name2id": {"annie": 1, "olaf": 2},
          "norm": lambda value: str(value or "").lower(), "items": {}, "id2tags": {}}
    barrier = threading.Barrier(2)
    roster_calls = []

    def parallel_lcu(url, **_kwargs):
        roster_calls.append(url)
        barrier.wait(timeout=0.5)
        if url.endswith("/lol-gameflow/v1/session"):
            return {"gameData": {
                "teamOne": [{"summonerId": 11, "championId": 1,
                             "selectedPosition": "MIDDLE"}],
                "teamTwo": [{"summonerId": 22, "championId": 2,
                             "selectedPosition": "TOP"}],
            }}
        return {"summonerId": 11}

    timings = []
    with mock.patch.object(lolload.lg, "_lcu", return_value=(123, {})), \
            mock.patch.object(lolload.lb, "http", side_effect=parallel_lcu):
        roster = lolload._roster(
            request_timeout=0.2,
            on_timing=lambda stage, elapsed, outcome: timings.append((stage, outcome)),
        )
    if not roster or not roster[0][0]["me"] or len(roster_calls) != 2 \
            or {stage for stage, _outcome in timings} != {
                "gameflow-session", "current-summoner"}:
        return FAIL, "cold Loading roster reads were not parallel and timed"

    def cached_lcu(url, **_kwargs):
        if url.endswith("/current-summoner"):
            raise AssertionError("cached identity was ignored")
        return {"gameData": {
            "teamOne": [{"summonerId": 11, "championId": 1}],
            "teamTwo": [{"summonerId": 22, "championId": 2}],
        }}

    with mock.patch.object(lolload.lg, "_lcu", return_value=(123, {})), \
            mock.patch.object(lolload.lb, "http", side_effect=cached_lcu):
        if not lolload._roster(mysid=11, request_timeout=0.2)[0][0]["me"]:
            return FAIL, "ChampSelect identity warmup was not reused in Loading"

    live_payload = {
        "activePlayer": {"riotId": "Self Name#NA1"},
        "allPlayers": [
            {"riotId": "Self Name#NA1", "championName": "Annie",
             "team": "ORDER", "position": "MIDDLE"},
            {"riotId": "Enemy Name#NA1", "championName": "Olaf",
             "team": "CHAOS", "position": "TOP"},
        ],
    }
    with mock.patch.object(lolload.lb, "http", return_value=live_payload):
        live_minimal = lolload.brief_from_live(dd)
    live_encoded = json.dumps(live_minimal)
    if not live_minimal or not live_minimal["allies"][0]["me"] \
            or "Name#NA1" in live_encoded or "riotId" in live_encoded \
            or not live_minimal["_lobby_key"].startswith("live-"):
        return FAIL, "clock-zero Live Client fallback was not anonymous and shaped"
    draft = lolgame.coach_snapshot(dd, {"my": 1, "pos": "mid", "allies": [(1, "mid")],
                                         "enemies": [(2, "top")], "phase": "ChampSelect",
                                         "source": "fixture"})
    if draft["allies"][0]["slot"] != "self" or draft["enemies"][0]["slot"] != "enemy_1":
        return FAIL, "draft adapter did not anonymize stable player slots"
    loading = lolload.coach_snapshot({"allies": [{"me": True, "champ": "Annie",
        "player": "Self Name#NA1", "puuid": "x" * 78,
        "tags": [("comfort · 5-1 on Annie", "good")]}], "enemies": []})
    if loading["allies"][0]["slot"] != "self" or \
            loading["allies"][0]["tags"][0]["evidence_scope"] != "this_game":
        return FAIL, "loading adapter lost self anonymity or tag scope"
    with tempfile.TemporaryDirectory(prefix="smiteless-loading-short-") as tmp:
        snap_file = os.path.join(tmp, "scout.json")
        minimal = {"scouted": False, "_lobby_key": "short-load",
                   "plan": ["play safe"], "wincons": {},
                   "allies": [{"me": True, "champ": "Annie", "role": "MID",
                                "player": "", "puuid": None, "tags": []}],
                   "enemies": [{"me": False, "champ": "Olaf", "role": "TOP",
                                 "player": "", "puuid": None, "tags": []}]}
        full = dict(minimal, scouted=True)
        lolload._LOCAL.update(key=None, brief=None)
        with mock.patch.object(lolload, "SNAP_FILE", snap_file), \
                mock.patch.object(lolload, "SNAP_LOCK", snap_file + ".lock"):
            with mock.patch.object(lolload, "brief",
                                   side_effect=[None, None, minimal]) as minimal_read, \
                    mock.patch.object(lolload, "brief_from_live", return_value=None), \
                    mock.patch.object(lolload, "_lobby_key") as key_probe:
                prepared = lolload.prepare_minimal_snapshot(
                    dd, mysid=11, attempts=3, request_timeout=0.1, retry_delay=0)
            if prepared is not minimal or minimal_read.call_count != 3:
                return FAIL, "short Loading bounded retries did not reach the roster"
            if key_probe.called:
                return FAIL, "minimal Loading snapshot repeated the roster/Lobby read"
            if not os.path.exists(snap_file):
                return FAIL, "short Loading did not publish the minimal snapshot"
            cached = lolload.coach_snapshot(lifecycle_key="short-load")
            encoded_cached = json.dumps(cached)
            if cached["allies"][0]["slot"] != "self" or "puuid" in encoded_cached \
                    or "player" in encoded_cached:
                return FAIL, "minimal Loading snapshot was not anonymous"
            with mock.patch.object(lolload, "_lobby_key", return_value="short-load"), \
                    mock.patch.object(lolload, "brief", return_value=full) as full_fetch:
                shared = lolload.brief_shared(dd, wait=0)
            if not shared.get("scouted") or full_fetch.call_count != 1 \
                    or full_fetch.call_args.kwargs.get("scout") is not True:
                return FAIL, "minimal Loading snapshot suppressed the one full scout"
            live_same_match = dict(minimal, _lobby_key="live-same-champions")
            lolload.publish_minimal_snapshot(dd, live_same_match)
            with open(snap_file, encoding="utf-8") as snapshot_handle:
                preserved = json.load(snapshot_handle)
            if preserved.get("key") != "short-load" \
                    or not (preserved.get("brief") or {}).get("scouted"):
                return FAIL, "Live fallback downgraded an existing full scout"
        lolload._LOCAL.update(key=None, brief=None)
    live_data = {"activePlayer": {"riotId": "Self Name#NA1"},
                 "gameData": {"gameTime": 12}, "events": {"Events": []},
                 "allPlayers": [{"riotId": "Self Name#NA1", "championName": "Annie",
                                 "team": "ORDER", "scores": {}, "items": []},
                                {"riotId": "Enemy Name#NA1", "championName": "Olaf",
                                 "team": "CHAOS", "scores": {}, "items": []}]}
    live = lollive.coach_snapshot(dd, live_data)
    if "Name#NA1" in json.dumps(live) or live["enemies"][0]["slot"] != "enemy_1":
        return FAIL, "live adapter exposed a Riot ID or lost anonymous slots"
    for phase_name, want in expected.items():
        env = cc.capture(phase=phase_name, collectors=all_sections,
                         lifecycle_hints={"game_id": 123}, now=1000)
        if set(env["sections"]) != want:
            return FAIL, f"{phase_name} leaked sections {set(env['sections'])}, wanted {want}"

    with mock.patch.object(lolqueue, "coach_snapshot",
                           side_effect=lambda phase=None: {"captured_phase": phase}):
        lobby = cc.capture(phase="Lobby", collectors={"profile": {"safe": True}},
                           lifecycle_hints={"lobby_id": 123}, now=1000)
    if lobby["sections"].get("queue", {}).get("captured_phase") != "Lobby":
        return FAIL, "context did not pass its known phase to the queue adapter"
    with mock.patch.object(phasecheck, "phase",
                           side_effect=AssertionError("phase was re-detected")), \
            mock.patch.object(lolgame, "_lcu", return_value=None):
        state = lolqueue._coach_queue_state(phase="Lobby")
    if state.get("phase") != "Lobby":
        return FAIL, "queue adapter did not reuse its supplied phase"

    dirty = {"Authorization": "Basic dXNlcjpwYXNz", "riot_api_key": "RGAPI-secret",
             "puuid": "x" * 78, "player": "Enemy Name#NA1",
             "raw": "LeagueClient:123:456:password:https",
             "note": r"see C:\Users\Alice\AppData\Local\Riot\lockfile",
             "safe": "keep me"}
    env = cc.capture(phase="Lobby", collectors={"profile": dirty, "queue": {}},
                     lifecycle_hints={"lobby_id": "secret-lobby"}, now=1000)
    encoded = cc.serialize_json(env)
    forbidden = ("RGAPI-", "Basic ", "x" * 70, "Name#NA1", r"C:\Users", "password:https")
    if any(value in encoded for value in forbidden):
        return FAIL, "a credential, identifier or local path survived coach serialization"
    if not env["redactions"] or env["sections"]["profile"].get("safe") != "keep me":
        return FAIL, "sanitizer did not preserve safe data and record redactions"

    ev = cc.capture(phase="Loading", collectors=all_sections,
                    lifecycle_hints={"game_id": 123}, now=1000)
    scopes = {(row["kind"], row["evidence_scope"]) for row in ev["evidence"]}
    if ("tag", "this_game") not in scopes or ("tag", "account_history") not in scopes:
        return FAIL, "tag evidence scopes collapsed"
    post = cc.capture(phase="EndOfGame", collectors=all_sections,
                      lifecycle_hints={"game_id": 123}, now=1000)
    if not any(row["kind"] == "in_game_performance_grade" and
               row["evidence_scope"] == "this_game" for row in post["evidence"]):
        return FAIL, "performance grade lost its in-game evidence origin"

    def slow():
        time.sleep(0.05)
        return {"late": True}

    partial = cc.capture(phase="Lobby", collectors={"profile": slow,
                         "queue": {"verdict": "GO"}}, timeout=0.005,
                         lifecycle_hints={"lobby_id": 7}, now=1000)
    if partial["sections"].get("queue", {}).get("verdict") != "GO":
        return FAIL, "one collector timeout discarded a healthy section"
    timeouts = [row for row in partial["unavailable"] if row["reason"] == "timeout"]
    if timeouts != [{"section": "profile", "reason": "timeout"}]:
        return FAIL, f"collector timeout was not isolated: {partial['unavailable']}"

    a = cc.capture(phase="InProgress", collectors=all_sections,
                   lifecycle_hints={"game_id": 123}, now=1000)
    b = cc.capture(phase="InProgress", collectors=all_sections,
                   lifecycle_hints={"game_id": 123}, now=1000)
    if cc.serialize_json(a) != cc.serialize_json(b):
        return FAIL, "context JSON is not stable for identical inputs"
    first = cc.lifecycle_identity("InProgress")
    if cc.lifecycle_identity("InProgress") != first:
        return FAIL, "fallback lifecycle changed inside one game"
    cc.lifecycle_identity("EndOfGame")
    if cc.lifecycle_identity("Lobby") == first:
        return FAIL, "timestamp fallback joined two games across a terminal transition"
    return OK, "all phases exclusive; secrets redacted; evidence scoped; failures isolated"


def c_coach_runtime():
    """Phase 2 fixtures: session, prompts, authenticated IPC and launcher contracts."""
    import socket
    import tempfile
    import threading
    from unittest import mock
    import lolcoachcontext as context
    import lolcoachipc as ipc
    import lolcoachprompt as prompt
    import lolcoachsession as session
    import llmprocess
    import smitecoach
    import smitei18n
    import smitesettings
    import smiteless_tray

    bad = []
    clock = [1000.0]
    memory = session.CoachSession(max_turns=2, max_characters=40, idle_seconds=20,
                                  clock=lambda: clock[0])
    memory.observe("Lobby", "league-a")
    memory.add_turn("first question", "first answer")
    memory.observe("ChampSelect", "league-a")
    memory.add_turn("second question", "second answer")
    memory.add_turn("third question", "third answer")
    if len(memory.history()) > 2 or any("context" in row for row in memory.history()):
        bad.append("session bounds/text-only history")
    if [row["phase"] for row in memory.snapshot()["phase_markers"]][-2:] \
            != ["Lobby", "ChampSelect"]:
        bad.append("session phase markers")
    memory.observe("PostGame", "league-a")
    if not memory.observe("Lobby", "league-b")["new_lifecycle"] or memory.history():
        bad.append("session lifecycle separation")
    memory.add_turn("q", "a")
    clock[0] += 21
    if memory.history():
        bad.append("session two-hour-style idle expiry")
    memory.add_turn("q", "a")
    memory.reset()
    if memory.snapshot()["turn_count"]:
        bad.append("session reset")

    env = context.capture(
        phase="Lobby", lifecycle_hints={"lobby_id": "fixture"}, now=1000,
        collectors={"profile": {"safe": "value", "riot_id": "Name#NA1"},
                    "queue": {"_unavailable": "missing"}},
    )
    en = prompt.build_prompt("What now?", env, [{"user": "Earlier?", "assistant": "Wait."}], "en")
    pt = prompt.build_prompt("E agora?", env, [], "pt_BR")
    if "Reply only in English" not in en or "Brazilian Portuguese" not in pt \
            or "unavailable" not in en or "Name#NA1" in en:
        bad.append("bilingual/redacted/unavailable prompt")

    killed = []
    fake = type("FakeProcess", (), {"pid": 7})()
    handle = llmprocess.CancellationHandle()
    with mock.patch.object(llmprocess, "terminate_tree", side_effect=killed.append):
        if not handle.attach(fake):
            bad.append("cancellation attach")
        handle.cancel()
    if killed != [fake] or not handle.cancelled:
        bad.append("provider cancellation tree")

    original_language = smitei18n.lang()
    try:
        expected = {
            "en": "I did not hear a question. Press the hotkey and try once more.",
            "pt_BR": "Não ouvi uma pergunta. Pressione o atalho e tente mais uma vez.",
        }
        for locale, message in expected.items():
            smitei18n.set_lang(locale)
            listening = smitecoach.t("Listening…")
            expected_listening = "Ouvindo…" if locale == "pt_BR" else "Listening…"
            if listening != expected_listening or "â" in listening:
                bad.append(f"listening ellipsis encoding {locale}")
            for code in ("no_speech", "empty_transcript"):
                visible = smitecoach.recognition_error_message(code)
                if visible != message or code in visible \
                        or "recognition is unavailable" in visible.lower() \
                        or "reconhecimento de voz local está indisponível" in visible.lower():
                    bad.append(f"recoverable {code} {locale} UI mapping")
            unclear = smitecoach.recognition_error_message("low_confidence")
            if "clearly" not in unclear.lower() and "clareza" not in unclear.lower():
                bad.append(f"distinct low-confidence {locale} UI mapping")
            for code in ("silent", "online_unavailable", "missing_voice", "sapi_error",
                         "timeout", "playback_error", "speaker_error"):
                result = {"ok": False, "error": code}
                coach_message = smitecoach.coach_audio_state(
                    "private visible answer", result)["error"]
                settings_message = smitesettings.audio_test_message(result)
                if coach_message != settings_message or code in coach_message \
                        or "private visible answer" in coach_message:
                    bad.append(f"shared safe audio classification {code} {locale}")
                    break
    finally:
        smitei18n.set_lang(original_language)

    class ListeningAudio:
        def __init__(self):
            self.stopped = 0
            self.finished = 0

        def stop_listening(self):
            self.stopped += 1
            return True

        def finish_listening(self):
            self.finished += 1
            return True

    listener = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    listener.lock = threading.RLock()
    listener.cancel_handle = None
    listener.state = "idle"
    listener.stt_runtime = object()
    listener.audio = ListeningAudio()
    listener._cancel_proactive = mock.Mock(return_value=False)
    listener.show = mock.Mock()
    state_changed = threading.Event()
    asked = threading.Event()

    def set_listener(**values):
        for key, value in values.items():
            setattr(listener, key, value)
        if values.get("state") in ("error", "thinking"):
            state_changed.set()

    def ask_listener(question, handle=None):
        listener.asked_question = question
        listener.asked_handle = handle
        asked.set()
        return {"ok": True}

    listener._set = set_listener
    listener.ask = ask_listener
    recognize_results = iter((
        {"ok": False, "error": "empty_transcript"},
        {"ok": True, "text": "What is my next move?"},
    ))
    with mock.patch.object(smitecoach.cfg, "load",
                           return_value={"voice_coach": True}), \
            mock.patch.object(smitecoach.smitestt, "recognize",
                              side_effect=lambda *_args, **_kwargs: next(recognize_results)):
        first_listen = listener.start_listening()
        if not state_changed.wait(1):
            bad.append("empty transcript Coach callback timeout")
        first_handle_released = listener.cancel_handle is None
        first_gate_released = listener.audio.finished == 1
        first_message = listener.error
        listener.state = "idle"
        state_changed.clear()
        second_listen = listener.start_listening()
        if not asked.wait(1):
            bad.append("post-empty transcript retry timeout")
    if not first_listen.get("ok") or not first_handle_released or not first_gate_released \
            or "empty_transcript" in first_message \
            or "unavailable" in first_message.lower():
        bad.append("empty transcript handle/gate/recoverable Coach state")
    if not second_listen.get("ok") or listener.state != "thinking" \
            or getattr(listener, "asked_question", "") != "What is my next move?" \
            or listener.audio.stopped != 2 or listener.audio.finished != 2 \
            or listener._cancel_proactive.call_count != 2:
        bad.append("immediate valid retry after empty transcript")

    disabled = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    disabled._set = mock.Mock()
    disabled.show = mock.Mock()
    with mock.patch.object(smitecoach.cfg, "load",
                           return_value={"voice_coach": False}), \
            mock.patch.object(smitecoach.lolcoachcontext, "capture") as capture_mock:
        rejected = disabled.ask("Should I queue?")
    if rejected.get("ok") or not rejected.get("disabled") or capture_mock.called:
        bad.append("disabled coach sent context")

    failing = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    failing.session = session.CoachSession()
    failing.lock = threading.RLock()
    failing.cancel_handle = None
    failing.provider = "claude"
    failing._set = mock.Mock()
    failing.show = mock.Mock()
    fake_env = context.capture(phase="None", lifecycle_hints={"session_id": "x"},
                               now=1000, collectors={"profile": {"safe": True}})
    with mock.patch.object(smitecoach.cfg, "load",
                           return_value={"voice_coach": True, "llm_provider": "codex"}), \
            mock.patch.object(smitecoach.phasecheck, "phase_detailed", return_value="None"), \
            mock.patch.object(smitecoach.lolcoachcontext, "capture", return_value=fake_env), \
            mock.patch.object(smitecoach.llmcli, "call",
                              return_value=(None, "provider failed")) as provider_call:
        failed = failing.ask("What now?")
    if failed.get("ok") or failing.session.history() \
            or provider_call.call_args.args[1] != "codex" \
            or failing.cancel_handle is not None:
        bad.append("provider failure/no-failover/no-answer-cache")

    rejected_audio = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    rejected_audio.session = session.CoachSession()
    rejected_audio.lock = threading.RLock()
    rejected_audio.cancel_handle = None
    rejected_audio.provider = "codex"
    rejected_audio.audio = mock.Mock()
    rejected_audio.audio.submit.return_value = False
    rejected_audio._cancel_proactive = lambda _reason: False
    rejected_audio.show = mock.Mock()

    def set_rejected_audio(**values):
        for key, value in values.items():
            setattr(rejected_audio, key, value)

    rejected_audio._set = set_rejected_audio
    original_language = smitei18n.lang()
    smitei18n.set_lang("en")
    try:
        with mock.patch.object(smitecoach.cfg, "load", return_value={
                    "voice_coach": True, "llm_provider": "codex", "dragon_volume": 30}), \
                mock.patch.object(smitecoach.phasecheck, "phase_detailed", return_value="None"), \
                mock.patch.object(smitecoach.lolcoachcontext, "capture", return_value=fake_env), \
                mock.patch.object(smitecoach.lolcoachtools, "answer",
                                  return_value={"text": "Keep this visible answer"}):
            refused_submit = rejected_audio.ask("What now?")
    finally:
        smitei18n.set_lang(original_language)
    if not refused_submit.get("ok") or rejected_audio.state != "error" \
            or rejected_audio.answer != "Keep this visible answer" \
            or "unexpected audio error" not in rejected_audio.error.lower() \
            or rejected_audio.audio.submit.call_count != 1 \
            or rejected_audio.cancel_handle is not None:
        bad.append("rejected manual audio submit preserved answer/state")

    class ImmediateRoot:
        def after(self, _delay, callback):
            callback()

    class DeferredRoot:
        def __init__(self):
            self.callbacks = []

        def after(self, _delay, callback):
            self.callbacks.append(callback)

    class HeldAudio:
        def __init__(self):
            self.jobs = []
            self.stopped = 0
            self.finished = 0

        def submit(self, job):
            self.jobs.append(job)
            return True

        def stop_listening(self):
            self.stopped += 1
            return True

        def finish_listening(self):
            self.finished += 1
            return True

    def manual_fixture(audio=None):
        coordinator = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
        coordinator.root = ImmediateRoot()
        coordinator.lock = threading.RLock()
        coordinator.cancel_handle = None
        coordinator.manual_turn_token = 0
        coordinator.proactive_handle = None
        coordinator.proactive_turn_token = 0
        coordinator.state = "idle"
        coordinator.answer = ""
        coordinator.error = ""
        coordinator.user_text = ""
        coordinator.session = session.CoachSession()
        coordinator.audio = audio or HeldAudio()
        coordinator._cancel_proactive = lambda _reason: False
        coordinator.show = mock.Mock()
        coordinator._render = lambda: None
        return coordinator

    visual_only = manual_fixture()
    visual_only.state = "speaking"
    visual_only.start_listening = mock.Mock(return_value={"ok": True, "state": "listening"})
    visual_only.cancel = mock.Mock(return_value={"ok": True, "cancelled": True})
    visual_toggle = visual_only.dispatch({"type": "toggle"})
    visual_only.state = "thinking"
    thinking_toggle = visual_only.dispatch({"type": "toggle"})
    visual_only.state = "listening"
    listening_toggle = visual_only.dispatch({"type": "toggle"})
    if not all(row.get("ok") for row in (visual_toggle, thinking_toggle, listening_toggle)) \
            or visual_only.start_listening.call_count != 3 or visual_only.cancel.called \
            or visual_only._manual_busy():
        bad.append("visual-only coach states recover into listening")

    pending_proactive = manual_fixture()
    pending_proactive.root = DeferredRoot()
    pending_handle = object()
    pending_proactive.proactive_handle = pending_handle
    pending_proactive.proactive_turn_token = 1
    pending_proactive._set_proactive(pending_handle, state="speaking")
    pending_proactive._reserve_manual_turn()
    for callback in pending_proactive.root.callbacks:
        callback()
    if pending_proactive.state != "idle":
        bad.append("queued proactive UI callback cannot overwrite manual reservation")

    active_toggle = manual_fixture()
    active_handle = active_toggle._reserve_manual_turn()
    active_toggle.start_listening = mock.Mock(return_value={"ok": True})
    active_toggle.cancel = mock.Mock(return_value={"ok": True, "cancelled": True})
    active_toggle.dispatch({"type": "toggle"})
    if active_handle is None or not active_toggle.cancel.called or active_toggle.start_listening.called:
        bad.append("real manual turn toggles to explicit cancellation")

    held_audio = HeldAudio()
    answering = manual_fixture(held_audio)
    with mock.patch.object(smitecoach.cfg, "load", return_value={
                "voice_coach": True, "llm_provider": "codex", "dragon_volume": 30}), \
            mock.patch.object(smitecoach.phasecheck, "phase_detailed", return_value="None"), \
            mock.patch.object(smitecoach.lolcoachcontext, "capture", return_value=fake_env), \
            mock.patch.object(smitecoach.lolcoachtools, "answer",
                              return_value={"text": "Manual answer"}):
        accepted_audio = answering.ask("What now?")
    manual_handle = answering.cancel_handle
    if not accepted_audio.get("ok") or manual_handle is None or not answering._manual_busy() \
            or answering.state != "speaking" or len(held_audio.jobs) != 1:
        bad.append("manual owner survives through audio playback")
    held_audio.jobs[0].callback({"ok": True})
    if answering.cancel_handle is not None or answering._manual_busy() \
            or answering.state != "idle":
        bad.append("manual audio completion releases owner")

    delayed_audio = HeldAudio()
    delayed = manual_fixture(delayed_audio)
    with mock.patch.object(smitecoach.cfg, "load", return_value={
                "voice_coach": True, "llm_provider": "codex", "dragon_volume": 30}), \
            mock.patch.object(smitecoach.phasecheck, "phase_detailed", return_value="None"), \
            mock.patch.object(smitecoach.lolcoachcontext, "capture", return_value=fake_env), \
            mock.patch.object(smitecoach.lolcoachtools, "answer",
                              return_value={"text": "Old answer"}):
        delayed.ask("Old question?")
    delayed._cancel_manual_turn()
    delayed._reserve_manual_turn()
    delayed.state = "listening"
    delayed_audio.jobs[0].callback({"ok": True})
    if delayed.state != "listening" or delayed.cancel_handle is None:
        bad.append("old manual audio callback cannot overwrite new listening turn")

    failed_audio = HeldAudio()
    audio_error = manual_fixture(failed_audio)
    with mock.patch.object(smitecoach.cfg, "load", return_value={
                "voice_coach": True, "llm_provider": "codex", "dragon_volume": 30}), \
            mock.patch.object(smitecoach.phasecheck, "phase_detailed", return_value="None"), \
            mock.patch.object(smitecoach.lolcoachcontext, "capture", return_value=fake_env), \
            mock.patch.object(smitecoach.lolcoachtools, "answer",
                              return_value={"text": "Audio may fail"}):
        audio_error.ask("What now?")
    failed_audio.jobs[0].callback({"ok": False, "error": "speaker_error"})
    if audio_error.cancel_handle is not None or audio_error.state != "error":
        bad.append("manual audio failure releases owner")

    cancelling = manual_fixture(HeldAudio())
    cancelling_handle = cancelling._reserve_manual_turn()
    cancelling.state = "speaking"
    explicit_cancel = cancelling.cancel()
    if not explicit_cancel.get("cancelled") or cancelling.cancel_handle is not None \
            or not cancelling_handle.cancelled or cancelling.state != "cancelled":
        bad.append("explicit manual cancellation releases and invalidates owner")

    surface = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    surface.root = mock.Mock()
    surface.root.winfo_reqheight.return_value = 260
    surface.root.winfo_screenwidth.return_value = 1920
    surface.root.winfo_screenheight.return_value = 1080
    surface._resize_surface()
    surface.root.geometry.assert_called_once_with("440x260+1452+496")
    rendered = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    rendered.session = mock.Mock()
    rendered.session.snapshot.return_value = {"phase": "Lobby"}
    rendered.state = "error"
    rendered.provider = "codex"
    rendered.user_text = "question"
    rendered.answer = "kept answer"
    rendered.error = "long error"
    rendered.status_label = mock.Mock()
    rendered.phase_label = mock.Mock()
    rendered.user_label = mock.Mock()
    rendered.answer_label = mock.Mock()
    rendered._resize_surface = mock.Mock()
    rendered._render()
    rendered._resize_surface.assert_called_once_with()
    visible_audio_failure = rendered.answer_label.config.call_args.kwargs.get("text", "")
    if "kept answer" not in visible_audio_failure or "long error" not in visible_audio_failure:
        bad.append("rendered audio failure hid textual answer")

    hidden = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    hidden.root = mock.Mock()
    if hidden.dispatch({"type": "hide"}) != {"ok": True}:
        bad.append("focus-free hide IPC")
    else:
        hidden.root.after.assert_called_once_with(0, hidden.root.withdraw)

    with mock.patch.object(smitecoach, "_server_alive", return_value=True), \
            mock.patch.object(smitecoach, "_single_instance") as instance_mock:
        duplicate = smitecoach.serve()
    if duplicate != 0 or instance_mock.called:
        bad.append("duplicate serve idempotence")

    with tempfile.TemporaryDirectory(prefix="smiteless-coach-ipc-") as tmp:
        endpoint_path = os.path.join(tmp, "endpoint.json")
        server = ipc.CoachIpcServer(
            lambda message: {"ok": True, "echo": message.get("text")}, endpoint_path)
        endpoint = server.publish()
        if endpoint.get("owner_pid") is not None:
            bad.append("ownerless IPC endpoint compatibility")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            got = ipc.request({"type": "fixture", "text": "hello"},
                              endpoint_path=endpoint_path)
            if got != {"ok": True, "echo": "hello"}:
                bad.append("IPC valid request")

            def raw(value):
                with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as sock:
                    sock.sendall(json.dumps(value).encode("utf-8") + b"\n")
                    return json.loads(sock.recv(4096).split(b"\n", 1)[0].decode("utf-8"))

            wrong = raw({"version": ipc.PROTOCOL_VERSION, "token": "wrong", "type": "status"})
            mismatch = raw({"version": 999, "token": endpoint["token"], "type": "status"})
            if wrong.get("error") != "unauthorized" or mismatch.get("error") != "version_mismatch":
                bad.append("IPC auth/version gate")
            with socket.create_connection(("127.0.0.1", endpoint["port"]), timeout=2) as sock:
                sock.sendall(b"x" * (ipc.MAX_REQUEST_BYTES + 1) + b"\n")
                oversized = json.loads(sock.recv(4096).split(b"\n", 1)[0].decode("utf-8"))
            if oversized.get("error") != "request_too_large":
                bad.append("IPC oversized request")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        if os.path.exists(endpoint_path):
            bad.append("IPC clean shutdown endpoint")
        try:
            ipc.request({"type": "status"}, endpoint_path=endpoint_path, timeout=0.1)
            bad.append("IPC missing server")
        except ipc.IpcError:
            pass
        with open(endpoint_path, "w", encoding="utf-8") as handle_file:
            json.dump({"pid": 999, "port": 1, "token": "stale"}, handle_file)
        try:
            ipc.request({"type": "status"}, endpoint_path=endpoint_path, timeout=0.1)
            bad.append("IPC stale endpoint")
        except ipc.IpcError:
            ipc.remove_endpoint(endpoint_path)

    with tempfile.TemporaryDirectory(prefix="smiteless-coach-reload-") as tmp:
        endpoint_path = os.path.join(tmp, "endpoint.json")
        old_server = ipc.CoachIpcServer(lambda message: {"ok": True}, endpoint_path,
                                        owner_pid=101)
        old_endpoint = old_server.publish()
        old_server.server_close()
        new_server = ipc.CoachIpcServer(lambda message: {"ok": True}, endpoint_path,
                                        owner_pid=202)
        new_endpoint = new_server.publish()
        try:
            if old_endpoint["owner_pid"] != 101 or new_endpoint["owner_pid"] != 202 \
                    or old_endpoint["token"] == new_endpoint["token"]:
                bad.append("reload endpoint ownership/generation")
            with mock.patch.object(smitecoach, "_server_alive", return_value=True), \
                    mock.patch.object(smitecoach.lolcoachipc, "read_endpoint",
                                      return_value=new_endpoint), \
                    mock.patch.object(smitecoach, "_launch_server") as late_launch, \
                    mock.patch.object(smitecoach.lolcoachipc, "request") as late_shutdown:
                if smitecoach.main(["shutdown", "--endpoint-token=" +
                                    old_endpoint["token"]]) != 0 or late_shutdown.called \
                        or late_launch.called:
                    bad.append("late old-tray shutdown reached replacement coordinator")
        finally:
            new_server.server_close()

    launcher_paths = (os.path.join(_ROOT, "dist", "tray.ahk"),
                      os.path.join(_ROOT, "smiteless.ahk"),
                      os.path.join(_ROOT, "tools", "smiteless_tray.py"))
    launcher_texts = [open(path, encoding="utf-8").read() for path in launcher_paths]
    if not all(("coach serve" in text or '"coach", "serve"' in text)
               and ("coach show" in text or '"coach", "show"' in text)
               and ("coach hide" in text or '"coach", "hide"' in text)
               and ("coach shutdown" in text or '"coach", "shutdown"' in text)
               and "owner-pid" in text and "endpoint-token" in text
               and "reload" in text.lower()
               for text in launcher_texts):
        bad.append("coach startup/show/hide/reload launcher contract")
    if any("A_Pid" in text or "GetCurrentProcessId" in text
           or "ProcessExist()" not in text for text in launcher_texts[:2]):
        bad.append("AHK tray owner PID contract")

    tray_icon = mock.Mock()
    with mock.patch.object(smiteless_tray, "_shutdown_coach") as tray_shutdown, \
            mock.patch.object(smiteless_tray, "_launch") as tray_launch, \
            mock.patch.object(smiteless_tray._stop, "set") as tray_stop:
        smiteless_tray.reload_tray(tray_icon)
    if not (tray_shutdown.called and tray_stop.called and tray_icon.stop.called) \
            or tray_launch.call_args.args[1:] != ("--reload-wait", str(os.getpid())):
        bad.append("Python tray reload replacement contract")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, "session/prompt/cancellation/IPC/launcher fixtures pass"


def c_coach_tools():
    """Phase 5 fixtures: allowlisted one-round context discovery and redaction."""
    import dataclasses
    import tempfile
    import threading
    from unittest import mock
    import lolcoachcontext as context
    import lolcoachtools as tools
    import lolmatchup
    import lolcoachsession
    import smitecoach

    bad = []
    dirty = {
        "safe": "keep me", "riot_id": "Enemy Name#NA1", "puuid": "x" * 78,
        "authorization": "Basic dXNlcjpwYXNz", "path": r"C:\Users\Alice\secret.txt",
    }
    forbidden_phase = {
        "profile.recent": "InProgress", "queue.current": "ChampSelect",
        "draft.current": "None", "loading.scout": "Lobby",
        "live.current": "Loading", "matchup.current": "None",
        "postgame.latest": "Lobby",
    }
    with tempfile.TemporaryDirectory(prefix="smiteless-coach-tools-") as tmp:
        trace_path = os.path.join(tmp, "trace.jsonl")
        for spec in tools._SPECS:
            allowed_phase = spec.phases[0]
            allowed = tools.execute(
                spec.tool_id, {}, allowed_phase, collectors={spec.tool_id: lambda: dirty},
                trace_path=trace_path)
            encoded = json.dumps(allowed.get("data"), ensure_ascii=False)
            if not allowed.get("ok") or allowed.get("outcome") != "ok" \
                    or "keep me" not in encoded or any(secret in encoded for secret in (
                        "Name#NA1", "x" * 70, "Basic ", r"C:\Users")):
                bad.append(f"{spec.tool_id} allowed/sanitizer")

            forbidden_collector = mock.Mock(return_value={"must": "not run"})
            forbidden = tools.execute(
                spec.tool_id, {}, forbidden_phase[spec.tool_id],
                collectors={spec.tool_id: forbidden_collector}, trace_path=trace_path)
            if forbidden.get("executed") or forbidden_collector.called \
                    or forbidden.get("outcome") != "forbidden_phase":
                bad.append(f"{spec.tool_id} forbidden phase")

            slow_spec = dataclasses.replace(spec, timeout_seconds=0.005)
            with mock.patch.dict(tools.SPECS, {spec.tool_id: slow_spec}):
                timed = tools.execute(
                    spec.tool_id, {}, allowed_phase,
                    collectors={spec.tool_id: lambda: (time.sleep(0.03), dirty)[1]},
                    trace_path=trace_path)
            if timed.get("outcome") != "timeout" or not timed.get("executed"):
                bad.append(f"{spec.tool_id} timeout")

            stale = tools.execute(
                spec.tool_id, {}, allowed_phase,
                collectors={spec.tool_id: lambda age=spec.freshness_seconds: {
                    "source_age_ms": (age + 1) * 1000, "safe": True}},
                trace_path=trace_path)
            if stale.get("outcome") != "stale" or not stale.get("executed"):
                bad.append(f"{spec.tool_id} freshness")

        first_spec = tools._SPECS[0]
        oversized = tools.execute(
            first_spec.tool_id, {}, first_spec.phases[0],
            collectors={first_spec.tool_id: lambda: {
                "rows": [{"safe": "word " * 200} for _ in range(20)]}},
            trace_path=trace_path)
        if oversized.get("outcome") != "oversized" or not oversized.get("executed"):
            bad.append("oversized retrieved output refusal")

        traces = [json.loads(line) for line in open(trace_path, encoding="utf-8") if line.strip()]
        if not traces or any(set(row) != {
                "ts", "tool", "timing_ms", "byte_count", "outcome"} for row in traces):
            bad.append("metadata-only trace schema")
        trace_text = json.dumps(traces)
        if any(secret in trace_text for secret in ("keep me", "Name#NA1", "Basic ", "arguments")):
            bad.append("trace persisted args/results")

        envelope = context.capture(
            phase="None", lifecycle_hints={"session_id": "tools"}, now=1000,
            collectors={"profile": {"summary": "baseline intentionally incomplete"}},
        )
        provider_prompts = []
        provider_outputs = iter((
            '{"needs_context":{"tool":"profile.recent","arguments":{}}}',
            "Use the safer recent-game pattern.",
        ))

        def retrieve_provider(prompt):
            provider_prompts.append(prompt)
            return next(provider_outputs), None

        retrieved = tools.answer(
            "What pattern should I fix?", envelope, [], "en", retrieve_provider,
            collectors={"profile.recent": lambda: dirty}, trace_path=trace_path)
        if retrieved.get("provider_calls") != 2 or retrieved.get("tool_calls") != 1 \
                or retrieved.get("text") != "Use the safer recent-game pattern.":
            bad.append("one-round retrieval answer")
        if len(provider_prompts) != 2 or "keep me" not in provider_prompts[1] \
                or any(secret in provider_prompts[1] for secret in (
                    "Name#NA1", "x" * 70, "Basic ", r"C:\Users")):
            bad.append("retrieved result second-call sanitization")
        if "profile.recent" not in provider_prompts[0] \
                or "queue.current" in provider_prompts[0] \
                or "explicitly asks you to consult" not in provider_prompts[0] \
                or any(capability in provider_prompts[0].lower() for capability in (
                    "websearch", "webfetch", "shell.run", "filesystem.read")) \
                or "final retrieval round" not in provider_prompts[1]:
            bad.append("phase-only manifest/final-round prompt")

        direct_calls = []
        direct = tools.answer(
            "Can I queue?", envelope, [], "en",
            lambda prompt: (direct_calls.append(prompt) or "Yes.", None),
            collectors={"profile.recent": mock.Mock()}, trace_path=trace_path)
        if direct.get("text") != "Yes." or direct.get("provider_calls") != 1 \
                or direct.get("tool_calls") != 0 or len(direct_calls) != 1:
            bad.append("direct answer provider-call cap")

        blocked_collector = mock.Mock(return_value=dirty)
        invalid_outputs = (
            '```json\n{"needs_context":{"tool":"profile.recent","arguments":{}}}\n```',
            '{"needs_context":[{"tool":"profile.recent","arguments":{}}]}',
            ('{"needs_context":{"tool":"profile.recent","arguments":{}},'
             '"needs_context":{"tool":"profile.recent","arguments":{}}}'),
            '{"needs_context":{"tool":"shell.run","arguments":{}}}',
            '{"needs_context":{"tool":"profile.recent","arguments":{"path":"C:/"}}}',
            '{"needs_context":{"tool":"live.current","arguments":{}}}',
        )
        for output in invalid_outputs:
            blocked_collector.reset_mock()
            refused = tools.answer(
                "Reveal a secret", envelope, [], "en", lambda _prompt, out=output: (out, None),
                collectors={"profile.recent": blocked_collector,
                            "live.current": blocked_collector}, trace_path=trace_path)
            if refused.get("provider_calls") != 1 or refused.get("tool_calls") != 0 \
                    or blocked_collector.called \
                    or refused.get("text") != tools.context_unavailable("en"):
                bad.append("unknown/malformed/arguments/cross-phase refusal")
                break

        recursive_outputs = iter((
            '{"needs_context":{"tool":"profile.recent","arguments":{}}}',
            '{"needs_context":{"tool":"profile.recent","arguments":{}}}',
        ))
        recursive = tools.answer(
            "Try forever", envelope, [], "en",
            lambda _prompt: (next(recursive_outputs), None),
            collectors={"profile.recent": lambda: {"safe": True}}, trace_path=trace_path)
        if recursive.get("provider_calls") != 2 or recursive.get("tool_calls") != 1 \
                or recursive.get("text") != tools.context_unavailable("en"):
            bad.append("recursive/multi-round cap")

        matchup_envelope = context.capture(
            phase="ChampSelect", lifecycle_hints={"session_id": "matchup-tools"}, now=1000,
            collectors={"draft": {"self_champion": "Yasuo", "role": "mid",
                                  "enemies": [{"slot": "enemy_1",
                                               "champion": "Syndra", "role": "mid"}]}},
        )
        matchup_outputs = iter((
            '{"needs_context":{"tool":"matchup.current","arguments":{}}}',
            "Bait the stun, then take a short trade.",
        ))
        matchup_answer = tools.answer(
            "How do I play this lane?", matchup_envelope, [], "en",
            lambda _prompt: (next(matchup_outputs), None),
            collectors={"matchup.current": lambda: {
                "self_champion": "Yasuo", "opponent": "Syndra",
                "cached_guidance": "Bait the stun."}}, trace_path=trace_path)
        if matchup_answer.get("provider_calls") != 2 \
                or matchup_answer.get("tool_calls") != 1 \
                or "short trade" not in matchup_answer.get("text", ""):
            bad.append("missing-matchup retrieval answer")

        legal_none = {row["id"] for row in tools.manifest_for_phase("None")}
        legal_live = {row["id"] for row in tools.manifest_for_phase("InProgress")}
        if legal_none != {"profile.recent"} \
                or legal_live != {"live.current", "matchup.current"}:
            bad.append("phase-filtered public manifest")

        dd = {"ver": "16.15.1", "norm": lambda value: "".join(
                  char for char in str(value).lower() if char.isalnum()),
              "name2id": {"yasuo": 1, "syndra": 2},
              "id2name": {1: "Yasuo", 2: "Syndra"},
              "id2key": {1: "Yasuo", 2: "Syndra"}}
        matchup_path = os.path.join(tmp, "Yasuo_vs_Syndra_mid_1615_en.txt")
        with open(matchup_path, "w", encoding="utf-8") as handle:
            handle.write("Bait Syndra's stun before trading.")
        with mock.patch.object(lolmatchup, "CACHE", tmp), \
                mock.patch.object(lolmatchup.llmcli, "call") as no_provider:
            matchup = lolmatchup.coach_snapshot(dd, "Yasuo", "Syndra", "mid", "en")
        if not matchup or "Bait Syndra" not in matchup.get("cached_guidance", "") \
                or no_provider.called:
            bad.append("matchup cache-only adapter")

        coordinator = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
        coordinator.session = lolcoachsession.CoachSession()
        coordinator.lock = threading.RLock()
        coordinator.cancel_handle = None
        coordinator.provider = "codex"
        coordinator._set = mock.Mock()
        coordinator.show = mock.Mock()
        coordinator._cancel_proactive = mock.Mock(return_value=False)
        coordinator.audio = mock.Mock()
        coordinator.audio.submit.return_value = True
        with mock.patch.object(smitecoach.cfg, "load", return_value={
                "voice_coach": True, "llm_provider": "codex", "dragon_volume": 30}), \
                mock.patch.object(smitecoach.phasecheck, "phase_detailed", return_value="None"), \
                mock.patch.object(smitecoach.lolcoachcontext, "capture", return_value=envelope), \
                mock.patch.object(smitecoach.lolcoachtools, "answer", return_value={
                    "text": "Integrated answer.", "error": None}) as harness_call, \
                mock.patch.object(smitecoach.llmcli, "call") as direct_provider:
            integrated = coordinator.ask("Use missing context")
        if not integrated.get("ok") or not harness_call.called or direct_provider.called \
                or coordinator.session.history()[-1]["assistant"] != "Integrated answer.":
            bad.append("manual coordinator harness integration")

    if bad:
        return FAIL, "; ".join(dict.fromkeys(bad))
    return OK, "seven tools phase-gated, timed, sanitized; retrieval capped at two calls"


def c_coach_proactive():
    """Phase 4 fixtures: lifecycle edges, sparse policy, typed bridge and isolation."""
    import inspect
    import tempfile
    import threading
    from unittest import mock
    import lolcoachproactive as proactive
    import smitecoach
    import smiteconfig as cfg

    bad = []
    clock = [0.0]
    detector = proactive.ProactiveDetector(clock=lambda: clock[0])

    def snap(phase, lifecycle="game-1", sections=None, widget=None, **extra):
        return {"phase": phase, "lifecycle_id": lifecycle,
                "sections": sections or {}, "widget": widget or {},
                "observed_at": clock[0], **extra}

    if detector.observe(snap("None", "client")):
        bad.append("late registration baseline")
    clock[0] = 1
    lobby = detector.observe(snap("Lobby", sections={"queue": {
        "verdict": "STOP", "summary": "cold window", "evidence": ["fixture"]}}))
    if [intent.kind for intent in lobby] != ["queue_warning"]:
        bad.append("Lobby STOP/WAIT edge")
    clock[0] = 2
    if detector.observe(snap("Matchmaking")):
        bad.append("routine matchmaking chatter")
    clock[0] = 3
    draft = detector.observe(snap("ChampSelect", sections={"draft": {
        "role": "MID", "self_champion": "Ahri", "locked": True,
        "enemies": [{"champion": "Zed", "role": "MID"}] + [
            {"champion": name, "role": role} for name, role in
            (("Olaf", "TOP"), ("Lee Sin", "JUNGLE"),
             ("Jinx", "BOTTOM"), ("Nautilus", "UTILITY"))]}}))
    if {intent.kind for intent in draft} != {
            "draft_assignment", "draft_lock", "enemy_lane_reveal", "draft_final_plan"}:
        bad.append("ChampSelect high-value edges")
    hover_detector = proactive.ProactiveDetector(clock=lambda: clock[0])
    hover_detector.observe(snap("None", "hover-client"))
    hover_detector.observe(snap("ChampSelect", "hover-game", {"draft": {
        "role": "MID", "self_champion": "Ahri", "locked": False}}))
    if hover_detector.observe(snap("ChampSelect", "hover-game", {"draft": {
            "role": "MID", "self_champion": "Zed", "locked": False}})):
        bad.append("routine champion-hover chatter")
    clock[0] = 4
    loading = detector.observe(snap("Loading", sections={"loading": {
        "scouted": True, "plan": ["front to back"],
        "win_conditions": {"win": "scale"}}}))
    if [intent.kind for intent in loading] != ["loading_plan"]:
        bad.append("Loading consolidated scout edge")
    clock[0] = 5
    live = detector.observe(snap("InProgress", widget={
        "tempo": {"phase": "TAKE", "objective": "Drake"},
        "guards": {"ward": {"calls": 1, "verdict": "PIT", "quiet": False}},
        "events": [{"kind": "DragonKill", "time": 300.0},
                   {"kind": "ChampionKill", "time": 301.0}],
    }))
    if {intent.kind for intent in live} != {"live_tempo", "guard_ward", "major_event"}:
        bad.append("live typed transition filtering")
    if detector.observe(snap("InProgress", widget={
            "tempo": {"phase": "TAKE", "objective": "Drake"},
            "guards": {"ward": {"calls": 1, "verdict": "PIT", "quiet": False}},
            "events": [{"kind": "DragonKill", "time": 300.0}]})):
        bad.append("live dedupe")
    clock[0] = 6
    post = detector.observe(snap("PostGame", sections={"postgame": {
        "recent_games": [{"champion": "Ahri", "win": True,
                          "in_game_performance_grade": "A"}]}}))
    if [intent.kind for intent in post] != ["postgame_review"]:
        bad.append("post-game review edge")
    clock[0] = 7
    reset = detector.observe(snap("Lobby", "game-2", {"queue": {
        "verdict": "WAIT", "summary": "take ten"}}))
    if [intent.kind for intent in reset] != ["queue_warning"]:
        bad.append("lifecycle reset")

    muted_detector = proactive.ProactiveDetector(clock=lambda: clock[0])
    muted_detector.observe(snap("Lobby", "muted", {"queue": {"verdict": "GO"}}))
    muted_detector.observe(snap("Lobby", "muted", {"queue": {"verdict": "STOP"}}),
                           emit=False)
    if muted_detector.observe(snap("Lobby", "muted", {"queue": {"verdict": "STOP"}})):
        bad.append("muted state replay")
    late = proactive.ProactiveDetector(clock=lambda: clock[0])
    if late.observe(snap("InProgress", "late", widget={
            "events": [{"kind": "BaronKill", "time": 1200}]})):
        bad.append("late registration replay")

    clock[0] = 0
    policy = proactive.ProactivePolicy(
        clock=lambda: clock[0], global_cooldown=60, per_kind_cooldown=120,
        max_per_lifecycle=2, max_per_phase=2, backoff_base=10)

    def intent(kind, priority=1, created=None, ttl=180, phase="InProgress"):
        created = clock[0] if created is None else created
        return proactive.ProactiveIntent(
            kind, phase, priority, created, ttl, f"{kind}:{created}", f"fixture:{kind}")

    low, high = intent("low", 1), intent("high", 3)
    if policy.offer(low, "life") != "queued" or policy.offer(high, "life") != "replaced" \
            or policy.pop_ready() != high:
        bad.append("one-item priority replacement")
    clock[0] = 30
    second = intent("second", 2)
    policy.offer(second, "life")
    if policy.pop_ready() is not None:
        bad.append("global cooldown")
    clock[0] = 61
    if policy.pop_ready() != second:
        bad.append("cooldown release")
    if policy.offer(intent("third", 3), "life") != "max_lifecycle":
        bad.append("explicit positive lifecycle cap")

    clock[0] = 0
    unlimited = proactive.ProactivePolicy(
        clock=lambda: clock[0], global_cooldown=0, per_kind_cooldown=0)
    unlimited_reasons = []
    for number in range(7):
        row = intent(f"unlimited_{number}", phase="InProgress")
        unlimited_reasons.append(unlimited.offer(row, "unlimited"))
        if unlimited.pop_ready() is not row:
            unlimited_reasons.append("not_ready")
    if any(reason not in ("queued",) for reason in unlimited_reasons) \
            or unlimited.calls != 7 or unlimited.phase_calls.get("InProgress") != 7:
        bad.append("unlimited lifecycle and phase counts")

    phase_cap = proactive.ProactivePolicy(
        clock=lambda: clock[0], global_cooldown=0, per_kind_cooldown=0,
        max_per_lifecycle=0, max_per_phase=2)
    for number in range(2):
        row = intent(f"phase_cap_{number}", phase="Lobby")
        phase_cap.offer(row, "phase-cap")
        phase_cap.pop_ready()
    if phase_cap.offer(intent("phase_cap_third", phase="Lobby"), "phase-cap") != "max_phase":
        bad.append("explicit positive phase cap")

    clock[0] = 0
    suppressed = proactive.ProactivePolicy(clock=lambda: clock[0])
    muted_intent = intent("muted")
    if suppressed.offer(muted_intent, "life", muted=True) != "muted" \
            or suppressed.offer(muted_intent, "life") != "duplicate":
        bad.append("muted policy advancement")
    stale_intent = intent("stale")
    if suppressed.offer(stale_intent, "life", stale=True) != "stale" \
            or suppressed.offer(stale_intent, "life") != "duplicate":
        bad.append("stale suppression/replay")
    uncertain_intent = intent("uncertain")
    if suppressed.offer(uncertain_intent, "life", uncertain=True) != "uncertain" \
            or suppressed.offer(uncertain_intent, "life") != "duplicate":
        bad.append("uncertain phase suppression/replay")
    zero_intent = intent("zero", phase="Loading")
    if suppressed.offer(zero_intent, "life", loading_zero=True) != "loading_zero" \
            or suppressed.offer(zero_intent, "life") != "duplicate":
        bad.append("zero-clock suppression/replay")
    expired = intent("expired", created=-10, ttl=5)
    if suppressed.offer(expired, "life") != "expired":
        bad.append("TTL expiry")

    recovery = proactive.ProactivePolicy(
        clock=lambda: clock[0], global_cooldown=0, per_kind_cooldown=0,
        backoff_base=10, backoff_cap=40)
    recovery.offer(intent("initial"), "life")
    recovery.pop_ready()
    delay = recovery.record_failure()
    recovery.offer(intent("recover"), "life")
    if delay != 10 or recovery.pop_ready() is not None:
        bad.append("provider/TTS backoff")
    clock[0] = 10
    if recovery.pop_ready() is None:
        bad.append("scheduler recovery after failure")
    recovery.record_success()
    if recovery.failures or recovery.backoff_until > clock[0]:
        bad.append("success clears backoff")

    with tempfile.TemporaryDirectory(prefix="smiteless-proactive-") as tmp:
        state_path = os.path.join(tmp, "widget.json")
        with mock.patch.object(proactive, "WIDGET_STATE_FILE", state_path):
            if not proactive.publish_widget_state(
                    302, {"phase": "TAKE", "obj": "Drake"},
                    {"ward": {"calls": 1, "verdict": "PIT", "quiet": False}},
                    [{"EventName": "DragonKill", "EventTime": 300,
                      "KillerName": "Secret#NA1"},
                     {"EventName": "ChampionKill", "EventTime": 301}], now=100):
                bad.append("typed widget publication")
            bridge = proactive.read_widget_state(now=102)
            encoded = json.dumps(bridge)
            if bridge.get("tempo", {}).get("phase") != "TAKE" \
                    or bridge.get("events") != [{"kind": "DragonKill", "time": 300.0}] \
                    or "Secret" in encoded or "ChampionKill" in encoded:
                bad.append("widget allowlist/privacy")
            if proactive.read_widget_state(now=110).get("_unavailable") != "stale":
                bad.append("widget freshness")

    manual = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    manual.lock = threading.RLock()
    manual.proactive_policy = proactive.ProactivePolicy(clock=lambda: 0)
    queued = proactive.ProactiveIntent(
        "manual", "Lobby", 1, 0, 30, "manual:1", "fixture:manual")
    manual.proactive_policy.offer(queued, "life")
    manual.proactive_handle = mock.Mock()
    manual.audio = mock.Mock()
    manual.audio.cancel_proactive.return_value = True
    manual._set = mock.Mock()
    with mock.patch.object(proactive, "log_event"):
        cancelled = manual._cancel_proactive("manual_question")
    if not manual.proactive_handle is None or manual.proactive_policy.queued is not None:
        bad.append("manual interaction drops proactive work")
    if not cancelled or not manual.audio.cancel_proactive.called:
        bad.append("active proactive audio cancellation")
    source = inspect.getsource(smitecoach.Coordinator._run_proactive)
    if "self.session" in source or "build_prompt(question, envelope, [], locale)" not in source:
        bad.append("proactive conversation-history isolation")

    runner = smitecoach.Coordinator.__new__(smitecoach.Coordinator)
    runner.lock = threading.RLock()
    runner.cancel_handle = None
    runner.proactive_handle = None
    runner.state = "idle"
    runner._coach_dd = None
    runner.proactive_spoken = 0
    runner._set = mock.Mock()
    runner.show = mock.Mock()
    runner.proactive_policy = proactive.ProactivePolicy(
        clock=lambda: clock[0], global_cooldown=0, per_kind_cooldown=0)
    run_intent = proactive.ProactiveIntent(
        "queue_warning", "Lobby", 3, clock[0], 120,
        "run:1", "queue:stop")

    class ImmediateAudio:
        def submit(self, job):
            job.callback({"ok": True})
            return True

    runner.audio = ImmediateAudio()
    settings = {"llm_provider": "codex", "dragon_volume": 30}
    with mock.patch.object(smitecoach.phasecheck, "phase_detailed", return_value="Lobby"), \
            mock.patch.object(smitecoach.lolcoachcontext, "capture", return_value={"phase": "Lobby"}), \
            mock.patch.object(smitecoach.lolcoachprompt, "build_prompt", return_value="prompt"), \
            mock.patch.object(smitecoach.cfg, "load", return_value=settings), \
            mock.patch.object(smitecoach.llmcli, "call",
                              side_effect=[(None, "provider failed"), ("short tip", None)]), \
            mock.patch.object(proactive, "log_event"):
        runner._run_proactive(run_intent)
        failed_count = runner.proactive_policy.failures
        runner._run_proactive(proactive.ProactiveIntent(
            "queue_warning", "Lobby", 3, clock[0], 120,
            "run:2", "queue:wait"))
    if failed_count != 1 or runner.proactive_policy.failures \
            or runner.proactive_spoken != 1:
        bad.append("provider failure isolation/TTS recovery")

    real_path = cfg.PATH
    with tempfile.TemporaryDirectory(prefix="smiteless-proactive-config-") as tmp:
        cfg.PATH = os.path.join(tmp, "settings.json")
        try:
            missing = cfg.load()
            with open(cfg.PATH, "w", encoding="utf-8") as handle:
                json.dump({"proactive_max_per_game": 6}, handle)
            legacy = cfg.load()
            saved = cfg.save({"proactive_max_per_game": 6})
        finally:
            cfg.PATH = real_path
    if missing.get("proactive_global_cooldown") != 60 \
            or missing.get("proactive_max_per_game") != 0 \
            or legacy.get("proactive_max_per_game") != 0 \
            or saved.get("proactive_max_per_game") != 0:
        bad.append("unlimited config migration/default")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, ("lifecycle intents/reset; injected-clock TTL/cooldown/dedupe/queue/guards/backoff; "
                "typed widget bridge; manual/history isolation pass")


def c_voice_audio():
    """Completed locale voices/cache, audio arbitration and hotkey contracts."""
    import tempfile
    import threading
    import wave
    from pathlib import Path
    from unittest import mock
    import smiteaudio
    import smitestt

    bad = []
    if smitestt.locale_to_culture("en") != "en-US" \
            or smitestt.locale_to_culture("pt_BR") != "pt-BR" \
            or smitestt.BACKEND_LOCAL != "faster_whisper":
        bad.append("local STT locale/backend mapping")
    if smiteaudio.voice_for_locale("en") != "Salli" \
            or smiteaudio.voice_for_locale("pt_BR") != "Camila" \
            or smiteaudio.culture_for_locale("pt_BR") != "pt-BR":
        bad.append("online/SAPI locale selection")
    a = smiteaudio.cache_identity("Take it", "en", volume=30)
    b = smiteaudio.cache_identity("Pegue", "pt_BR", volume=30)
    c = smiteaudio.cache_identity("Take it!", "en", volume=30)
    if len({a, b, c}) != 3 or "Salli" not in a or "Camila" not in b:
        bad.append("locale/text audio cache isolation")

    fake_winsound = type("FakeWinsound", (), {
        "SND_FILENAME": 0x00020000,
        "SND_NODEFAULT": 0x0002,
        "calls": [],
        "PlaySound": classmethod(lambda cls, path, flags: cls.calls.append((path, flags))),
    })
    smiteaudio._winsound_play("fixture.wav", fake_winsound)
    if fake_winsound.calls != [("fixture.wav", 0x00020002)] \
            or hasattr(fake_winsound, "SND_SYNC"):
        bad.append("Python 3.13 winsound synchronous-default compatibility")

    with tempfile.TemporaryDirectory(prefix="smiteless-audio-fixture-") as tmp:
        wav_path = Path(tmp) / "fixture.wav"
        mp3_path = Path(tmp) / "fixture.mp3"
        mp3_path.write_bytes(b"fixture-mp3")
        with wave.open(str(wav_path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(b"\x00\x00" * 320)
        sapi_value = {"ok": True, "path": str(wav_path), "renderer": "sapi",
                      "culture": "pt-BR", "voice": "Fixture voice"}

        invalid_wav = Path(tmp) / "invalid.wav"
        invalid_wav.write_bytes(b"not-wave-audio")
        with mock.patch.object(smiteaudio, "_winsound_play") as invalid_winsound, \
                mock.patch.object(smiteaudio, "_mci") as invalid_mci:
            invalid_result = smiteaudio._play_file_result(str(invalid_wav), 30)
        if invalid_result.get("error") != "playback_error" \
                or invalid_result.get("stage") != "wav_validate" \
                or invalid_winsound.called or invalid_mci.called:
            bad.append("invalid WAV rejected before playback")

        online_commands = []

        def online_mci(command):
            online_commands.append(command)
            return 0

        with mock.patch.object(smiteaudio, "cleanup_cache"), \
                mock.patch.object(smiteaudio, "render_online", return_value=str(mp3_path)), \
                mock.patch.object(smiteaudio, "render_sapi") as sapi_probe, \
                mock.patch.object(smiteaudio, "_mci", side_effect=online_mci):
            online_success = smiteaudio.speak(
                "fixture", "private fixture speech", 30, "en", "test")
        if not online_success.get("ok") or online_success.get("renderer") != "ttsmp3" \
                or sapi_probe.called or not any(command.startswith("close ")
                                                for command in online_commands):
            bad.append("online MP3 success without SAPI")

        with mock.patch.object(smiteaudio, "cleanup_cache"), \
                mock.patch.object(smiteaudio, "render_online", return_value=None), \
                mock.patch.object(smiteaudio, "render_sapi", return_value=sapi_value), \
                mock.patch.object(smiteaudio, "_winsound_play", return_value=None):
            local_fallback = smiteaudio.speak(
                "fixture", "private fixture speech", 30, "pt_BR", "test")
        attempts = local_fallback.get("attempts", [])
        if not local_fallback.get("ok") or local_fallback.get("renderer") != "sapi" \
                or attempts[0].get("error") != "online_unavailable" \
                or attempts[-1].get("stage") != "wav_winsound":
            bad.append("online failure/SAPI winsound success structured result")
        if "path" in str(local_fallback).lower() \
                or "private fixture speech" in str(local_fallback):
            bad.append("audio result leaked path or speech")

        with mock.patch.object(smiteaudio, "cleanup_cache"), \
                mock.patch.object(smiteaudio, "render_online", return_value=str(mp3_path)), \
                mock.patch.object(smiteaudio, "render_sapi", return_value=sapi_value), \
                mock.patch.object(smiteaudio, "_winsound_play", return_value=None), \
                mock.patch.object(smiteaudio, "_mci", return_value=1):
            mp3_fallback = smiteaudio.speak(
                "fixture", "private fixture speech", 30, "pt_BR", "test")
        if not mp3_fallback.get("ok") or mp3_fallback.get("renderer") != "sapi" \
                or not any(row.get("stage") == "mp3_open" and not row.get("ok")
                           for row in mp3_fallback.get("attempts", [])):
            bad.append("MP3 playback failure/SAPI fallback")

        wav_commands = []

        def wav_mci(command):
            wav_commands.append(command)
            return 0

        with mock.patch.object(smiteaudio, "cleanup_cache"), \
                mock.patch.object(smiteaudio, "render_online", return_value=None), \
                mock.patch.object(smiteaudio, "render_sapi", return_value=sapi_value), \
                mock.patch.object(smiteaudio, "_winsound_play",
                                  side_effect=OSError("fixture player failure")), \
                mock.patch.object(smiteaudio, "_mci", side_effect=wav_mci):
            mci_fallback = smiteaudio.speak(
                "fixture", "private fixture speech", 30, "pt_BR", "test")
        stages = [row.get("stage") for row in mci_fallback.get("attempts", [])]
        if not mci_fallback.get("ok") or stages[-2:] != ["wav_winsound", "wav_mci_play"] \
                or not any(command.startswith("close ") for command in wav_commands) \
                or smiteaudio._active_aliases:
            bad.append("winsound failure/MCI WAV fallback and cleanup")

        with mock.patch.object(smiteaudio, "cleanup_cache"), \
                mock.patch.object(smiteaudio, "render_online", return_value=str(mp3_path)), \
                mock.patch.object(smiteaudio, "render_sapi", return_value=sapi_value), \
                mock.patch.object(smiteaudio, "_winsound_play",
                                  side_effect=OSError("fixture player failure")), \
                mock.patch.object(smiteaudio, "_mci", return_value=1):
            failed_players = smiteaudio.speak(
                "fixture", "private fixture speech", 30, "en", "test")
        if failed_players.get("ok") or failed_players.get("error") != "playback_error" \
                or failed_players.get("stage") != "wav_mci_open" \
                or smiteaudio._active_aliases:
            bad.append("all audio players terminal playback error")

    with mock.patch.object(smiteaudio, "cleanup_cache"), \
            mock.patch.object(smiteaudio, "render_online", return_value=None), \
            mock.patch.object(smiteaudio, "render_sapi",
                              return_value={"ok": False, "error": "missing_voice"}):
        failed_renderers = smiteaudio.speak(
            "fixture", "private fixture speech", 30, "en", "test")
    if failed_renderers.get("ok") or failed_renderers.get("error") != "missing_voice" \
            or failed_renderers.get("stage") != "sapi_render":
        bad.append("dual-renderer terminal structured cause")

    with mock.patch.object(smiteaudio, "render_online") as online_probe, \
            mock.patch.object(smiteaudio, "render_sapi") as sapi_probe:
        silent = smiteaudio.speak("fixture", "private fixture speech", 0, "en", "test")
    if silent.get("ok") or silent.get("error") != "silent" \
            or online_probe.called or sapi_probe.called:
        bad.append("silent preflight without rendering")
    if set(smiteaudio.AUDIO_ERRORS) != {
            "silent", "online_unavailable", "missing_voice", "sapi_error", "timeout",
            "playback_error", "speaker_error"}:
        bad.append("stable audio error catalog")

    played, stopped = [], []
    started, release = threading.Event(), threading.Event()

    def speaker(name, text, volume, locale, kind):
        played.append((name, kind))
        if name == "hold":
            started.set()
            release.wait(2)
        return {"ok": True, "renderer": "fake"}

    scheduler = smiteaudio.AudioScheduler(
        speaker=speaker,
        chime_player=lambda value, volume: played.append((f"chime-{value}", "cue")) or
        {"ok": True}, stopper=lambda: stopped.append("stop"))
    scheduler.submit(smiteaudio.AudioJob(smiteaudio.Priority.MANUAL_RESPONSE,
                                         name="hold", text="answer"))
    if not started.wait(1):
        bad.append("audio scheduler worker")
    scheduler.submit(smiteaudio.AudioJob(smiteaudio.Priority.PROACTIVE_RESPONSE,
                                         name="old", text="old"))
    scheduler.submit(smiteaudio.AudioJob(smiteaudio.Priority.PROACTIVE_RESPONSE,
                                         name="new", text="new"))
    if not scheduler.cancel_proactive() or any(
            job.priority == smiteaudio.Priority.PROACTIVE_RESPONSE
            for job in scheduler.pending):
        bad.append("explicit proactive queue cancellation")
    scheduler.submit(smiteaudio.AudioJob(smiteaudio.Priority.DETERMINISTIC_ALERT,
                                         name="alert", text="alert"))
    release.set()
    deadline = time.monotonic() + 2
    while scheduler.current is not None or scheduler.pending:
        if time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    if [name for name, _kind in played] != ["hold", "alert"]:
        bad.append("manual/deterministic/proactive priority")
    scheduler.submit(smiteaudio.AudioJob(smiteaudio.Priority.PROACTIVE_RESPONSE,
                                         name="queued", text="queued"))
    scheduler.stop_listening()
    during = smiteaudio.AudioJob(smiteaudio.Priority.DETERMINISTIC_ALERT,
                                 name="during-listening", text="wait")
    scheduler.submit(during)
    proactive_accepted = scheduler.submit(smiteaudio.AudioJob(
        smiteaudio.Priority.PROACTIVE_RESPONSE, name="during-proactive", text="drop"))
    time.sleep(0.05)
    if not stopped or not scheduler.listening \
            or any(job.priority == smiteaudio.Priority.PROACTIVE_RESPONSE
                   for job in scheduler.pending) \
            or proactive_accepted \
            or any(name == "during-listening" for name, _kind in played):
        bad.append("listening preemption")
    scheduler.finish_listening()
    deadline = time.monotonic() + 1
    while scheduler.current is not None or scheduler.pending:
        if time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    if not any(name == "during-listening" for name, _kind in played):
        bad.append("post-listening deterministic release")
    scheduler.close()

    exception_results = []
    exception_done = threading.Event()

    def exception_speaker(name, *_args):
        if name == "explode":
            raise RuntimeError("private speaker fixture")
        return {"ok": True, "renderer": "fixture"}

    def exception_callback(result):
        exception_results.append(result)
        if len(exception_results) == 2:
            exception_done.set()

    resilient = smiteaudio.AudioScheduler(
        speaker=exception_speaker, chime_player=lambda *_args: {"ok": True},
        stopper=lambda: None)
    resilient.submit(smiteaudio.AudioJob(
        smiteaudio.Priority.MANUAL_RESPONSE, name="explode", text="private",
        callback=exception_callback))
    resilient.submit(smiteaudio.AudioJob(
        smiteaudio.Priority.MANUAL_RESPONSE, name="after", text="private",
        callback=exception_callback))
    exception_done.wait(1)
    resilient.close()
    if len(exception_results) != 2 \
            or exception_results[0].get("error") != "speaker_error" \
            or not exception_results[1].get("ok") \
            or "private" in str(exception_results[0]):
        bad.append("speaker exception callback/scheduler survival")

    with mock.patch.object(smiteaudio, "coordinator_request", return_value=None), \
            mock.patch.object(smiteaudio, "speak",
                              return_value={"ok": True, "renderer": "local"}) as local_speak:
        fallback = smiteaudio.deterministic_speech("ward", "Ward it.", 30, "en")
    if not fallback.get("ok") or not local_speak.called:
        bad.append("coordinator-unavailable local fallback")

    launcher_paths = (os.path.join(_ROOT, "dist", "tray.ahk"),
                      os.path.join(_ROOT, "smiteless.ahk"),
                      os.path.join(_ROOT, "tools", "smiteless_tray.py"))
    texts = [open(path, encoding="utf-8").read() for path in launcher_paths]
    if not all("coach toggle" in text or '"coach", "toggle"' in text for text in texts) \
            or not all(("^!c" in text) for text in texts[:2]) \
            or "VK_C" not in texts[2] or "Ask coach" not in "".join(texts):
        bad.append("Ctrl+Alt+C/menu launcher contract")
    if bad:
        return FAIL, "; ".join(bad)
    return OK, "local STT mapping, locale voice/cache, arbitration and hotkey fixtures pass"


def _historical_modern_stt_probe():
    """Phase 3A source/package contract; never registers identity or opens the microphone."""
    import subprocess
    import xml.etree.ElementTree as et

    probe_dir = os.path.join(_ROOT, "tools", "stt_winrt_probe")
    paths = {
        "source": os.path.join(probe_dir, "SmitelessSttProbe.cs"),
        "api_surface": os.path.join(probe_dir, "SpeechRecognizerApiSurfaceProbe.cs"),
        "desktop": os.path.join(probe_dir, "SmitelessSttProbe.exe.manifest"),
        "unpackaged": os.path.join(probe_dir, "SmitelessSttProbe.Unpackaged.exe.manifest"),
        "package": os.path.join(probe_dir, "Package.appxmanifest"),
        "build": os.path.join(probe_dir, "build-probe.ps1"),
        "readme": os.path.join(probe_dir, "README.md"),
        "production_build": os.path.join(_ROOT, "dist", "build-stt-package.ps1"),
        "production_lifecycle": os.path.join(_ROOT, "dist", "stt-package.ps1"),
        "app_build": os.path.join(_ROOT, "dist", "build.ps1"),
        "release": os.path.join(_ROOT, "dist", "make-release.ps1"),
        "installer": os.path.join(_ROOT, "dist", "installer.ahk"),
    }
    missing = [name for name, path in paths.items() if not os.path.isfile(path)]
    if missing:
        return FAIL, "missing modern STT probe files: " + ", ".join(missing)

    source = open(paths["source"], encoding="utf-8").read()
    required_source = (
        "SupportedTopicLanguages", "SupportedGrammarLanguages", "capture_started",
        "RecognizeAsync", "CompileConstraintsAsync", "missing_package_identity",
        "SpeechRecognitionConfidence.Low", "SpeechRecognitionConfidence.Rejected",
        "network_unavailable", "microphone_unavailable", "permission_denied",
        "online_speech_disabled", "AudioQualityFailure", "GetCurrentPackageFullName",
        "new UTF8Encoding(false)", "alternateResults == null",
        "SMITELESS_STT_PROBE_CUE", "MediaDevice.GetDefaultAudioCaptureId",
        '"capture_mode", "windows_default"', '"explicit_endpoint_binding", false',
    )
    absent = [token for token in required_source if token not in source]
    if absent:
        return FAIL, "modern STT source contract missing: " + ", ".join(absent)

    api_surface_source = open(paths["api_surface"], encoding="utf-8").read()
    required_api_surface = (
        "typeof(SpeechRecognizer)", "typeof(MediaCaptureInitializationSettings)",
        "recognizer_has_writable_input_member", "recognizer_has_input_parameter",
        "media_capture_has_audio_device_id", "explicit_endpoint_binding_supported",
    )
    absent = [token for token in required_api_surface if token not in api_surface_source]
    if absent:
        return FAIL, "STT API-surface probe contract missing: " + ", ".join(absent)

    ns = {
        "f": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
        "uap": "http://schemas.microsoft.com/appx/manifest/uap/windows10",
        "uap10": "http://schemas.microsoft.com/appx/manifest/uap/windows10/10",
        "rescap": "http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities",
        "msix": "urn:schemas-microsoft-com:msix.v1",
    }
    package = et.parse(paths["package"]).getroot()
    identity = package.find("f:Identity", ns)
    app = package.find("f:Applications/f:Application", ns)
    microphone = package.find("f:Capabilities/f:DeviceCapability[@Name='microphone']", ns)
    run_full = package.find("f:Capabilities/rescap:Capability[@Name='runFullTrust']", ns)
    unvirtualized = package.find(
        "f:Capabilities/rescap:Capability[@Name='unvirtualizedResources']", ns)
    allow_external = package.find("f:Properties/uap10:AllowExternalContent", ns)
    if identity is None or app is None or microphone is None or run_full is None \
            or unvirtualized is None or allow_external is None \
            or (allow_external.text or "").strip().lower() != "true":
        return FAIL, "sparse package identity/capability contract"
    uap10 = "{%s}" % ns["uap10"]
    if app.get(uap10 + "RuntimeBehavior") != "win32App" \
            or app.get(uap10 + "TrustLevel") != "mediumIL":
        return FAIL, "sparse package Win32 runtime/trust contract"

    desktop = et.parse(paths["desktop"]).getroot()
    msix = desktop.find("msix:msix", ns)
    if msix is None or msix.get("packageName") != identity.get("Name") \
            or msix.get("publisher") != identity.get("Publisher") \
            or msix.get("applicationId") != app.get("Id"):
        return FAIL, "desktop/package identity fields diverge"

    build_text = open(paths["build"], encoding="utf-8").read()
    if "/nv" not in build_text or any(token in build_text for token in (
            "Add-AppxPackage", "New-SelfSignedCertificate", "Import-Certificate",
            "Remove-AppxPackage")):
        return FAIL, "probe build must pack external identity without registering/trusting it"

    production_build = open(paths["production_build"], encoding="utf-8").read()
    required_production_build = (
        'packageName = "Smiteless.Stt"', "CertificateThumbprint", "HasPrivateKey",
        "1.3.6.1.5.5.7.3.3", "makeappx.exe", "signtool.exe", "/nv",
        "Get-AuthenticodeSignature", "Package.appxmanifest",
        "SmitelessSttProbe.exe.manifest",
        'publisher -eq "CN=Smiteless Development"',
    )
    absent = [token for token in required_production_build if token not in production_build]
    if absent or any(token in production_build for token in (
            "New-SelfSignedCertificate", "Import-Certificate", "Add-AppxPackage")):
        return FAIL, "production STT signing gate: " + ", ".join(absent)

    lifecycle = open(paths["production_lifecycle"], encoding="utf-8").read()
    required_lifecycle = (
        'packageName = "Smiteless.Stt"', "Get-AuthenticodeSignature",
        "SignerCertificate.Subject", "Add-AppxPackage", "-ExternalLocation",
        "-ForceUpdateFromAnyVersion", "Remove-AppxPackage", "Get-AppxPackage",
        'Subject -eq "CN=Smiteless Development"',
    )
    absent = [token for token in required_lifecycle if token not in lifecycle]
    if absent or any(token in lifecycle for token in (
            "New-SelfSignedCertificate", "Import-Certificate")):
        return FAIL, "production STT registration gate: " + ", ".join(absent)

    app_build = open(paths["app_build"], encoding="utf-8").read()
    release = open(paths["release"], encoding="utf-8").read()
    installer = open(paths["installer"], encoding="utf-8").read()
    if "build-stt-package.ps1" not in app_build or "RequireSttPackage" not in app_build \
            or 'stage "app\\stt"' not in app_build \
            or "stt-package.ps1" not in app_build:
        return FAIL, "frozen build does not stage the signed STT contract"
    if "SttCertificateThumbprint" not in release or "RequireSttPackage" not in release:
        return FAIL, "release path can bypass the signed STT packaging gate"
    required_installer = (
        "ConfigureStt", "RestoreStt", "smiteless_stt_backup_", "Smiteless.Stt.msix",
        'RunSttLifecycle(sttScript, "Uninstall"', "previous speech package was restored",
    )
    absent = [token for token in required_installer if token not in installer]
    if absent:
        return FAIL, "installer STT upgrade/rollback/uninstall contract: " + ", ".join(absent)

    exe = os.path.join(_ROOT, "build", "stt-probe", "SmitelessSttProbe.Unpackaged.exe")
    api_surface_exe = os.path.join(
        _ROOT, "build", "stt-probe", "SpeechRecognizerApiSurfaceProbe.exe")
    if os.path.isfile(api_surface_exe):
        surface_child = subprocess.run([api_surface_exe], capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=10)
        try:
            surface = json.loads(surface_child.stdout)
        except json.JSONDecodeError:
            return FAIL, "built STT API-surface probe emitted malformed JSON"
        if surface_child.returncode or not surface.get("ok") \
                or surface.get("media_capture_has_audio_device_id") is not True \
                or not isinstance(surface.get("explicit_endpoint_binding_supported"), bool):
            return FAIL, "built STT API-surface JSON contract"
    if os.path.isfile(exe):
        child = subprocess.run([exe, "readiness", "pt-BR"], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=10)
        try:
            value = json.loads(child.stdout)
        except json.JSONDecodeError:
            return FAIL, "built modern STT readiness emitted malformed JSON"
        if not value.get("ok") or value.get("command") != "readiness" \
                or value.get("backend") != "windows_media_speech" \
                or value.get("capture_started") is not False \
                or not isinstance(value.get("supported_topic_languages"), list):
            return FAIL, "built modern STT readiness JSON contract"
        if not value.get("package_identity"):
            refusal = subprocess.run([exe, "recognize", "pt-BR", "1000"],
                                     capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=10)
            try:
                refused = json.loads(refusal.stdout)
            except json.JSONDecodeError:
                return FAIL, "unpackaged recognition refusal emitted malformed JSON"
            if refusal.returncode != 2 or refused.get("error") != "missing_package_identity":
                return FAIL, "unpackaged helper must refuse recognition before microphone access"
        return OK, ("modern STT helper + sparse manifest; package_identity="
                    f"{value.get('package_identity')}, pt-BR={value.get('topic_supported')}")
    return OK, "modern STT helper + sparse manifest source contracts (helper not built)"


def c_frozen_whisper_runtime():
    """Phase 3H frozen/local runtime contract; never captures, loads or downloads a model."""
    import subprocess

    bad = []
    paths = {
        "requirements": os.path.join(_ROOT, "requirements.txt"),
        "build": os.path.join(_ROOT, "dist", "build.ps1"),
        "release": os.path.join(_ROOT, "dist", "make-release.ps1"),
        "installer": os.path.join(_ROOT, "dist", "installer.ahk"),
        "entry": os.path.join(_ROOT, "smiteless_main.py"),
        "stt": os.path.join(_ROOT, "core", "smitestt.py"),
        "settings": os.path.join(_ROOT, "ui", "smitesettings.py"),
    }
    sources = {name: open(path, encoding="utf-8").read()
               for name, path in paths.items()}
    build = sources["build"]
    required_build = (
        '"smitemicworker","smitewhisperworker"',
        '"--collect-all","faster_whisper"',
        '"--collect-binaries","ctranslate2"',
        '"--collect-binaries","_sounddevice_data"',
        '"--copy-metadata","ctranslate2"',
        '"--copy-metadata","sounddevice"',
        'assets\\whisper-small-manifest.json',
        '"--console","--hide-console","hide-early"',
    )
    absent = [token for token in required_build if token not in build]
    if absent:
        bad.append("frozen runtime collection missing: " + ", ".join(absent))
    if "__stt-mic-worker" not in sources["entry"] \
            or "__stt-whisper-worker" not in sources["entry"] \
            or "getattr(sys, \"frozen\", False)" not in sources["stt"]:
        bad.append("frozen private-worker dispatch")
    for requirement in ("faster-whisper==1.2.1", "ctranslate2==4.8.1",
                        "sounddevice==0.5.5"):
        if requirement not in sources["requirements"]:
            bad.append("unpinned runtime: " + requirement)
    forbidden = (
        "Windows.Media.SpeechRecognition", "System.Speech", "Add-AppxPackage",
        "Smiteless.Stt", "SttCertificateThumbprint", "RequireSttPackage",
        "build-stt-package.ps1", "stt-package.ps1",
    )
    active = "\n".join(sources.values())
    leaked = [token for token in forbidden if token in active]
    if leaked:
        bad.append("legacy speech product path remains: " + ", ".join(leaked))
    for stale in (os.path.join(_ROOT, "dist", "build-stt-package.ps1"),
                  os.path.join(_ROOT, "dist", "stt-package.ps1")):
        if os.path.exists(stale):
            bad.append("legacy production script still exists: " + os.path.basename(stale))

    frozen = os.environ.get("SMITELESS_FROZEN_EXE", "").strip()
    if frozen:
        if not os.path.isfile(frozen):
            bad.append("SMITELESS_FROZEN_EXE does not exist")
        else:
            requests = (
                ("__stt-mic-worker", {"version": 1, "command": "readiness"},
                 lambda row: row.get("ok") and row.get("capture_started") is False),
                ("__stt-whisper-worker", {"version": 1, "command": "readiness"},
                 lambda row: row.get("ok") and row.get("model_loaded") is False
                 and row.get("download_started") is False
                 and (row.get("runtime") or {}).get("ok") is True
                 and (row.get("runtime") or {}).get("pointer_bits") == 64
                 and all((row.get("packages") or {}).get(name)
                         for name in ("faster-whisper", "ctranslate2"))),
            )
            for command, request, validate in requests:
                try:
                    child = subprocess.run(
                        [frozen, command], input=json.dumps(request) + "\n",
                        capture_output=True, text=True, encoding="utf-8", errors="replace",
                        timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    row = json.loads((child.stdout or "").strip())
                    if not validate(row):
                        bad.append(command + " readiness contract")
                except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
                    bad.append(command + " frozen startup")
    if bad:
        return FAIL, "; ".join(bad)
    detail = "collection/dispatch/legacy-removal contracts pass"
    if frozen:
        detail += "; frozen DLL imports and no-load readiness pass"
    return OK, detail


def c_local_whisper_probe():
    """Active Phase 3A: local Whisper readiness/refusal without model/network access."""
    import tempfile
    from unittest import mock
    import whisper_probe as probe

    bad = []
    if probe.MODEL_NAME != "small" or not probe.MODEL_ID.endswith("faster-whisper-small") \
            or len(probe.MODEL_REVISION) != 40:
        bad.append("multilingual small model pin")
    for forbidden in ("small.en", "base", "medium"):
        try:
            probe.validate_model_name(forbidden)
            bad.append(f"accepted forbidden model {forbidden}")
        except probe.ProbeError:
            pass

    with tempfile.TemporaryDirectory(prefix="smiteless-whisper-fixture-") as tmp:
        local = os.path.join(tmp, "Local")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": local}, clear=False):
            root = probe.model_root()
            expected = os.path.join(local, "Smiteless", "models", "whisper-small")
            if os.path.normcase(str(root)) != os.path.normcase(os.path.abspath(expected)):
                bad.append("shared LocalAppData model root")
            ready = probe.readiness()
        model = ready.get("model", {})
        if model.get("state") != "missing" or ready.get("model_loaded") is not False \
                or ready.get("download_started") is not False:
            bad.append("missing-model readiness performed work")
        if ready.get("cpu", {}).get("selected") != "int8" \
                or not isinstance(ready.get("cuda", {}).get("compute_types"), list):
            bad.append("CPU/CUDA readiness contract")
        if ready.get("packages", {}).get("ctranslate2") is None \
                and ready.get("error") != "ctranslate2_not_installed":
            bad.append("absent dependency diagnostic")

    source = open(os.path.join(_ROOT, "tools", "whisper_probe.py"), encoding="utf-8").read()
    cloud_tokens = ("api.openai.com", "gpt-4o-transcribe", "requests.post(",
                    "Windows.Media.SpeechRecognition", "System.Speech")
    if any(token in source for token in cloud_tokens):
        bad.append("cloud/legacy STT path in local probe")
    if "device=None" not in source or "local_files_only=True" not in source:
        bad.append("default-microphone/offline model contract")
    if "capture_beep(880, 250)" not in source or "capture_beep(440, 180)" not in source:
        bad.append("microphone start/end beep contract")
    if "cpu_fallback" not in source or "without CPU fallback" not in source:
        bad.append("explicit GPU failure contract")
    cuda_error = probe.actionable_runtime_error(
        RuntimeError("Library cublas64_12.dll is not found or cannot be loaded"))
    if "CUDA 12" not in cuda_error or "cuDNN 9" not in cuda_error:
        bad.append("actionable CUDA runtime diagnostic")
    if bad:
        return FAIL, "; ".join(bad)
    return OK, "multilingual small pin; no-load readiness; CPU/GPU/refusal contracts pass"


def c_whisper_model_manager():
    """Active Phase 3B: trusted tiny-file cache/lock/download fixtures, never network."""
    import copy
    import hashlib
    import tempfile
    import threading
    from pathlib import Path
    from unittest import mock
    import smitewhispermodel as model

    bad = []
    blobs = {
        "config.json": b'{"fixture":1}\n',
        "model.bin": b"tiny-model-fixture\x00\x01",
        "tokenizer.json": b'{"tokens":["dragao","dragon"]}\n',
        "vocabulary.txt": b"dragao\ndragon\nlee sin\n",
    }

    def fixture_manifest():
        return model.validate_manifest({
            "schema_version": 1,
            "model": {
                "name": "small", "multilingual": True,
                "repository": "Systran/faster-whisper-small",
                "revision": "1" * 40,
            },
            "format": {
                "name": "CTranslate2", "format_version": 1,
                "runtime_version": "4.8.1",
            },
            "cache": {
                "directory": "whisper-small",
                "compatibility_key": "fixture-small-ct2-v1",
            },
            "files": [
                {"path": name, "size": len(data),
                 "sha256": hashlib.sha256(data).hexdigest()}
                for name, data in blobs.items()
            ],
        })

    manifest = fixture_manifest()
    production = model.load_manifest()
    expected_hashes = {
        "config.json": (2370, "b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828"),
        "model.bin": (483546902, "3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671"),
        "tokenizer.json": (2203239, "fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab"),
        "vocabulary.txt": (459861, "34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913"),
    }
    got_hashes = {row["path"]: (row["size"], row["sha256"])
                  for row in production["files"]}
    if got_hashes != expected_hashes or production["model"]["revision"] \
            != "536b0662742c02347bc0e980a01041f333bce120":
        bad.append("trusted production revision/file manifest")
    unsafe = copy.deepcopy(manifest)
    unsafe["files"][0]["path"] = "../escape.bin"
    try:
        model.validate_manifest(unsafe)
        bad.append("manifest path traversal accepted")
    except model.ModelManagerError as exc:
            if exc.code != "manifest_unsafe_path":
                bad.append("manifest traversal typed error")
    broad_cache = copy.deepcopy(manifest)
    broad_cache["cache"]["directory"] = ".."
    try:
        model.validate_manifest(broad_cache)
        bad.append("broad/versioned cache directory accepted")
    except model.ModelManagerError as exc:
        if exc.code != "manifest_cache_invalid":
            bad.append("versioned cache typed error")

    with tempfile.TemporaryDirectory(prefix="smiteless-model-state-") as tmp:
        paths = model.resolve_paths(local_appdata=tmp)
        with mock.patch.object(sys, "frozen", False, create=True):
            source_root = model.resolve_paths(local_appdata=tmp).model_root
        with mock.patch.object(sys, "frozen", True, create=True):
            frozen_root = model.resolve_paths(local_appdata=tmp).model_root
        if source_root != frozen_root or source_root != Path(tmp).resolve() / \
                "Smiteless" / "models" / "whisper-small":
            bad.append("source/frozen canonical model root")
        try:
            model.resolve_paths(
                local_appdata=Path(tmp) / "redirected",
                trusted_local_appdata=Path(tmp) / "trusted")
            bad.append("redirected LocalAppData accepted")
        except model.ModelManagerError as exc:
            if exc.code != "local_appdata_redirected":
                bad.append("redirected LocalAppData typed error")
        forged = model.ModelPaths(
            Path(tmp), Path(tmp) / "Elsewhere", Path(tmp) / "Elsewhere" / "models",
            Path(tmp) / "Elsewhere" / "models" / "whisper-small",
            Path(tmp) / "Elsewhere" / "models" / model.LOCK_FILE_NAME)
        try:
            model.inspect_model(manifest=manifest, paths=forged)
            bad.append("forged model path object accepted")
        except model.ModelManagerError as exc:
            if exc.code != "unsafe_model_path":
                bad.append("forged model path typed error")
        if model.inspect_model(manifest=manifest, paths=paths)["state"] != "missing":
            bad.append("missing model state")
        paths.model_root.mkdir(parents=True)
        first_name = next(iter(blobs))
        (paths.model_root / first_name).write_bytes(blobs[first_name])
        if model.inspect_model(manifest=manifest, paths=paths)["state"] != "partial":
            bad.append("partial model state")
        for name, data in blobs.items():
            (paths.model_root / name).write_bytes(data)
        corrupt_name = "tokenizer.json"
        (paths.model_root / corrupt_name).write_bytes(b"X" * len(blobs[corrupt_name]))
        corrupt = model.inspect_model(manifest=manifest, paths=paths)
        if corrupt["state"] != "invalid" or corrupt.get("error") != "model_hash_mismatch":
            bad.append("same-size wrong-hash model state")
        (paths.model_root / corrupt_name).write_bytes(blobs[corrupt_name])
        if not model.inspect_model(manifest=manifest, paths=paths).get("ready"):
            bad.append("valid model state")

    with tempfile.TemporaryDirectory(prefix="smiteless-model-lock-") as tmp:
        paths = model.resolve_paths(local_appdata=tmp)
        old = model.ModelLock(paths, clock=lambda: 100.0, pid_probe=lambda _pid: True,
                              owner_pid=101)
        if not old.acquire():
            bad.append("initial active lock")
        blocked = model.ModelLock(
            paths, clock=lambda: 100.0 + model.LOCK_STALE_SECONDS + 1,
            pid_probe=lambda _pid: True, owner_pid=202)
        active_state = model.lock_status(
            paths, clock=lambda: 100.0 + model.LOCK_STALE_SECONDS + 1,
            pid_probe=lambda _pid: True)
        if active_state.get("owner_pid") != 101 or not active_state.get("stale") \
                or active_state.get("recoverable"):
            bad.append("lock owner/age/active status")
        if blocked.acquire():
            bad.append("active old lock was reclaimed")
            blocked.release()
        old.release()
        abandoned = model.ModelLock(paths, clock=lambda: 100.0,
                                    pid_probe=lambda _pid: True, owner_pid=303)
        abandoned.acquire()
        recovered = model.ModelLock(
            paths, clock=lambda: 100.0 + model.LOCK_STALE_SECONDS + 1,
            pid_probe=lambda pid: pid != 303, owner_pid=404)
        if not recovered.acquire():
            bad.append("proven-dead stale lock was not recovered")
        recovered.release()
        abandoned.release()

        gate = threading.Barrier(3)
        release = threading.Event()
        outcomes = []

        def contender(owner_pid):
            lock = model.ModelLock(paths, pid_probe=lambda _pid: True, owner_pid=owner_pid)
            gate.wait()
            acquired = lock.acquire()
            outcomes.append(acquired)
            if acquired:
                release.wait(2)
                lock.release()

        threads = [threading.Thread(target=contender, args=(pid,)) for pid in (501, 502)]
        for thread in threads:
            thread.start()
        gate.wait()
        deadline = time.monotonic() + 2
        while len(outcomes) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        release.set()
        for thread in threads:
            thread.join(timeout=2)
        if sorted(outcomes) != [False, True]:
            bad.append("concurrent fake-process exclusion")

    def write_remaining(_manifest, entry, partial, offset, cancellation, on_chunk):
        cancellation.raise_if_cancelled()
        data = blobs[entry["path"]]
        with open(partial, "ab" if offset else "wb") as handle:
            handle.write(data[offset:])
        on_chunk(len(data))

    with tempfile.TemporaryDirectory(prefix="smiteless-model-resume-") as tmp:
        paths = model.resolve_paths(local_appdata=tmp)
        calls = []
        interrupted = [False]

        def flaky(_manifest, entry, partial, offset, cancellation, on_chunk):
            cancellation.raise_if_cancelled()
            name = entry["path"]
            data = blobs[name]
            calls.append((name, offset))
            if name == "tokenizer.json" and not interrupted[0]:
                interrupted[0] = True
                cut = max(1, len(data) // 2)
                with open(partial, "ab" if offset else "wb") as handle:
                    handle.write(data[offset:cut])
                on_chunk(cut)
                raise RuntimeError("fixture interruption")
            with open(partial, "ab" if offset else "wb") as handle:
                handle.write(data[offset:])
            on_chunk(len(data))

        with mock.patch.object(model, "CHECKPOINT_INTERVAL_BYTES", 1):
            first = model.download_model(manifest, paths, fetcher=flaky)
        staging_dirs = list(paths.models_root.glob(model.STAGING_PREFIX + "*"))
        checkpoint = model._read_json(staging_dirs[0] / model.CHECKPOINT_NAME) \
            if len(staging_dirs) == 1 else None
        split = len(calls)
        progress_rows = []
        second = model.download_model(
            manifest, paths, fetcher=flaky, progress=progress_rows.append)
        resumed_calls = calls[split:]
        if first.get("error") != "download_failed" or not first.get("resumable"):
            bad.append("interrupted download checkpoint")
        completed_size = len(blobs["config.json"]) + len(blobs["model.bin"])
        if not checkpoint or checkpoint.get("bytes_downloaded", 0) <= completed_size:
            bad.append("bounded partial-byte checkpoint")
        if not second.get("ok") or not second.get("resumed") \
                or not model.inspect_model(manifest=manifest, paths=paths).get("ready"):
            bad.append("interrupted download resume/promotion")
        if any(name in ("config.json", "model.bin") for name, _offset in resumed_calls) \
                or not any(name == "tokenizer.json" and offset > 0
                           for name, offset in resumed_calls):
            bad.append("completed-file skip/partial-file resume")
        if not progress_rows or progress_rows[-1].get("state") != "ready" \
                or progress_rows[-1].get("percent") != 100.0:
            bad.append("pure progress API")
        response_text = json.dumps([first, second, model.status(manifest, paths)],
                                   sort_keys=True)
        if os.path.normcase(tmp) in os.path.normcase(response_text) or "token" in response_text:
            bad.append("user path/model token leaked into status")

    with tempfile.TemporaryDirectory(prefix="smiteless-model-retry-") as tmp:
        paths = model.resolve_paths(local_appdata=tmp)
        attempts = [0]

        def invalid_then_valid(_manifest, entry, partial, offset, cancellation, on_chunk):
            attempts[0] += 1
            data = blobs[entry["path"]]
            if attempts[0] == 1:
                Path(partial).write_bytes(b"!" * len(data))
                on_chunk(len(data))
                return
            write_remaining(_manifest, entry, partial, offset, cancellation, on_chunk)

        failed = model.download_model(manifest, paths, fetcher=invalid_then_valid)
        retried = model.download_model(manifest, paths, fetcher=write_remaining)
        if failed.get("error") != "download_file_invalid" or not retried.get("ok"):
            bad.append("invalid completed-file clean retry")

    with tempfile.TemporaryDirectory(prefix="smiteless-model-concurrent-") as tmp:
        paths = model.resolve_paths(local_appdata=tmp)
        entered = threading.Event()
        release_fetch = threading.Event()
        concurrent_results = []

        def blocking_fetcher(_manifest, entry, partial, offset, cancellation, on_chunk):
            entered.set()
            if not release_fetch.wait(2):
                raise RuntimeError("fixture release timeout")
            write_remaining(_manifest, entry, partial, offset, cancellation, on_chunk)

        first_thread = threading.Thread(
            target=lambda: concurrent_results.append(
                model.download_model(manifest, paths, fetcher=blocking_fetcher)))
        first_thread.start()
        if not entered.wait(2):
            bad.append("concurrent download did not enter fetch")
        second_thread = threading.Thread(
            target=lambda: concurrent_results.append(
                model.download_model(manifest, paths, fetcher=write_remaining)))
        second_thread.start()
        second_thread.join(timeout=2)
        release_fetch.set()
        first_thread.join(timeout=2)
        if len(concurrent_results) != 2 \
                or sorted((row.get("ok", False), row.get("error"))
                          for row in concurrent_results) \
                != [(False, "model_locked"), (True, None)]:
            bad.append("concurrent download/promotion exclusion")

    with tempfile.TemporaryDirectory(prefix="smiteless-model-atomic-") as tmp:
        paths = model.resolve_paths(local_appdata=tmp)
        paths.model_root.mkdir(parents=True)
        sentinel = paths.model_root / "old-invalid-cache.txt"
        sentinel.write_text("preserve until promotion", encoding="utf-8")
        observed = []

        def observing_fetcher(_manifest, entry, partial, offset, cancellation, on_chunk):
            observed.append(sentinel.is_file() and not (paths.model_root / entry["path"]).exists())
            write_remaining(_manifest, entry, partial, offset, cancellation, on_chunk)

        promoted = model.download_model(manifest, paths, fetcher=observing_fetcher)
        if not promoted.get("ok") or not all(observed) or sentinel.exists() \
                or not model.inspect_model(manifest=manifest, paths=paths).get("ready"):
            bad.append("validated atomic promotion/preservation")
        candidate = model.validate_import_candidate(paths.model_root, manifest, paths)
        if not candidate.get("ready"):
            bad.append("allowlisted future import candidate validation")
        cancellation = model.DownloadCancellation()
        cancellation.cancel()
        other_paths = model.resolve_paths(local_appdata=Path(tmp) / "cancel")
        cancelled = model.download_model(
            manifest, other_paths, fetcher=write_remaining, cancellation=cancellation)
        if cancelled.get("error") != "cancelled" or not cancelled.get("resumable"):
            bad.append("pure cancellation API")

    with tempfile.TemporaryDirectory(prefix="smiteless-model-upgrade-") as tmp:
        current_paths = model.paths_for_manifest(manifest, local_appdata=tmp)
        current = model.download_model(manifest, current_paths, fetcher=write_remaining)
        future_manifest = copy.deepcopy(manifest)
        future_manifest["model"]["revision"] = "2" * 40
        future_manifest["cache"] = {
            "directory": "whisper-small-fixture-v2",
            "compatibility_key": "fixture-small-ct2-v2",
        }
        future_manifest = model.validate_manifest(future_manifest)
        future_paths = model.paths_for_manifest(future_manifest, local_appdata=tmp)
        failed_future = model.download_model(
            future_manifest, future_paths,
            fetcher=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("fixture interrupted incompatible upgrade")))
        preserved = model.inspect_model(manifest=manifest, paths=current_paths)
        upgraded = model.download_model(
            future_manifest, future_paths, fetcher=write_remaining)
        if not current.get("ok") or failed_future.get("error") != "download_failed" \
                or not preserved.get("ready") or not upgraded.get("ok") \
                or not model.inspect_model(
                    manifest=future_manifest, paths=future_paths).get("ready") \
                or current_paths.model_root == future_paths.model_root:
            bad.append("incompatible versioned-cache upgrade preservation")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, ("trusted manifest/path guards; missing/partial/corrupt/valid; active/stale locks; "
                "concurrent downloads; interrupt/resume/retry/atomic/versioned promotion/cancel pass")


def c_local_whisper_workers():
    """Active Phase 3C: bounded fake capture and isolated JSON worker contracts."""
    import array
    import hashlib
    import subprocess
    import tempfile
    import wave
    from pathlib import Path
    from unittest import mock
    import llmprocess
    import smitemicworker as mic
    import smitestt
    import smitewhispermodel as manager
    import smitewhisperworker as whisper

    bad = []
    block_frames = mic.SAMPLE_RATE * mic.BLOCK_MS // 1000
    silence = array.array("h", [0] * block_frames).tobytes()
    voiced = array.array("h", [1200] * block_frames).tobytes()
    captured = mic.capture_blocks(
        [voiced] * 4 + [silence] * 20,
        initial_silence_ms=250, end_silence_ms=300, total_ms=3000)
    if not captured.get("pcm") or not captured.get("stopped_by_silence") \
            or captured.get("duration_ms", 9999) > 1000:
        bad.append("bounded PCM/end-silence capture")
    try:
        mic.capture_blocks([silence] * 20, initial_silence_ms=250, total_ms=1000)
        bad.append("initial silence accepted as speech")
    except mic.CaptureError as exc:
        if exc.code != "no_speech":
            bad.append("initial silence typed error")

    blobs = {
        "config.json": b'{"fixture":1}\n',
        "model.bin": b"tiny-model-fixture\x00\x01",
        "tokenizer.json": b'{"tokens":["dragao","dragon"]}\n',
        "vocabulary.txt": b"dragao\ndragon\nlee sin\n",
    }
    manifest = manager.validate_manifest({
        "schema_version": 1,
        "model": {"name": "small", "multilingual": True,
                  "repository": "Systran/faster-whisper-small", "revision": "2" * 40},
        "format": {"name": "CTranslate2", "format_version": 1,
                   "runtime_version": "4.8.1"},
        "cache": {"directory": "whisper-small", "compatibility_key": "worker-fixture-v1"},
        "files": [{"path": name, "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in blobs.items()],
    })

    def write_wav(path, pcm=voiced * 4):
        with wave.open(str(path), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(16000)
            target.writeframes(pcm)

    with tempfile.TemporaryDirectory(prefix="smiteless-worker-fixture-") as tmp:
        paths = manager.resolve_paths(local_appdata=tmp)
        paths.model_root.mkdir(parents=True)
        for name, data in blobs.items():
            (paths.model_root / name).write_bytes(data)
        audio_root = mic.audio_root(paths)
        audio_root.mkdir(parents=True)
        audio_path = audio_root / "coach-fixture.wav"
        audio_path.touch()

        seen_stream = []

        class FakeStream:
            def __init__(self, **kwargs):
                seen_stream.append(kwargs)
                self.blocks = iter([voiced] * 4 + [silence] * 20)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _frames):
                return next(self.blocks, silence), False

        fake_sd = type("FakeSoundDevice", (), {
            "query_devices": staticmethod(lambda device, kind: {"max_input_channels": 1}),
            "RawInputStream": FakeStream,
        })
        got_capture = mic.capture_default(
            audio_path, initial_silence_ms=250, end_silence_ms=300, total_ms=2000,
            sounddevice=fake_sd, root=audio_root, beeper=lambda *_args: True,
            post_beep_delay=0)
        if not got_capture.get("ok") or not mic.validate_wav(audio_path, root=audio_root) \
                or not seen_stream or seen_stream[0].get("device") is not None \
                or not got_capture.get("start_beep") or not got_capture.get("end_beep"):
            bad.append("Windows-default fake capture/WAV validation")
        missing_sd = type("MissingSoundDevice", (), {
            "query_devices": staticmethod(
                lambda *_args: (_ for _ in ()).throw(RuntimeError("no input"))),
        })
        if mic.microphone_readiness(missing_sd).get("error") != "microphone_unavailable":
            bad.append("missing default microphone typed error")
        arbitrary = Path(tmp) / "outside.wav"
        arbitrary.write_bytes(b"outside")
        try:
            mic.validate_audio_path(arbitrary, root=audio_root, require_exists=True)
            bad.append("arbitrary audio path accepted")
        except mic.CaptureError:
            pass

        stale = audio_root / "coach-stale.wav"
        stale.touch()
        unrelated = audio_root / "keep.txt"
        unrelated.touch()
        os.utime(stale, (1, 1))
        if mic.cleanup_stale_audio(audio_root, clock=lambda: 10000, max_age=10) != 1 \
                or stale.exists() or not unrelated.exists():
            bad.append("allowlisted startup temp cleanup")

        class Segment:
            def __init__(self, text, no_speech_prob=0.01):
                self.text = text
                self.no_speech_prob = no_speech_prob

        class FakeModel:
            def transcribe(self, path, **kwargs):
                language = kwargs.get("language")
                if Path(path) != audio_path or language not in ("en", "pt"):
                    raise AssertionError("worker transcription arguments")
                text = ((" Dragão ", " agora ") if language == "pt"
                        else (" Dragon ", " now "))
                info = type("Info", (), {
                    "language": language, "language_probability": 0.97})()
                return [Segment(part) for part in text], info

        factory_calls = []

        def model_factory(path, **kwargs):
            factory_calls.append((path, kwargs))
            return FakeModel()

        worker = whisper.WhisperWorker(
            paths=paths, manifest=manifest, model_factory=model_factory,
            audio_root=audio_root)
        if worker.handle({"version": 999, "command": "status"}).get("error") \
                != "protocol_mismatch":
            bad.append("worker protocol mismatch")
        for decoder, limit in ((mic.decode_request, mic.MAX_REQUEST_BYTES),
                               (whisper.decode_request, whisper.MAX_REQUEST_BYTES)):
            for raw, expected in ((b"not-json", "malformed_json"),
                                  (b"x" * (limit + 1), "request_too_large")):
                try:
                    decoder(raw)
                    bad.append(f"worker accepted {expected}")
                except (mic.CaptureError, whisper.WorkerError) as exc:
                    if exc.code != expected:
                        bad.append(f"worker mistyped {expected}")
        invalid_load = worker.handle({"version": 1, "command": "load",
                                      "model_path": str(Path(tmp) / "other"),
                                      "device": "cpu", "compute_type": "int8"})
        if invalid_load.get("error") != "invalid_model_path":
            bad.append("invalid model path refusal")
        loaded = worker.handle({"version": 1, "command": "load",
                                "model_path": str(paths.model_root),
                                "device": "cpu", "compute_type": "int8"})
        if not loaded.get("ok") or not factory_calls \
                or factory_calls[0][1].get("local_files_only") is not True:
            bad.append("offline canonical model load")
        write_wav(audio_path)
        invalid_audio = worker.handle({"version": 1, "command": "transcribe",
                                       "audio_path": str(arbitrary), "locale": "pt_BR"})
        if invalid_audio.get("error") != "invalid_audio_path":
            bad.append("invalid worker audio path refusal")
        transcript = worker.handle({"version": 1, "command": "transcribe",
                                    "audio_path": str(audio_path), "locale": "pt_BR"})
        if not transcript.get("ok") or transcript.get("text") != "Dragão agora" \
                or transcript.get("cpu_fallback") is not False:
            bad.append("Unicode PT-BR worker transcription")
        english = worker.handle({"version": 1, "command": "transcribe",
                                 "audio_path": str(audio_path), "locale": "en"})
        if not english.get("ok") or english.get("text") != "Dragon now" \
                or english.get("language") != "en":
            bad.append("Unicode English worker transcription")

        class EmptyModel:
            def __init__(self, rows):
                self.rows = rows

            def transcribe(self, _path, **_kwargs):
                info = type("Info", (), {
                    "language": "en", "language_probability": 0.97})()
                return self.rows, info

        for rows in ([], [Segment("  ")]):
            worker.model = EmptyModel(rows)
            empty = worker.handle({"version": 1, "command": "transcribe",
                                   "audio_path": str(audio_path), "locale": "en"})
            if empty.get("error") != "empty_transcript":
                bad.append("zero/empty segments typed empty_transcript")
                break
        worker.model = EmptyModel([Segment("unclear", no_speech_prob=0.91)])
        uncertain = worker.handle({"version": 1, "command": "transcribe",
                                   "audio_path": str(audio_path), "locale": "en"})
        if uncertain.get("error") != "low_confidence":
            bad.append("nonempty high-no-speech segment typed low_confidence")
        if "empty_transcript" not in smitestt.ACTIONABLE_ERRORS \
                or "unavailable" in smitestt.actionable_error("empty_transcript").lower():
            bad.append("empty transcript actionable STT mapping")
        if not worker.handle({"version": 1, "command": "unload"}).get("ok") \
                or worker.status().get("model_loaded"):
            bad.append("worker unload/status")

        created = []
        real_new = smitestt._new_audio_file

        def tracked_new(_paths=None):
            value = real_new(paths)
            created.append(value[0])
            return value

        def fake_capture(path, *_args, **_kwargs):
            write_wav(path)
            return {"ok": True, "duration_ms": 200, "sample_rate": 16000,
                    "channels": 1, "peak_int16": 1200, "rms_int16": 1200}

        with mock.patch.object(smitestt.smitewhispermodel, "load_manifest",
                               return_value=manifest), \
                mock.patch.object(smitestt.smitewhispermodel, "resolve_paths",
                                  return_value=paths), \
                mock.patch.object(smitestt.smitewhispermodel, "inspect_model",
                                  return_value={"state": "ready", "ready": True}), \
                mock.patch.object(smitestt, "_new_audio_file", side_effect=tracked_new), \
                mock.patch.object(smitestt, "_capture", side_effect=fake_capture), \
                mock.patch.object(smitestt, "_transcribe",
                                  return_value={"ok": False, "error": "worker_crash"}):
            failed_turn = smitestt.recognize("pt_BR")
        if failed_turn.get("error") != "worker_crash" or not created or created[0].exists():
            bad.append("temporary WAV cleanup after worker failure")
        with mock.patch.object(smitestt.smitewhispermodel, "load_manifest",
                               return_value=manifest), \
                mock.patch.object(smitestt.smitewhispermodel, "resolve_paths",
                                  return_value=paths), \
                mock.patch.object(smitestt.smitewhispermodel, "inspect_model",
                                  return_value={"state": "missing", "ready": False}), \
                mock.patch.object(smitestt, "_capture") as capture_probe:
            missing_model = smitestt.recognize("en")
        if missing_model.get("error") != "model_missing" or capture_probe.called:
            bad.append("missing model opened microphone")

    class FakeProcess:
        pid = 4242

        def __init__(self, stdout="", returncode=0, timeout=False):
            self.stdout = stdout
            self.returncode = returncode
            self.timeout = timeout

        def communicate(self, input=None, timeout=None):
            self.input = input
            if self.timeout:
                raise subprocess.TimeoutExpired("worker", timeout)
            return self.stdout, "redacted diagnostic"

    def protocol_factory(stdout="", returncode=0, timeout=False):
        return lambda *_args, **_kwargs: FakeProcess(stdout, returncode, timeout)

    good_line = json.dumps({"version": 1, "ok": True, "command": "status"}) + "\n"
    responses, error = smitestt._run_protocol(
        ["fixture"], [{"version": 1, "command": "status"}], 1,
        popen_factory=protocol_factory(good_line))
    if error or not responses or not responses[0].get("ok"):
        bad.append("JSON-lines success")
    protocol_cases = (
        ("malformed", protocol_factory("not-json\n"), "malformed_json"),
        ("no output", protocol_factory(""), "no_output"),
        ("crash", protocol_factory("", returncode=7), "worker_crash"),
        ("oversized", protocol_factory("x" * (smitestt.MAX_PROTOCOL_OUTPUT_BYTES + 1)),
         "response_too_large"),
    )
    for name, factory, expected in protocol_cases:
        _responses, got_error = smitestt._run_protocol(
            ["fixture"], [{"version": 1, "command": "status"}], 1,
            popen_factory=factory)
        if got_error != expected:
            bad.append(f"{name} protocol error")
    killed = []
    with mock.patch.object(smitestt.llmprocess, "terminate_tree", side_effect=killed.append):
        _responses, timed_error = smitestt._run_protocol(
            ["fixture"], [{"version": 1, "command": "status"}], 1,
            popen_factory=protocol_factory(timeout=True))
    if timed_error != "timeout" or len(killed) != 1:
        bad.append("worker timeout/tree termination")
    cancelled = llmprocess.CancellationHandle()
    cancelled.cancel()
    killed = []
    with mock.patch.object(smitestt.llmprocess, "terminate_tree", side_effect=killed.append):
        _responses, cancelled_error = smitestt._run_protocol(
            ["fixture"], [{"version": 1, "command": "status"}], 1,
            cancel_handle=cancelled, popen_factory=protocol_factory(good_line))
    if cancelled_error != "cancelled" or len(killed) != 1:
        bad.append("worker cancellation/tree termination")

    sources = "\n".join(open(os.path.join(_ROOT, path), encoding="utf-8").read()
                         for path in ("core/smitestt.py", "tools/smitemicworker.py",
                                      "tools/smitewhisperworker.py"))
    forbidden = ("Windows.Media.SpeechRecognition", "System.Speech", "api.openai.com",
                 "gpt-4o-transcribe", "requests.post(", "audio_device_id",
                 "coach_microphone_id")
    if any(token in sources for token in forbidden):
        bad.append("cloud/legacy/endpoint-selection code in active local STT")
    if "device=None" not in sources or "RawInputStream" not in sources \
            or "local_files_only=True" not in sources \
            or "from faster_whisper import WhisperModel" not in sources \
            or 'reconfigure(encoding="utf-8"' not in sources \
            or "START_BEEP_HZ = 880" not in sources or "END_BEEP_HZ = 440" not in sources:
        bad.append("default-input/offline isolated-worker static contract")
    if bad:
        return FAIL, "; ".join(bad)
    return OK, ("bounded default capture; private WAV cleanup; versioned Unicode worker; "
                "path/protocol/crash/timeout/cancel/refusal contracts pass")


def c_whisper_runtime_policies():
    """Active Phase 3D: canonical compute and generation-bound worker policies."""
    import queue
    import tempfile
    import threading
    from pathlib import Path
    from unittest import mock
    import llmprocess
    import smiteconfig as cfg
    import smitestt

    bad = []
    real_path = cfg.PATH
    with tempfile.TemporaryDirectory(prefix="smiteless-stt-config-") as tmp:
        cfg.PATH = os.path.join(tmp, "settings.json")
        try:
            defaults = cfg.load()
            if defaults.get("coach_stt_device") != "cpu" \
                    or defaults.get("coach_stt_load_policy") != "keep_loaded" \
                    or defaults.get("coach_stt_model") != "small":
                bad.append("canonical STT defaults")
            saved = cfg.save({"coach_stt_device": "CUDA",
                              "coach_stt_load_policy": "per_question",
                              "coach_stt_model": "small.en"})
            if saved.get("coach_stt_device") != "cuda" \
                    or saved.get("coach_stt_load_policy") != "per_question" \
                    or saved.get("coach_stt_model") != "small":
                bad.append("STT config normalization/small.en refusal")
            partial = cfg.save({"board_size": 80})
            if partial.get("coach_stt_device") != "cuda" \
                    or partial.get("coach_stt_load_policy") != "per_question":
                bad.append("partial save preserved STT policy")
        finally:
            cfg.PATH = real_path

    cpu = smitestt.runtime_configuration({
        "coach_stt_device": "cpu", "coach_stt_load_policy": "keep_loaded",
        "coach_stt_model": "small"})
    gpu_float = smitestt.runtime_configuration({"coach_stt_device": "cuda"},
                                               compute_probe=lambda: {"float16"})
    gpu_mixed = smitestt.runtime_configuration({"coach_stt_device": "cuda"},
                                               compute_probe=lambda: {"int8_float16"})
    if cpu.get("compute_type") != "int8" or gpu_float.get("compute_type") != "float16" \
            or gpu_mixed.get("compute_type") != "int8_float16":
        bad.append("CPU/GPU compute selection")
    for code, probe in (("cuda_unavailable", lambda: (_ for _ in ()).throw(
            smitestt.SttError("cuda_unavailable"))),
                        ("unsupported_compute_type", lambda: {"float32"})):
        try:
            smitestt.runtime_configuration({"coach_stt_device": "cuda"},
                                           compute_probe=probe)
            bad.append(f"accepted {code}")
        except smitestt.SttError as exc:
            if exc.code != code:
                bad.append(f"mistyped {code}")

    class Output:
        def __init__(self, values):
            self.values = values

        def __iter__(self):
            return self

        def __next__(self):
            value = self.values.get(timeout=2)
            if value is None:
                raise StopIteration
            return value

    class Input:
        def __init__(self, process):
            self.process = process

        def write(self, raw):
            for line in raw.splitlines():
                if line:
                    self.process.respond(json.loads(line))

        def flush(self):
            pass

    class FakePersistentProcess:
        next_pid = 9100

        def __init__(self, wrong_id=False, load_error=None, transcribe_error=None):
            self.pid = FakePersistentProcess.next_pid
            FakePersistentProcess.next_pid += 1
            self.returncode = None
            self.values = queue.Queue()
            self.stdout = Output(self.values)
            self.stderr = iter(())
            self.stdin = Input(self)
            self.commands = []
            self.wrong_id = wrong_id
            self.load_error = load_error
            self.transcribe_error = transcribe_error

        def respond(self, request):
            command = request.get("command")
            self.commands.append((command, request.get("device"), request.get("compute_type")))
            response = {"version": 1, "ok": True, "command": command,
                        "id": "old-generation" if self.wrong_id else request.get("id")}
            if command == "load" and self.load_error:
                response.update(ok=False, error=self.load_error)
            elif command == "transcribe":
                if self.transcribe_error:
                    response.update(ok=False, error=self.transcribe_error)
                else:
                    response.update(text="fixture transcript", language="en",
                                    cpu_fallback=False)
            self.values.put(json.dumps(response) + "\n")
            if command == "shutdown":
                self.returncode = 0
                self.values.put(None)

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if self.returncode is None:
                raise TimeoutError("still running")
            return self.returncode

        def kill(self):
            self.returncode = -9
            self.values.put(None)

        def communicate(self, timeout=None):
            return "", ""

    created = []

    def factory(*_args, **_kwargs):
        process = FakePersistentProcess()
        created.append(process)
        return process

    keep = {"coach_stt_device": "cpu", "coach_stt_load_policy": "keep_loaded",
            "coach_stt_model": "small"}
    with mock.patch.object(llmprocess, "terminate_tree", side_effect=lambda p: p.kill()):
        runtime = smitestt.WhisperRuntime(
            popen_factory=factory, command_factory=lambda: ["fixture"])
        first = runtime.transcribe(Path("one.wav"), "en", Path("model"), settings=keep)
        second = runtime.transcribe(Path("two.wav"), "en", Path("model"), settings=keep)
        if not first.get("ok") or not second.get("ok") or len(created) != 1 \
                or [row[0] for row in created[0].commands].count("load") != 1 \
                or not runtime.status().get("model_loaded"):
            bad.append("keep-loaded lazy load/warm reuse")
        generation = runtime.status().get("generation")
        unloaded = runtime.unload()
        if not unloaded.get("ok") or runtime.status().get("worker_alive"):
            bad.append("explicit unload/process exit")
        runtime.transcribe(Path("three.wav"), "en", Path("model"), settings=keep)
        if runtime.status().get("generation") != generation + 1 or len(created) != 2:
            bad.append("unload next-generation restart")
        with mock.patch.object(smitestt, "_transcribe",
                               return_value={"ok": True, "text": "one shot"}) as one_shot:
            per_question = dict(keep, coach_stt_load_policy="per_question")
            got = runtime.transcribe(
                Path("four.wav"), "en", Path("model"), settings=per_question)
        if not got.get("ok") or not one_shot.called or runtime.status().get("worker_alive"):
            bad.append("per-question shutdown policy")
        runtime.close()
        if runtime.status().get("worker_alive"):
            bad.append("tray/coordinator close")

        failing_created = []
        gpu_runtime = smitestt.WhisperRuntime(
            popen_factory=lambda *_a, **_k: failing_created.append(
                FakePersistentProcess(load_error="cuda_runtime_missing")) or failing_created[-1],
            command_factory=lambda: ["fixture"], compute_probe=lambda: {"float16"})
        gpu = gpu_runtime.transcribe(
            Path("gpu.wav"), "en", Path("model"),
            settings={"coach_stt_device": "cuda",
                      "coach_stt_load_policy": "keep_loaded",
                      "coach_stt_model": "small"})
        if gpu.get("error") != "cuda_runtime_missing" or len(failing_created) != 1 \
                or any(row[1] == "cpu" for row in failing_created[0].commands):
            bad.append("GPU load failure had CPU fallback")

        transcribe_failed = []
        gpu_transcribe_runtime = smitestt.WhisperRuntime(
            popen_factory=lambda *_a, **_k: transcribe_failed.append(
                FakePersistentProcess(transcribe_error="cuda_runtime_missing"))
                or transcribe_failed[-1],
            command_factory=lambda: ["fixture"], compute_probe=lambda: {"float16"})
        gpu_transcribe = gpu_transcribe_runtime.transcribe(
            Path("gpu.wav"), "en", Path("model"),
            settings={"coach_stt_device": "cuda",
                      "coach_stt_load_policy": "keep_loaded",
                      "coach_stt_model": "small"})
        if gpu_transcribe.get("error") != "cuda_runtime_missing" \
                or gpu_transcribe_runtime.status().get("worker_alive") \
                or any(row[1] == "cpu" for row in transcribe_failed[0].commands):
            bad.append("GPU transcription failure cleanup/CPU fallback")

        stale_created = []
        stale_runtime = smitestt.WhisperRuntime(
            popen_factory=lambda *_a, **_k: stale_created.append(
                FakePersistentProcess(wrong_id=not stale_created)) or stale_created[-1],
            command_factory=lambda: ["fixture"])
        stale = stale_runtime.transcribe(
            Path("stale.wav"), "en", Path("model"), settings=keep)
        fresh = stale_runtime.transcribe(
            Path("fresh.wav"), "en", Path("model"), settings=keep)
        if stale.get("error") != "stale_worker_response" or not fresh.get("ok") \
                or len(stale_created) != 2:
            bad.append("delayed old-worker generation isolation")
        stale_runtime.close()

    order = []
    fake_runtime = mock.Mock()
    fake_runtime.transcribe.side_effect = lambda *_a, **_k: order.append("worker") or {
        "ok": True, "text": "heard"}
    with tempfile.TemporaryDirectory(prefix="smiteless-listen-order-") as tmp:
        audio = Path(tmp) / "coach-order.wav"
        audio.touch()
        paths = mock.Mock(model_root=Path(tmp) / "model")
        with mock.patch.object(smitestt.smitewhispermodel, "load_manifest", return_value={}), \
                mock.patch.object(smitestt.smitewhispermodel, "paths_for_manifest",
                                  return_value=paths), \
                mock.patch.object(smitestt.smitewhispermodel, "inspect_model",
                                  return_value={"ready": True}), \
                mock.patch.object(smitestt, "_new_audio_file", return_value=(audio, Path(tmp))), \
                mock.patch.object(smitestt, "_capture",
                                  side_effect=lambda *_a, **_k: order.append("capture") or {
                                      "ok": True}), \
                mock.patch("smitemicworker.validate_wav",
                           return_value={"duration_ms": 100}):
            smitestt.recognize("en", runtime=fake_runtime, settings=keep)
    if order != ["capture", "worker"]:
        bad.append("model worker allocated before capture completed")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, ("canonical CPU/CUDA config; lazy reuse/unload/per-question/close; "
                "GPU refusal and generation isolation pass")


def c_coach_settings_onboarding():
    """Active Phase 3E: pure Settings states and consented first-use transaction."""
    import tempfile
    from unittest import mock
    import smiteconfig as cfg
    import smitei18n
    import smitesettings
    import smitestt
    import smitewhispermodel

    bad = []
    real_path = cfg.PATH
    with tempfile.TemporaryDirectory(prefix="smiteless-phase3e-config-") as tmp:
        cfg.PATH = os.path.join(tmp, "settings.json")
        try:
            with open(cfg.PATH, "w", encoding="utf-8") as handle:
                json.dump({"speech_backend": "windows_media_speech",
                           "speech_online": True}, handle)
            migrated = cfg.load()
            if migrated.get("coach_stt_device") != "cpu" \
                    or migrated.get("coach_stt_load_policy") != "keep_loaded" \
                    or migrated.get("coach_stt_model") != "small" \
                    or migrated.get("voice_coach") is not False \
                    or migrated.get("proactive_coach") is not False:
                bad.append("WinRT-era config migration/default opt-ins")
            invalid = cfg.save({"coach_stt_device": "automatic",
                                "coach_stt_load_policy": "forever",
                                "coach_stt_model": "small.en"})
            partial = cfg.save({"board_size": 85})
            if invalid.get("coach_stt_device") != "cpu" \
                    or invalid.get("coach_stt_load_policy") != "keep_loaded" \
                    or invalid.get("coach_stt_model") != "small" \
                    or partial.get("voice_coach") is not False \
                    or partial.get("proactive_coach") is not False:
                bad.append("invalid/partial Settings normalization")
        finally:
            cfg.PATH = real_path

    cpu_resolver = lambda _settings: {
        "device": "cpu", "compute_type": "int8",
        "load_policy": "keep_loaded", "model": "small"}
    base_settings = {"coach_stt_device": "cpu",
                     "coach_stt_load_policy": "keep_loaded",
                     "coach_stt_model": "small"}
    ready = smitesettings.coach_settings_state({
        "model": {"state": "ready", "ready": True},
        "worker": {"model_loaded": False, "last_error": ""}},
        base_settings, compute_resolver=cpu_resolver)
    missing = smitesettings.coach_settings_state({
        "model": {"state": "missing", "ready": False, "error": "model_missing"},
        "worker": {}}, base_settings, compute_resolver=cpu_resolver)
    invalid = smitesettings.coach_settings_state({
        "model": {"state": "invalid", "ready": False,
                  "error": "model_hash_mismatch"}, "worker": {}},
        base_settings, compute_resolver=cpu_resolver)
    downloading = smitesettings.coach_settings_state({
        "model": {"state": "partial", "ready": False}, "worker": {}},
        base_settings, progress={"state": "downloading", "percent": 42.5,
                                 "bytes_downloaded": 425, "bytes_total": 1000},
        compute_resolver=cpu_resolver)
    loaded = smitesettings.coach_settings_state({
        "model": {"state": "ready", "ready": True},
        "worker": {"model_loaded": True, "last_error": ""}},
        base_settings, compute_resolver=cpu_resolver)

    def gpu_failure(_settings):
        raise smitestt.SttError("cuda_unavailable")

    gpu_error = smitesettings.coach_settings_state({
        "model": {"state": "ready", "ready": True}, "worker": {}},
        {**base_settings, "coach_stt_device": "cuda"},
        compute_resolver=gpu_failure)
    if not ready.get("model_ready") or ready.get("compute_type") != "int8" \
            or missing.get("error") != "model_missing" \
            or invalid.get("error") != "model_hash_mismatch" \
            or not downloading.get("downloading") or downloading.get("percent") != 42.5 \
            or not loaded.get("worker_loaded") \
            or gpu_error.get("error") != "cuda_unavailable":
        bad.append("Settings model/download/device/compute/worker states")

    download_calls = []
    progress_rows = []

    def successful_download(**kwargs):
        download_calls.append("success")
        kwargs["progress"]({"state": "downloading", "percent": 50,
                            "bytes_downloaded": 1, "bytes_total": 2})
        return {"ok": True, "downloaded": True,
                "model": {"state": "ready", "ready": True}}

    ready_result = lambda: {"ok": True,
                            "model": {"state": "ready", "ready": True}}
    declined = smitesettings.run_coach_onboarding(
        False, base_settings, downloader=lambda **_kwargs: bad.append("decline downloaded"))
    accepted = smitesettings.run_coach_onboarding(
        True, base_settings, downloader=successful_download,
        readiness_fn=ready_result, progress=progress_rows.append)
    interrupted = smitesettings.run_coach_onboarding(
        True, base_settings,
        downloader=lambda **_kwargs: {"ok": False, "error": "download_failed",
                                      "resumable": True}, readiness_fn=ready_result)
    retried = smitesettings.run_coach_onboarding(
        True, base_settings, downloader=successful_download,
        readiness_fn=ready_result, progress=lambda _row: None)
    cancelled = smitesettings.run_coach_onboarding(
        True, base_settings, cancellation=smitewhispermodel.DownloadCancellation(),
        downloader=lambda **_kwargs: {"ok": False, "error": "cancelled",
                                      "resumable": True}, readiness_fn=ready_result)
    validation_failed = smitesettings.run_coach_onboarding(
        True, base_settings, downloader=successful_download,
        readiness_fn=lambda: {"ok": True, "model": {
            "state": "invalid", "ready": False, "error": "model_hash_mismatch"}},
        progress=lambda _row: None)
    if not declined.get("declined") or declined.get("enable_voice") \
            or not accepted.get("ok") or not accepted.get("enable_voice") \
            or not accepted.get("offer_microphone_test") or len(progress_rows) != 1 \
            or interrupted.get("error") != "download_failed" \
            or not interrupted.get("resumable") or not retried.get("ok") \
            or cancelled.get("error") != "cancelled" \
            or validation_failed.get("error") != "model_hash_mismatch":
        bad.append("onboarding accept/decline/cancel/interrupt/retry/validation/test offer")

    if smitesettings.needs_coach_onboarding(
            {"voice_coach": False}, False, False) \
            or smitesettings.needs_coach_onboarding(
                {"voice_coach": True}, True, False) \
            or smitesettings.needs_coach_onboarding(
                {"voice_coach": False}, True, True) \
            or not smitesettings.needs_coach_onboarding(
                {"voice_coach": False}, True, False):
        bad.append("unrelated save/new-opt-in download boundary")

    smitei18n.set_lang("pt_BR")
    translated = smitesettings.coach_error_message("cuda_runtime_missing")
    low_confidence = smitesettings.coach_error_message("low_confidence")
    smitei18n.set_lang("en")
    if "CUDA 12" not in translated or "selecione CPU" not in translated \
            or "WinRT" in translated or "pacote de voz" in translated \
            or "clareza" not in low_confidence or "microfone padrão" not in low_confidence \
            or "low_confidence" in low_confidence:
        bad.append("bilingual actionable local-Whisper errors")

    with mock.patch.object(smitesettings.smitewhispermodel, "download_model") as download_mock, \
            mock.patch.object(smitesettings.smitestt, "recognize") as recognize_mock:
        smitesettings.coach_settings_state(
            {"model": {"state": "missing", "ready": False}, "worker": {}},
            base_settings, compute_resolver=cpu_resolver)
    if download_mock.called or recognize_mock.called:
        bad.append("passive Settings state started download/capture")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, ("config migration/default opt-ins; all Settings states; consent, progress, "
                "cancel/retry/validation/readiness/test offer and bilingual errors pass")


def c_installed_whisper_lifecycle():
    """Phase 3I installer/upgrade/uninstall contract using isolated tiny filesystem fixtures."""
    import re
    import shutil
    import tempfile
    from pathlib import Path

    installer_path = os.path.join(_ROOT, "dist", "installer.ahk")
    installer = open(installer_path, encoding="utf-8").read()
    bad = []
    required = (
        "KnownFolder(0x001C)", "KnownFolder(0x0028)", "InstallTargetIsSafe",
        "AllowedChild", "CLAUDE_FILES", "CLAUDE_DIRS", "CACHE_FILES", "CACHE_DIRS",
        "TEMP_DIRS", "CleanupLegacyAudioCache", "/IM Smiteless.exe",
        "/IM SmitelessApp.exe", "A_Desktop", "A_Startup", "A_Programs",
        "RegDeleteKey(REGKEY)", 'rmdir /s /q "' + "' TARGET '",
        "Voice coaching downloads its local model only after you opt in",
        'Expand-Archive -LiteralPath', '-DestinationPath \'" TARGET "\' -Force',
    )
    absent = [token for token in required if token not in installer]
    if absent:
        bad.append("installer lifecycle tokens missing: " + ", ".join(absent))
    if not re.search(r'Run\(A_ComSpec.*bat.*TEMP_ROOT,\s*"Hide"\)', installer):
        bad.append("detached uninstall cleanup inherits the install directory")
    forbidden_deletes = (
        "DirDelete(CLAUDE_ROOT, true)", "DirDelete(CACHE_ROOT, true)",
        "DirDelete(LOCAL_ROOT, true)", "DirDelete(PROFILE_ROOT, true)",
        "DirDelete(TEMP_ROOT, true)",
    )
    leaked = [token for token in forbidden_deletes if token in installer]
    if leaked:
        bad.append("broad uninstall target present: " + ", ".join(leaked))
    if 'DirDelete(TARGET "\\models"' in installer \
            or 'DirDelete(TARGET "\\models", true)' in installer:
        bad.append("compatible upgrade deletes the shared model cache")

    def ahk_array(name):
        match = re.search(rf"(?ms)^\s*{re.escape(name)}\s*:=\s*\[(.*?)\]", installer)
        return re.findall(r'"([^"]+)"', match.group(1)) if match else []

    arrays = {name: ahk_array(name) for name in (
        "CLAUDE_FILES", "CLAUDE_DIRS", "CACHE_FILES", "CACHE_DIRS", "TEMP_DIRS")}
    required_state = {
        "CLAUDE_FILES": {"smiteless_settings.json", "smiteless_logins.bin",
                         "smiteless_noautoopen", "smiteless_nohomeonstart"},
        "CLAUDE_DIRS": {"smiteless_accounts"},
        "CACHE_FILES": {"smiteless_coach_endpoint.json", "scout_snapshot.json.lock",
                        "smiteless_coach_tools.jsonl", "smiteless_coach_tools.jsonl.old",
                        "smiteless_proactive_intents.jsonl",
                        "smiteless_proactive_intents.jsonl.old",
                        "smiteless_proactive_widget.json"},
        "CACHE_DIRS": {"riot", "matchups", "ddragon"},
        "TEMP_DIRS": {"smiteless_audio"},
    }
    for name, expected in required_state.items():
        if not expected.issubset(set(arrays[name])):
            bad.append(name + " incomplete")
        if any(not value or ".." in value or ":" in value
               or value.startswith(("\\", "/")) for value in arrays[name]):
            bad.append(name + " contains a broadened relative target")

    def allowed_child(root, relative, allowlist):
        if not relative or relative not in allowlist or ".." in relative \
                or ":" in relative or relative.startswith(("\\", "/")):
            return None
        root = Path(root).resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return None
        return target if target != root else None

    with tempfile.TemporaryDirectory(prefix="smiteless-phase3i-uninstall-") as tmp:
        fixture = Path(tmp)
        local_root = fixture / "LocalAppData"
        profile_root = fixture / "User"
        claude_root = profile_root / ".claude"
        cache_root = claude_root / "cache"
        temp_root = fixture / "Temp"
        install_root = local_root / "Smiteless"
        unrelated_local = local_root / "Unrelated" / "keep.txt"
        unrelated_claude = claude_root / "unrelated.txt"
        unrelated_cache = cache_root / "unrelated" / "keep.txt"
        unrelated_temp = temp_root / "keep.txt"
        for path in (unrelated_local, unrelated_claude, unrelated_cache, unrelated_temp):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("keep", encoding="utf-8")
        for relative in arrays["CLAUDE_FILES"]:
            path = claude_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned", encoding="utf-8")
        for relative in arrays["CLAUDE_DIRS"]:
            path = claude_root / relative / "owned.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned", encoding="utf-8")
        for relative in arrays["CACHE_FILES"]:
            path = cache_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned", encoding="utf-8")
        for relative in arrays["CACHE_DIRS"]:
            path = cache_root / relative / "owned.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned", encoding="utf-8")
        for relative in arrays["TEMP_DIRS"]:
            path = temp_root / relative / "owned.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned", encoding="utf-8")
        for relative in ("app/runtime.dll", "models/whisper-small/model.bin",
                         "models/whisper-small-v2/model.bin",
                         "models/whisper-small.partial-fixture/model.bin.partial",
                         "models/.whisper-small.lock"):
            path = install_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("owned", encoding="utf-8")

        for name, root in (("CLAUDE_FILES", claude_root), ("CACHE_FILES", cache_root)):
            for relative in arrays[name]:
                target = allowed_child(root, relative, arrays[name])
                if target:
                    target.unlink(missing_ok=True)
        for name, root in (("CLAUDE_DIRS", claude_root), ("CACHE_DIRS", cache_root),
                           ("TEMP_DIRS", temp_root)):
            for relative in arrays[name]:
                target = allowed_child(root, relative, arrays[name])
                if target and target.exists():
                    shutil.rmtree(target)
        shutil.rmtree(install_root)

        owned_left = []
        for name, root in (("CLAUDE_FILES", claude_root), ("CLAUDE_DIRS", claude_root),
                           ("CACHE_FILES", cache_root), ("CACHE_DIRS", cache_root),
                           ("TEMP_DIRS", temp_root)):
            owned_left.extend(str(root / relative) for relative in arrays[name]
                              if (root / relative).exists())
        preserved = all(path.read_text(encoding="utf-8") == "keep" for path in (
            unrelated_local, unrelated_claude, unrelated_cache, unrelated_temp))
        refused = all(allowed_child(claude_root, target, arrays["CLAUDE_FILES"]) is None
                      for target in ("", "..", "../outside", str(profile_root),
                                     "unrelated.txt"))
        if install_root.exists() or owned_left or not preserved or not refused:
            bad.append("isolated complete-uninstall allowlist/path-guard fixture")

    if bad:
        return FAIL, "; ".join(bad)
    return OK, ("clean first-use disclosure; compatible/versioned upgrade preservation; exact "
                "process/state/model/audio/shortcut/registry cleanup and broad-target refusal pass")


def main():
    print("\nSMITELESS SELF-TEST")
    print("=" * 66)
    checks = [
        ("Pillow (image render)", c_pillow),
        ("Data Dragon (champ data)", c_ddragon),
        ("op.gg (builds + matchups)", c_opgg),
        ("Riot API key (player scout)", c_riot_key),
        ("LLM CLI (matchup tips)", c_llm_cli),
        ("Coach coordinator health", c_coach_service_health),
        ("Coach voice readiness", c_coach_readiness_health),
        ("LLM provider contracts", c_llm_providers),
        ("LLM provider integration", c_llm_integration),
        ("Tag spec (docs/TAGS.md)", c_tagspec),
        ("Glyph coverage (tofu)", c_glyphs),
        ("Queue call (verdict engine)", c_queuecall),
        ("Re-entry guard (90s window)", c_reentry),
        ("Bleed guard (first 14 min)", c_bleed),
        ("Closer (win conversion)", c_closer),
        ("Gold clock (farm pace)", c_gold),
        ("Ward clock (vision war)", c_ward),
        ("THE OUT (the losing game)", c_out),
        ("THE ONE FIX (leak board)", c_onefix),
        ("THE POOL (champions in LP)", c_pool),
        ("Frozen build (hidden imports)", c_frozen),
        ("Auto-mute (chat + settings)", c_mute),
        ("Auto-mute input guard", c_muteguard),
        ("Personal fit (your results)", c_fit),
        ("Adaptive runes (comp-aware)", c_runes),
        ("New feature i18n (PT/EN)", c_new_i18n),
        ("MAX ELO (one-switch arming)", c_maxelo),
        ("MAX ELO auto-lock (draft)", c_autolock),
        ("Coach context boundary", c_coach_context),
        ("Coach text runtime", c_coach_runtime),
        ("Coach context discovery", c_coach_tools),
        ("Coach proactive lifecycle", c_coach_proactive),
        ("Coach voice + audio", c_voice_audio),
        ("Frozen local Whisper runtime", c_frozen_whisper_runtime),
        ("Local Whisper probe", c_local_whisper_probe),
        ("Whisper model manager", c_whisper_model_manager),
        ("Local Whisper capture/workers", c_local_whisper_workers),
        ("Whisper runtime policies", c_whisper_runtime_policies),
        ("Coach Settings + onboarding", c_coach_settings_onboarding),
        ("Installed Whisper lifecycle", c_installed_whisper_lifecycle),
        ("League client / LCU", c_lcu),
    ]
    for name, fn in checks:
        check(name, fn)
    mark = {OK: "[ OK ]", FAIL: "[FAIL]", SKIP: "[skip]"}
    for name, status, detail in results:
        print(f"{mark[status]} {name:30} {detail}")
    print("=" * 66)
    fails = [r for r in results if r[1] == FAIL]
    if fails:
        print(f"{len(fails)} check(s) FAILED. The overlay's core needs Pillow + Data Dragon "
              f"+ op.gg; the rest gate optional features.")
    else:
        print("All good. (skips are optional features that aren't set up / not running.)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
