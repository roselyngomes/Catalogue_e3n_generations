#!/usr/bin/env python3
"""
keep_awake.py - version 2
=========================

Maintient eveillee une application hebergee sur Streamlit Community Cloud.

CE QUI CHANGE PAR RAPPORT A LA VERSION 1
----------------------------------------
La version 1 echouait avec "Aucun conteneur Streamlit detecte - page
inattendue" alors que l'application fonctionnait parfaitement. La cause :
elle exigeait de trouver l'element [data-testid="stAppViewContainer"] dans
la page principale. Or Streamlit Cloud peut servir l'application dans une
iframe, et les data-testid changent au fil des versions.

Corrections apportees :
  1. La recherche se fait dans TOUS les cadres de la page (page.frames),
     pas seulement dans le cadre principal.
  2. La liste des indices acceptes est bien plus large.
  3. Surtout : la regle de succes est inversee. Au lieu d'exiger un
     element precis, le script considere que tout va bien tant que la page
     n'est PAS la page de veille. C'est la seule chose qui compte
     reellement : l'objectif est de generer du trafic, pas de valider le
     DOM de Streamlit.
  4. Attente initiale allongee (Streamlit met parfois 15 s a peindre).

Utilisation
-----------
    pip install playwright
    playwright install --with-deps chromium
    python keep_awake.py https://mon-app.streamlit.app/

Codes de sortie
---------------
    0 : application accessible
    1 : application inaccessible apres toutes les tentatives
    2 : erreur de configuration
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


DEFAULT_URL = "https://cataloguee3ngenerations.streamlit.app/"

# --- Detection du bouton de reveil -----------------------------------------
# Plusieurs pistes, car le DOM de la page de veille change au fil des
# versions de Community Cloud.
SLEEP_BUTTON_SELECTORS = [
    'button:has-text("Yes, get this app back up!")',
    'button:has-text("get this app back up")',
    'button:has-text("Yes, get this app back up")',
    '[data-testid="wakeup-button-viewer"]',
    '[data-testid="wakeup-button-owner"]',
    'button:has-text("app back up")',
]

# --- Texte caracteristique de la page de veille ----------------------------
# C'est le critere DECISIF : si ce texte est absent, l'application tourne.
SLEEP_PAGE_MARKERS = [
    "has gone to sleep",
    "gone to sleep due to inactivity",
    "zzzz",
    "s'est mise en veille",
]

# --- Indices que l'application est rendue ----------------------------------
# Liste large et volontairement permissive : on cherche n'importe lequel.
APP_READY_SELECTORS = [
    '[data-testid="stAppViewContainer"]',
    '[data-testid="stApp"]',
    '[data-testid="stMain"]',
    '[data-testid="stSidebar"]',
    '[data-testid="stHeader"]',
    'div.stApp',
    'section.main',
    'div.main',
    '#root > div',
    'iframe[title="streamlitApp"]',
    '.streamlit-container',
]


@dataclass
class Config:
    url: str
    attempts: int = 3
    page_timeout_ms: int = 60_000
    wake_timeout_ms: int = 150_000
    initial_wait_ms: int = 12_000   # allonge : Streamlit peint lentement
    ready_timeout_ms: int = 45_000
    settle_seconds: float = 10.0
    retry_delay_seconds: float = 20.0
    screenshot_dir: Path | None = None
    verbose: bool = False


log = logging.getLogger("keep_awake")


def setup_logging(verbose: bool) -> logging.Logger:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger("keep_awake")


# ---------------------------------------------------------------------------
# Detection, en parcourant TOUS les cadres de la page
# ---------------------------------------------------------------------------

def all_frames(page):
    """Cadre principal plus toutes les iframes imbriquees."""
    return list(page.frames)


def find_wake_button(page):
    """Cherche le bouton de reveil dans tous les cadres."""
    for frame in all_frames(page):
        for selector in SLEEP_BUTTON_SELECTORS:
            try:
                locator = frame.locator(selector).first
                if locator.count() > 0 and locator.is_visible(timeout=1_500):
                    log.debug("Bouton de reveil trouve : %s (cadre %s)",
                              selector, frame.url[:60])
                    return locator
            except PlaywrightError:
                continue
    return None


def collect_text(page) -> str:
    """Concatene le texte visible de tous les cadres, en minuscules."""
    parts = []
    for frame in all_frames(page):
        try:
            text = frame.inner_text("body", timeout=4_000)
            if text:
                parts.append(text.lower())
        except PlaywrightError:
            continue
    return "\n".join(parts)


def is_sleep_page(page) -> bool:
    """Critere decisif : la page de veille affiche-t-elle son texte ?"""
    text = collect_text(page)
    return any(marker in text for marker in SLEEP_PAGE_MARKERS)


def find_app_container(page) -> str | None:
    """Cherche un indice d'application rendue, dans tous les cadres."""
    for frame in all_frames(page):
        for selector in APP_READY_SELECTORS:
            try:
                if frame.locator(selector).first.count() > 0:
                    return selector
            except PlaywrightError:
                continue
    return None


def wait_for_app_ready(page, timeout_ms: int) -> str | None:
    """Attend un indice d'application rendue. Retourne le selecteur trouve."""
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        found = find_app_container(page)
        if found:
            return found
        page.wait_for_timeout(2_500)
    return None


# ---------------------------------------------------------------------------
# Visite
# ---------------------------------------------------------------------------

def visit_once(page, cfg: Config) -> bool:
    log.info("Ouverture de %s", cfg.url)
    page.goto(cfg.url, wait_until="domcontentloaded", timeout=cfg.page_timeout_ms)

    log.debug("Attente initiale de %.0f s", cfg.initial_wait_ms / 1000)
    page.wait_for_timeout(cfg.initial_wait_ms)

    # --- 1. L'application dort-elle ? --------------------------------------
    button = find_wake_button(page)
    if button is not None:
        log.warning("Application EN VEILLE - clic sur le bouton de reveil")
        button.click()
        log.info("Redemarrage du conteneur en cours...")
        found = wait_for_app_ready(page, cfg.wake_timeout_ms)
        if found:
            log.info("Application reveillee (indice : %s)", found)
        else:
            # Le clic a eu lieu, le conteneur redemarre peut-etre encore.
            # On ne considere pas ca comme un echec si la page de veille
            # a disparu.
            if is_sleep_page(page):
                log.error("Toujours sur la page de veille apres le clic")
                return False
            log.info("Page de veille quittee, application en cours de demarrage")
        return finish(page, cfg)

    # --- 2. Pas de bouton : est-ce quand meme la page de veille ? ----------
    if is_sleep_page(page):
        log.error("Page de veille detectee mais bouton introuvable - "
                  "les selecteurs du bouton sont obsoletes")
        return False

    # --- 3. L'application est eveillee. On cherche un indice, sans exiger --
    found = find_app_container(page)
    if found is None:
        found = wait_for_app_ready(page, cfg.ready_timeout_ms)

    if found:
        log.info("Application eveillee et rendue (indice : %s)", found)
    else:
        # C'est ici que la version 1 echouait a tort.
        # L'application n'est pas endormie : la visite a donc bien genere
        # du trafic, ce qui est le seul objectif. On le signale sans
        # faire echouer le job.
        log.warning("Application eveillee, mais aucun selecteur connu "
                    "reconnu (le DOM de Streamlit a probablement change)")
        log.warning("Ce n'est pas bloquant : la visite compte comme du trafic")

    return finish(page, cfg)


def finish(page, cfg: Config) -> bool:
    """Maintient la session ouverte quelques secondes puis conclut."""
    log.debug("Maintien de la session pendant %.0f s", cfg.settle_seconds)
    page.wait_for_timeout(int(cfg.settle_seconds * 1_000))
    try:
        log.info("Titre de la page : %s", page.title() or "(vide)")
    except PlaywrightError:
        pass
    return True


def save_screenshot(page, cfg: Config, attempt: int) -> None:
    if cfg.screenshot_dir is None:
        return
    cfg.screenshot_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = cfg.screenshot_dir / f"echec-tentative{attempt}-{stamp}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        log.info("Capture d'ecran enregistree : %s", path)
    except PlaywrightError as exc:
        log.debug("Capture impossible : %s", exc)


def run(cfg: Config) -> int:
    started = datetime.now(timezone.utc)
    log.info("=== keep_awake v2 - %s ===",
             started.strftime("%Y-%m-%d %H:%M:%S UTC"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
            ),
            locale="fr-FR",
        )
        page = context.new_page()
        page.set_default_timeout(cfg.page_timeout_ms)

        success = False
        for attempt in range(1, cfg.attempts + 1):
            log.info("--- Tentative %d/%d ---", attempt, cfg.attempts)
            try:
                if visit_once(page, cfg):
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
        log.info("SUCCES - application accessible (%.1f s)", elapsed)
        return 0
    log.error("ECHEC - application inaccessible apres %d tentatives (%.1f s)",
              cfg.attempts, elapsed)
    return 1


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        description="Maintient eveillee une app Streamlit Community Cloud.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("url", nargs="?",
                        default=os.environ.get("APP_URL", DEFAULT_URL))
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--settle", type=float, default=10.0)
    parser.add_argument("--screenshot-dir", type=Path, default=Path("captures"))
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
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
