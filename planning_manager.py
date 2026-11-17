"""Planning Manager – punkt startowy (Planning + Monitoring + Consolidatie).

Kod aplikacji jest w pakiecie pm/. Exe: pyinstaller Planning_Manager.spec --noconfirm
"""
from pm import splash

splash.step(1, "Loading libraries...")

from pm.app import main  # noqa: E402  (celowo po pierwszym komunikacie na ekranie wczytywania)

if __name__ == "__main__":
    main()
