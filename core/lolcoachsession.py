#!/usr/bin/env python3
"""Bounded, text-only conversational memory for the local League coach."""

import time


MAX_TURNS = 12
MAX_CHARACTERS = 12000
IDLE_SECONDS = 2 * 60 * 60
_TERMINAL_PHASES = {"PostGame", "WaitingForStats", "PreEndOfGame", "EndOfGame"}


class CoachSession:
    """One in-memory session. Context snapshots are deliberately never stored here."""

    def __init__(self, max_turns=MAX_TURNS, max_characters=MAX_CHARACTERS,
                 idle_seconds=IDLE_SECONDS, clock=None):
        self.max_turns = int(max_turns)
        self.max_characters = int(max_characters)
        self.idle_seconds = float(idle_seconds)
        self.clock = clock or time.time
        self.reset()

    def reset(self):
        self.turns = []
        self.phase_markers = []
        self.phase = None
        self.lifecycle_id = None
        self.last_activity = self.clock()

    def _expire(self, now):
        if self.turns and now - self.last_activity >= self.idle_seconds:
            self.reset()
            return True
        return False

    def observe(self, phase, lifecycle_id, now=None):
        """Record a phase change and isolate a definitely new League lifecycle."""
        now = self.clock() if now is None else float(now)
        expired = self._expire(now)
        phase = str(phase or "None")
        lifecycle_id = str(lifecycle_id or "")
        prior_phase = self.phase
        prior_lifecycle = self.lifecycle_id
        new_game = bool(
            prior_lifecycle and lifecycle_id and prior_lifecycle != lifecycle_id
            and (prior_phase in _TERMINAL_PHASES or phase == "Lobby")
        )
        if new_game:
            self.reset()
        if phase != self.phase:
            self.phase_markers.append({"phase": phase, "at": int(now)})
            self.phase_markers = self.phase_markers[-16:]
        self.phase = phase
        self.lifecycle_id = lifecycle_id or self.lifecycle_id
        self.last_activity = now
        return {"expired": expired, "new_lifecycle": new_game}

    def add_turn(self, user_text, assistant_text, now=None):
        now = self.clock() if now is None else float(now)
        self._expire(now)
        self.turns.append({"user": str(user_text or "").strip()[:4000],
                           "assistant": str(assistant_text or "").strip()[:6000]})
        self.last_activity = now
        self._trim()

    def _trim(self):
        self.turns = self.turns[-self.max_turns:]
        while self.turns and sum(len(row["user"]) + len(row["assistant"])
                                 for row in self.turns) > self.max_characters:
            self.turns.pop(0)

    def history(self, now=None):
        now = self.clock() if now is None else float(now)
        self._expire(now)
        return [{"user": row["user"], "assistant": row["assistant"]}
                for row in self.turns]

    def snapshot(self, now=None):
        now = self.clock() if now is None else float(now)
        self._expire(now)
        return {"phase": self.phase or "None", "lifecycle_id": self.lifecycle_id,
                "turn_count": len(self.turns), "last_activity": int(self.last_activity),
                "phase_markers": list(self.phase_markers)}
