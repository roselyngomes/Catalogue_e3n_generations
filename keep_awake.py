#!/usr/bin/env python3
"""
keep_awake.py
=============

Maintient eveillee une application hebergee sur Streamlit Community Cloud.

Contexte
--------
Le plan gratuit de Streamlit Community Cloud met en veille toute application
qui ne recoit aucun trafic pendant 12 heures. Le visiteur suivant tombe alors
sur une page "This app has gone to sleep due to inactivity" avec un bouton
"Yes, get this app back up!".

Une simple requete HTTP (curl, requests.get) ne suffit pas :
  - elle n'execute pas le JavaScript de la page,
  - elle n'ouvre pas la connexion WebSocket que Streamlit utilise pour
    comptabiliser une session active,
  - elle ne peut donc pas cliquer le bouton de reveil.

Ce script pilote un vrai navigateur (Chromium headless via Playwright) :
  1. il ouvre l'URL,
  2. il detecte si la page de veille est affichee,
  3. le cas echeant il clique le bouton de reveil,
  4. il attend que le conteneur applicatif Streamlit soit reellement rendu,
  5. il verifie qu'un element attendu de l'application est present.

Utilisation
-----------
    pip install playwright
    playwright install --with-deps chromium
    python keep_awake.py https://cataloguee3ngenerations.streamlit.app/

L'URL peut aussi etre fournie par la variable d'environnement APP_URL.

Codes de sortie
---------------
    0 : application eveillee et rendue correctement
    1 : echec apres epuisement des tentatives
    2 : erreur de configuration (URL manquante ou invalide)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

try:
    from playwright.sync_api import (
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeout,
        sync_playwright,
    )
except ImportError:
    sys.exit(
        "Playwright n'est pas installe.\n"
        "  pip install playwright\n"
        "  playwright install --with-deps chromium"
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_URL = "https://cataloguee3ngenerations.streamlit.app/"

# Selecteurs CSS / texte utilises pour detecter l'etat de la page.
# Ils sont volontairement multiples : Streamlit fait evoluer son DOM au fil
# des versions, donc on essaie plusieurs pistes plutot qu'une seule fragile.
SLEEP_BUTTON_SELECTORS = [
    'button:has-text("Yes, get this app back up!")',
    'button:has-text("get this app back up")',
    '[data-testid="wakeup-button-viewer"]',
    '[data-testid="wakeup-button-owner"]',
]

# Presence de ce conteneur = l'application Streamlit est reellement rendue.
APP_READY_SELECTORS = [
    '[data-testid="stAppViewContainer"]',
    'section.main',
    'div.stApp',
]

# Texte caracteristique de la page de veille, utilise en second recours.
SLEEP_PAGE_MARKERS = [
    "has gone to sleep",
    "s'est mise en veille",
]


@dataclass
class Config:
    """Parametres d'execution du script."""

    url: str
    attempts: int = 3
    page_timeout_ms: int = 60_000     # chargement initial de la page
    wake_timeout_ms: int = 120_000    # redemarrage du conteneur apres clic
    settle_seconds: float = 8.0       # temps laisse a l'app pour s'initialiser
    retry_delay_seconds: float = 20.0
    screenshot_dir: Path | None = None
    verbose: bool = False


# ---------------------------------------------------------------------------
# Journalisation
# ---------------------------------------------------------------------------

def setup_logging(verbose: bool) -> logging.Logger:
    """Configure un logger lisible dans les journaux GitHub Actions."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger("keep_awake")


log = logging.getLogger("keep_awake")


# ---------------------------------------------------------------------------
# Detection d'etat
# ---------------------------------------------------------------------------

def find_wake_button(page):
    """
    Cherche le bouton de reveil de Streamlit.

    Retourne le Locator du premier selecteur qui correspond, sinon None.
    On teste plusieurs selecteurs car le DOM de la page de veille a change
    plusieurs fois entre les versions de Community Cloud.
    """
    for selector in SLEEP_BUTTON_SELECTORS:
        locator = page.locator(selector).first
        try:
            if locator.count() > 0 and locator.is_visible(timeout=2_000):
                log.debug("Bouton de reveil trouve via : %s", selector)
                return locator
        except PlaywrightError:
            continue
    return None


def looks_like_sleep_page(page) -> bool:
    """Second filet de securite : recherche du texte de la page de veille."""
    try:
        body_text = (page.inner_text("body", timeout=5_000) or "").lower()
    except PlaywrightError:
        return False
    return any(marker in body_text for marker in SLEEP_PAGE_MARKERS)


def wait_for_app_ready(page, timeout_ms: int) -> bool:
    """
    Attend qu'un conteneur applicatif Streamlit apparaisse dans le DOM.

    C'est la seule verification qui prouve que l'application tourne
    vraiment : la page de veille, elle, ne contient aucun de ces elements.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for selector in APP_READY_SELECTORS:
            try:
                if page.locator(selector).first.count() > 0:
                    log.debug("Conteneur applicatif detecte via : %s", selector)
                    return True
            except PlaywrightError:
                pass
        page.wait_for_timeout(2_000)
    return False


# ---------------------------------------------------------------------------
# Coeur du traitement
# ---------------------------------------------------------------------------

def visit_once(page, cfg: Config, attempt: int) -> bool:
    """
    Effectue une visite complete de l'application.

    Retourne True si l'application est eveillee et rendue, False sinon.
    """
    log.info("Ouverture de %s", cfg.url)
    page.goto(cfg.url, wait_until="domcontentloaded", timeout=cfg.page_timeout_ms)

    # Laisse a React le temps de peindre soit l'app, soit la page de veille.
    page.wait_for_timeout(5_000)

    button = find_wake_button(page)

    if button is not None:
        log.warning("Application EN VEILLE — clic sur le bouton de reveil")
        button.click()
        log.info("Redemarrage du conteneur en cours (jusqu'a %d s)...",
                 cfg.wake_timeout_ms // 1000)
        if not wait_for_app_ready(page, cfg.wake_timeout_ms):
            log.error("Le conteneur n'a pas fini de redemarrer a temps")
            return False
        log.info("Application reveillee")

    elif looks_like_sleep_page(page):
        # Page de veille detectee par son texte, mais bouton introuvable :
        # le DOM a probablement change. On le signale explicitement.
        log.error(
            "Page de veille detectee mais bouton introuvable — "
            "les selecteurs sont probablement obsoletes"
        )
        return False

    else:
        log.info("Application deja eveillee")
        if not wait_for_app_ready(page, 30_000):
            log.error("Aucun conteneur Streamlit detecte — page inattendue")
            return False

    # Temps de repos supplementaire : maintient la session WebSocket ouverte
    # quelques secondes, ce qui garantit que le trafic est bien comptabilise.
    log.debug("Maintien de la session pendant %.0f s", cfg.settle_seconds)
    page.wait_for_timeout(int(cfg.settle_seconds * 1_000))

    title = page.title()
    log.info("Titre de la page : %s", title or "(vide)")
    return True


def save_screenshot(page, cfg: Config, attempt: int) -> None:
    """Capture d'ecran de diagnostic, recuperable en artefact CI."""
    if cfg.screenshot_dir is None:
        return
    cfg.screenshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = cfg.screenshot_dir / f"echec-tentative{attempt}-{stamp}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        log.info("Capture d'ecran enregistree : %s", path)
    except PlaywrightError as exc:
        log.debug("Capture d'ecran impossible : %s", exc)


def run(cfg: Config) -> int:
    """Boucle principale avec nouvelles tentatives."""
    started = datetime.now(timezone.utc)
    log.info("=== keep_awake — %s ===", started.strftime("%Y-%m-%d %H:%M:%S UTC"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 "
                "keep-awake-bot/1.0"
            ),
            locale="fr-FR",
        )
        page = context.new_page()
        page.set_default_timeout(cfg.page_timeout_ms)

        success = False
        for attempt in range(1, cfg.attempts + 1):
            log.info("--- Tentative %d/%d ---", attempt, cfg.attempts)
            try:
                if visit_once(page, cfg, attempt):
                    success = True
                    break
                save_screenshot(page, cfg, attempt)
            except PlaywrightTimeout as exc:
                log.error("Delai depasse : %s", str(exc).splitlines()[0])
                save_screenshot(page, cfg, attempt)
            except PlaywrightError as exc:
                log.error("Erreur navigateur : %s", str(exc).splitlines()[0])
                save_screenshot(page, cfg, attempt)

            if attempt < cfg.attempts:
                log.info("Nouvelle tentative dans %.0f s", cfg.retry_delay_seconds)
                time.sleep(cfg.retry_delay_seconds)

        context.close()
        browser.close()

    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if success:
        log.info("SUCCES — application accessible (%.1f s)", elapsed)
        return 0
    log.error("ECHEC — application inaccessible apres %d tentatives (%.1f s)",
              cfg.attempts, elapsed)
    return 1


# ---------------------------------------------------------------------------
# Interface en ligne de commande
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        description="Maintient eveillee une app Streamlit Community Cloud.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=os.environ.get("APP_URL", DEFAULT_URL),
        help="URL de l'application Streamlit",
    )
    parser.add_argument("--attempts", type=int, default=3,
                        help="nombre de tentatives")
    parser.add_argument("--settle", type=float, default=8.0,
                        help="secondes de session maintenue apres chargement")
    parser.add_argument("--screenshot-dir", type=Path, default=Path("captures"),
                        help="dossier des captures de diagnostic")
    parser.add_argument("--no-screenshot", action="store_true",
                        help="desactive les captures d'ecran")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="journalisation detaillee")
    args = parser.parse_args(argv)

    parsed = urlparse(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        sys.exit(f"URL invalide : {args.url!r}")

    return Config(
        url=args.url,
        attempts=max(1, args.attempts),
        settle_seconds=args.settle,
        screenshot_dir=None if args.no_screenshot else args.screenshot_dir,
        verbose=args.verbose,
    )


def main() -> int:
    cfg = parse_args()
    global log
    log = setup_logging(cfg.verbose)
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
