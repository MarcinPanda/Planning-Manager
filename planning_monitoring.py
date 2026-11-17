"""Planning Manager + Monitoring – wersja testowa z tablicą działów (przeciąganie pracowników).

Ta sama aplikacja i ta sama baza co planning_manager.py, dodatkowo z przełącznikiem
Planning / Monitoring. Kod widoku: pm/monitoring.py.
"""
from pm.app import main

if __name__ == "__main__":
    main(with_monitoring=True)
