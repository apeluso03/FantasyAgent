"""Multiplayer mock draft simulator: pure draft engine, CPU drafter, and the
2027 ADP board. The web backend (backend/app/mock) adds rooms, websockets and
timers on top -- nothing in here does I/O except store.py/adp.py's fetchers."""
