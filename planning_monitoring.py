"""Planning Manager + Monitoring – wersja z tablicą działów (przeciąganie pracowników).

Ta sama aplikacja i ta sama baza co planning_manager.py, dodatkowo z przełącznikiem
Planning / Monitoring. Kod widoku: pm/monitoring.py.
"""
from pm import splash

splash.step(1, "Loading libraries...")

from pm.app import main  # noqa: E402  (celowo po pierwszym komunikacie na ekranie wczytywania)

if __name__ == "__main__":
    main(with_monitoring=True)
