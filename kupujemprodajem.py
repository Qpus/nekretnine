"""KupujemProdajem modul - za sada NIJE aktivan.

KP učitava oglase preko JavaScripta (običan HTML je prazan), pa mu treba tačan
API zahtev koji njihova stranica šalje. Kad ga pošalješ, ovde se dopiše parsiranje.

Kako da ga pronađeš (2 minuta, Chrome):
  1. Otvori kupujemprodajem.com -> Nekretnine -> Stanovi -> Prodaja, primeni filtere
     (Novi Sad, cena do 120000 €, sortiranje "najnoviji").
  2. F12 -> kartica Network -> filter "Fetch/XHR" -> osveži stranicu.
  3. Nađi zahtev čiji odgovor sadrži listu oglasa (JSON), desni klik ->
     Copy -> Copy as cURL, i pošalji mi to (ukloni cookie/token ako postoji).
"""
from __future__ import annotations


def fetch_kupujemprodajem(session, cfg):
    print("KupujemProdajem: modul još nije podešen, preskačem.")
    return []
