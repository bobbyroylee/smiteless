"""Small runtime i18n layer with English source-string fallbacks."""
import re

from i18n_pt_BR import MESSAGES as PT_BR_MESSAGES

SUPPORTED = ("pt_BR", "en")
DEFAULT_LANG = "en"
_override = None


def _normalize(code):
    value = str(code or "").strip().replace("-", "_")
    if value.lower() == "pt_br":
        return "pt_BR"
    if value.lower() == "en":
        return "en"
    return DEFAULT_LANG


def lang():
    """Return the active UI language, defaulting safely to English."""
    if _override is not None:
        return _override
    try:
        import smiteconfig as cfg
        return _normalize(cfg.load().get("ui_lang", DEFAULT_LANG))
    except Exception:
        return DEFAULT_LANG


def set_lang(code):
    """Set a process-local language override after a settings save."""
    global _override
    _override = _normalize(code)
    return _override


def t(msgid):
    """Translate an English source string, retaining it when no translation exists."""
    if lang() == "pt_BR":
        return PT_BR_MESSAGES.get(msgid, msgid)
    return msgid


def tf(msgid, **kwargs):
    """Translate and format a complete message template."""
    return t(msgid).format(**kwargs)


def coach(text):
    """Localize dynamic coaching copy while preserving names, scores, and timers."""
    if not text or lang() != "pt_BR":
        return text
    value = t(text)
    if value != text:
        return value
    replacements = (("FREE ", "LIVRE "), ("TAKE ", "FAÇA "), ("GIVE ", "CEDA "),
                    ("LEAN TAKE", "TENDÊNCIA: FAÇA"), ("LEAN GIVE", "TENDÊNCIA: CEDA"),
                    ("BASE window", "janela de BASE"), ("farm window", "janela de farm"),
                    ("ROTATE", "ROTACIONE"), ("CRASH your wave", "EMPURRE sua onda"),
                    ("their jungler", "o caçador inimigo"), ("enemy dead", "inimigo morto"),
                    (" dead", " morto"),
                    ("you can't reach", "você não consegue chegar"),
                    ("you win this read", "vocês vencem esta leitura"),
                    ("you lose this read", "vocês perdem esta leitura"),
                    ("confidence", "confiança"), ("objective", "objetivo"),
                    ("is carrying", "está carregando"), ("Behind", "Em desvantagem"),
                    ("You're ahead", "Vocês estão na frente"), ("Even game", "Jogo equilibrado"),
                    ("Solo-killed by", "Abatido sozinho por"), ("Killed by", "Abatido por"),
                    ("Executed by", "Executado por"), ("RESET", "RECOMPONHA"),
                    ("HOLD", "SEGURE"), ("CLEAR", "LIVRE"),
                    ("off-champ", "fora do campeão"), ("first ", "primeira vez com "),
                    ("new account", "conta nova"), ("heater", "em sequência"),
                    ("skid", "derrotas seguidas"), ("cold on", "frio com"),
                    ("comfort", "conforto"), ("hard to kill", "difícil de abater"),
                    ("carries", "carrega"), ("passenger", "carregado"),
                    ("off-role", "fora da rota"), ("main", "principal"),
                    ("shared", "em comum"), ("Enemy is AD-heavy", "Inimigo tem muito AD"),
                    ("Enemy is AP-heavy", "Inimigo tem muito AP"),
                    ("You out-scale", "Vocês escalam melhor"),
                    ("They out-scale", "Eles escalam melhor"),
                    ("enemies missing", "inimigos desaparecidos"))
    for source, translated in replacements:
        value = value.replace(source, translated)
    value = value.replace("with it:", "com o padrão:").replace("without:", "sem o padrão:")
    value = re.sub(r"\b(\d+)W-(\d+)L\b", r"\1V-\2D", value)
    return value
