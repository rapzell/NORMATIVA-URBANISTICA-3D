"""Memoria conversacional de sesión para el asistente.

Ventana deslizante de los últimos turnos + último edificio seleccionado,
por ``chat_id``. En RAM (dict global con TTL de 30 min); para producción
migrar a Redis — la interfaz ya lo permite.
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

_TTL_S = 30 * 60
_SESSIONS: dict[str, tuple[float, 'SessionMemory']] = {}
_LOCK = threading.Lock()

_REF_RE = re.compile(
    r'\b(ah[ií]|esa\s+(parcela|pregunta)|ese\s+(edificio|suelo)|'
    r'la\s+de\s+al\s+lado|el\s+mismo|lo\s+mismo|y\s+(si|en)\b|'
    r'esta\s+vez|entonces|y\s+ahora)\b', re.I)


@dataclass
class SessionMemory:
    chat_id: str
    last_building: dict | None = None
    turns: deque = field(default_factory=lambda: deque(maxlen=3))

    def add_turn(self, pregunta: str, respuesta_resumen: str) -> None:
        self.turns.append({'pregunta': pregunta,
                           'respuesta': respuesta_resumen[:300]})

    def usa_referencia(self, pregunta: str) -> bool:
        return bool(_REF_RE.search(pregunta or ''))

    def build_history_context(self) -> str:
        if not self.turns:
            return ''
        lines = ['HISTORIAL DE CONVERSACIÓN (turnos previos):']
        for t in self.turns:
            lines.append(f"Arquitecto: {t['pregunta']}")
            lines.append(f"Asistente: {t['respuesta']}")
        lines.append('Si el arquitecto usa referencias ("ahí", "esa '
                     'parcela", "y si…"), se refiere al edificio del '
                     'contexto actual salvo que indique otro punto.')
        return '\n'.join(lines)


def _limpiar(ahora: float) -> None:
    for cid in [c for c, (ts, _) in _SESSIONS.items()
                if ahora - ts > _TTL_S]:
        _SESSIONS.pop(cid, None)


def get_session(chat_id: str | None) -> SessionMemory | None:
    if not chat_id:
        return None
    ahora = time.time()
    with _LOCK:
        _limpiar(ahora)
        if chat_id in _SESSIONS:
            _SESSIONS[chat_id] = (ahora, _SESSIONS[chat_id][1])
            return _SESSIONS[chat_id][1]
        mem = SessionMemory(chat_id=chat_id)
        _SESSIONS[chat_id] = (ahora, mem)
        return mem


def estado() -> dict:
    with _LOCK:
        return {'sesiones_activas': len(_SESSIONS), 'ttl_min': _TTL_S // 60}
