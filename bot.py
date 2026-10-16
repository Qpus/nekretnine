#!/usr/bin/env python3
"""Bot koji prati nove oglase za stanove (Novi Sad, od vlasnika) i šalje ih na Telegram.

Pokretanje:
    python bot.py --dry-run        # samo ispiše šta je pronašao, ništa ne šalje i ne pamti
    python bot.py --test-telegram  # pošalje probnu poruku
    python bot.py                  # normalan rad (Telegram + state/seen.json)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# PODEŠAVANJA - ovde menjaš kriterijume
# --------------------------------------------------------------------------- #
CONFIG = {
    # Možeš da zameniš URL-om iz browsera (primeni filtere na sajtu, pa kopiraj adresu).
    # rt=vlasnik -> samo oglasi od vlasnika.
    "oglasi_rs_urls": [
        "https://www.oglasi.rs/nekretnine/prodaja-stanova/novi-sad?rt=vlasnik",
    ],
    "pages_per_url": 3,          # koliko strana rezultata prolazi po URL-u
    "max_price_eur": 120_000,
    "min_area_m2": 36,
    # Sobnosti koje prolaze (garsonjera i jednosoban ne prolaze).
    "allowed_rooms": ["jednoiposoban", "dvosoban", "dvoiposoban", "trosoban",
                      "troiposoban", "cetvorosoban", "petosoban"],
    # Ako oglas NE pominje uknjiženost/nameštenost: True = ipak javi uz upozorenje,
    # False = preskoči. Oglas koji to izričito negira se uvek odbacuje.
    "notify_if_unconfirmed": True,
    "allow_semi_furnished": False,   # "polunamešten" se računa kao namešten?
    "request_delay_s": 1.5,          # pauza između zahteva (budi fin prema sajtu)
    "state_file": "state/seen.json",
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "sr,en;q=0.8",
}
AD_HREF = re.compile(r"/oglas/(\d+-\d+)/")


# --------------------------------------------------------------------------- #
# Model i pomoćne funkcije
# --------------------------------------------------------------------------- #
@dataclass
class Listing:
    id: str
    url: str
    title: str
    price_eur: float | None = None
    area_m2: float | None = None
    rooms: str = ""
    location: str = ""
    header: str = ""        # tekst oglašivača iz kartice (vlasnik / agencija)
    snippet: str = ""       # skraćeni opis iz liste
    full_text: str = ""     # pun tekst oglasa (iz detaljne strane)
    notes: list[str] = field(default_factory=list)


def norm(text: str) -> str:
    """Mala slova, bez dijakritika (š->s, ž->z, č/ć->c, đ->dj)."""
    text = text.lower().replace("đ", "dj")
    text = unicodedata.normalize("NFD", text)
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def parse_price_eur(text: str) -> float | None:
    m = re.search(r"([\d.]+),(\d{2})\s*EUR", text)
    if not m:
        return None
    return float(m.group(1).replace(".", "") + "." + m.group(2))


def parse_area(text: str) -> float | None:
    m = re.search(r"Kvadratura:\s*(\d+(?:[.,]\d+)?)\s*m", text)
    return float(m.group(1).replace(",", ".")) if m else None


# --------------------------------------------------------------------------- #
# Oglasi.rs - čitanje liste
# --------------------------------------------------------------------------- #
def parse_listing_page(html: str, base: str = "https://www.oglasi.rs") -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, Listing] = {}

    for a in soup.find_all("a", href=AD_HREF):
        ad_id = AD_HREF.search(a["href"]).group(1)
        if ad_id in found:
            continue

        # Penjemo se do najvećeg roditelja koji sadrži samo OVAJ oglas (kartica).
        card = a
        node = a.parent
        while node is not None and node.name not in ("body", "html"):
            ids = {AD_HREF.search(x["href"]).group(1) for x in node.find_all("a", href=AD_HREF)}
            if len(ids) > 1:
                break
            card = node
            node = node.parent

        text = card.get_text("\n", strip=True)
        h2 = card.find(["h2", "h3"])
        title = (h2.get_text(" ", strip=True) if h2 else a.get_text(" ", strip=True)) or ad_id

        rooms_m = re.search(r"Sobnost:\s*([^\n]+)", text)
        rooms = rooms_m.group(1).strip() if rooms_m else ""

        # Zaglavlje: sve pre prve cene, bez naslova -> ime oglašivača (vlasnik / agencija)
        head = text.split("EUR")[0] if "EUR" in text else text[:200]
        header = head.replace(title, " ")

        # Lokacija iz "breadcrumb" linkova kartice
        crumbs = []
        for x in card.find_all("a", href=re.compile(r"/nekretnine/prodaja-stanova/.+")):
            t = x.get_text(" ", strip=True)
            if t and norm(t) != norm(rooms) and t not in crumbs:
                crumbs.append(t)
        location = " / ".join(crumbs[-2:])

        desc_m = re.search(r"Nivo u zgradi:[^\n]*\n(.+?)(?:\n[\d.]+,\d{2}|\Z)", text, re.S)
        snippet = desc_m.group(1).strip() if desc_m else ""

        found[ad_id] = Listing(
            id=ad_id, url=urljoin(base, a["href"]), title=title,
            price_eur=parse_price_eur(text), area_m2=parse_area(text),
            rooms=rooms, location=location, header=header, snippet=snippet,
        )
    return list(found.values())


def with_page(url: str, page: int) -> str:
    sep = "&" if "?" in url else "?"
    return url if page == 1 else f"{url}{sep}p={page}"


def fetch(session: requests.Session, url: str) -> str:
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def fetch_oglasi_rs(session: requests.Session, cfg: dict) -> list[Listing]:
    out: dict[str, Listing] = {}
    for base_url in cfg["oglasi_rs_urls"]:
        for page in range(1, cfg["pages_per_url"] + 1):
            html = fetch(session, with_page(base_url, page))
            for item in parse_listing_page(html):
                out.setdefault(item.id, item)
            time.sleep(cfg["request_delay_s"])
    return list(out.values())


def fetch_full_text(session: requests.Session, listing: Listing) -> str:
    """Pun tekst oglasa. Odsecamo 'slične oglase' da se ne uhvate tuđe reči."""
    soup = BeautifulSoup(fetch(session, listing.url), "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    cut = re.search(r"Slični oglasi|Preporučeni oglasi|Pogledajte i ostale", text)
    return text[: cut.start()] if cut else text


# --------------------------------------------------------------------------- #
# Filteri
# --------------------------------------------------------------------------- #
def tri_state(text_norm: str, pos: str, neg: str) -> bool | None:
    """False = izričito negirano, True = potvrđeno, None = nije pomenuto."""
    if re.search(neg, text_norm):
        return False
    if re.search(pos, text_norm):
        return True
    return None


def check_registered(text: str) -> bool | None:
    return tri_state(
        norm(text),
        pos=r"uknjiz|list nepokretnosti|vlasnicki list",
        neg=(r"neuknjiz|(nije|nema|bez)\s+(jos\s+)?(je\s+)?uknjiz|u\s+procesu\s+uknjiz"
             r"|uknjizba\s+u\s+toku|nije\s+u\s+katastru|ne\s+uknjiz"),
    )


def check_furnished(text: str, allow_semi: bool) -> bool | None:
    t = norm(text)
    if re.search(r"polunamest|poluopremljen|delimicno\s+namest|delimicno\s+opremljen", t):
        return True if allow_semi else False
    return tri_state(
        t,
        pos=r"namesten|namestaj|opremljen",
        neg=(r"nenamest|neopremljen|nije\s+(namesten|opremljen)|bez\s+namestaja"
             r"|prazan\s+stan|stan\s+je\s+prazan"),
    )


def is_agency(listing: Listing) -> bool:
    header = norm(listing.header)
    if re.search(r"reg\.?\s*br|nekretnin|agencij|\bd\.?o\.?o\b|\bdoo\b|investitor", header):
        return True
    body = norm(listing.snippet + " " + listing.full_text)
    return bool(re.search(r"agencijsk[aeiu]?\s+(id|sifra)|agencijski\s+id|id\s+oglasa\s*:", body))


def cheap_filter(l: Listing, cfg: dict) -> str | None:
    """Vraća razlog odbacivanja ili None ako oglas prolazi osnovne filtere."""
    if is_agency(l):
        return "posrednik/agencija"
    if l.price_eur is None:
        return "nema cene u EUR"
    if l.price_eur > cfg["max_price_eur"]:
        return f"cena {l.price_eur:,.0f} > {cfg['max_price_eur']:,}"
    if l.area_m2 is None:
        return "nema kvadrature"
    if l.area_m2 < cfg["min_area_m2"]:
        return f"{l.area_m2:g} m2 < {cfg['min_area_m2']}"
    r = norm(l.rooms)
    if not any(r.startswith(x) for x in cfg["allowed_rooms"]):
        return f"struktura '{l.rooms or '?'}'"
    return None


def detail_filter(l: Listing, cfg: dict) -> str | None:
    text = l.full_text or l.snippet
    if is_agency(l):
        return "posrednik (iz opisa)"
    reg = check_registered(text)
    fur = check_furnished(text, cfg["allow_semi_furnished"])
    if reg is False:
        return "nije uknjižen"
    if fur is False:
        return "nije namešten"
    if reg is None:
        l.notes.append("uknjiženost nije navedena - proveri")
    if fur is None:
        l.notes.append("nameštenost nije navedena - proveri")
    if l.notes and not cfg["notify_if_unconfirmed"]:
        return "; ".join(l.notes)
    return None


# --------------------------------------------------------------------------- #
# Telegram
# --------------------------------------------------------------------------- #
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_message(l: Listing) -> str:
    lines = [f"🏠 <b>{esc(l.title)}</b>",
             f"💶 {l.price_eur:,.0f} €  ·  📐 {l.area_m2:g} m²  ·  🚪 {esc(l.rooms)}".replace(",", ".")]
    if l.location:
        lines.append(f"📍 {esc(l.location)}")
    lines.append("✅ vlasnik · uknjižen · namešten" if not l.notes
                 else "⚠️ " + esc("; ".join(l.notes)))
    lines.append(f'🔗 <a href="{esc(l.url)}">Otvori oglas</a>')
    return "\n".join(lines)


def send_telegram(session: requests.Session, text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    r = session.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": False},
        timeout=30,
    )
    r.raise_for_status()


# --------------------------------------------------------------------------- #
# Stanje (već viđeni oglasi)
# --------------------------------------------------------------------------- #
def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- #
# Glavni tok
# --------------------------------------------------------------------------- #
def fetch_all(session: requests.Session, cfg: dict) -> list[Listing]:
    listings = fetch_oglasi_rs(session, cfg)
    try:
        from kupujemprodajem import fetch_kupujemprodajem
        listings += fetch_kupujemprodajem(session, cfg)
    except ImportError:
        pass
    return listings


def run(dry_run: bool) -> int:
    cfg = CONFIG
    session = requests.Session()
    state_path = Path(cfg["state_file"])
    state = load_state(state_path)

    listings = fetch_all(session, cfg)
    print(f"Pročitano oglasa: {len(listings)}")
    if not listings:
        print("UPOZORENJE: nijedan oglas nije pročitan - moguće da sajt blokira zahtev "
              "ili se promenio HTML.", file=sys.stderr)
        return 1

    sent = 0
    for l in listings:
        prev = state.get(l.id)
        if prev and (prev["status"] == "notified" or prev.get("price") == l.price_eur):
            continue  # već obrađen (a cena se nije promenila)

        reason = cheap_filter(l, cfg)
        if reason is None:
            time.sleep(cfg["request_delay_s"])
            try:
                l.full_text = fetch_full_text(session, l)
            except requests.RequestException as e:
                print(f"  ! ne mogu da otvorim {l.url}: {e}", file=sys.stderr)
                continue  # probaćemo opet pri sledećem pokretanju
            reason = detail_filter(l, cfg)

        if reason:
            print(f"  - odbačen [{l.id}] {l.title[:50]!r}: {reason}")
            state[l.id] = {"status": "rejected", "price": l.price_eur, "reason": reason}
            continue

        print(f"  + MATCH [{l.id}] {l.title[:60]!r} {l.price_eur:,.0f}€ {l.area_m2:g}m2 {l.notes}")
        if dry_run:
            print("    " + format_message(l).replace("\n", "\n    "))
            continue
        try:
            send_telegram(session, format_message(l))
        except requests.RequestException as e:
            print(f"  ! Telegram greška: {e}", file=sys.stderr)
            continue  # nije označen kao viđen -> pokušaj ponovo
        state[l.id] = {"status": "notified", "price": l.price_eur}
        sent += 1

    if not dry_run:
        save_state(state_path, state)
    print(f"Gotovo. Poslato obaveštenja: {sent}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="ne šalje poruke i ne pamti stanje")
    ap.add_argument("--test-telegram", action="store_true", help="pošalji probnu poruku")
    args = ap.parse_args()

    if args.test_telegram:
        send_telegram(requests.Session(), "✅ Bot radi. Ovako će izgledati obaveštenja.")
        print("Probna poruka poslata.")
        return 0
    if not args.dry_run and not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")):
        print("Nedostaju TELEGRAM_BOT_TOKEN i/ili TELEGRAM_CHAT_ID.", file=sys.stderr)
        return 2
    return run(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
