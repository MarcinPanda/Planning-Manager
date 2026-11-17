"""Planning Manager – punkt startowy. Kod aplikacji jest w pakiecie pm/."""
from pm import splash

splash.step(1, "Loading libraries...")

from pm.app import main  # noqa: E402  (celowo po pierwszym komunikacie na ekranie wczytywania)

if __name__ == "__main__":
    main()
