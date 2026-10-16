import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot  # noqa: E402

# Kartice napravljene po strukturi koju Oglasi.rs stvarno vraća (naslov, cena, Sobnost, Kvadratura...)
CARD = """
<div class="oglas">
  <a href="/oglas/{id}/slug"><img src="x.jpg"></a>
  <div class="by">{by}</div>
  <div class="price"><b>{price} EUR</b></div>
  <h2><a href="/oglas/{id}/slug">{title}</a></h2>
  <div class="path"><a href="/nekretnine/prodaja-stanova/novi-sad-grad">Novi Sad grad</a> /
     <a href="/nekretnine/prodaja-stanova/telep-novi-sad">Telep</a></div>
  <div>Sobnost: <a href="/nekretnine/prodaja-stanova/telep-novi-sad/dvosoban"><b>{rooms}</b></a></div>
  <div>Kvadratura: <b>{area}m2</b></div>
  <div>Nivo u zgradi: <b>2. sprat</b></div>
  <p>{desc}</p>
  <div class="price2"><b>{price}</b> <b>EUR</b></div>
</div>
"""


def card(id, title="Stan", price="99.000,00", rooms="Dvosoban", area="45", by="oglas", desc="Opis"):
    return CARD.format(id=id, title=title, price=price, rooms=rooms, area=area, by=by, desc=desc)


class ParserTests(unittest.TestCase):
    def test_parses_cards(self):
        html = "<body>" + card("03-100", price="115.000,50", area="39", rooms="Jednoiposoban") + \
               card("03-101", by="JELENA NEKRETNINE, Novi Sad,Reg.br. 136") + "</body>"
        items = bot.parse_listing_page(html)
        self.assertEqual([i.id for i in items], ["03-100", "03-101"])
        a, b = items
        self.assertEqual(a.price_eur, 115000.50)
        self.assertEqual(a.area_m2, 39)
        self.assertEqual(a.rooms, "Jednoiposoban")
        self.assertIn("Telep", a.location)
        self.assertFalse(bot.is_agency(a))
        self.assertTrue(bot.is_agency(b))

    def test_duplicate_links_in_card_counted_once(self):
        self.assertEqual(len(bot.parse_listing_page(card("03-5"))), 1)


class FilterTests(unittest.TestCase):
    def make(self, **kw):
        base = dict(id="1", url="u", title="t", price_eur=100000, area_m2=40, rooms="Dvosoban",
                    header="oglas")
        base.update(kw)
        return bot.Listing(**base)

    def test_price_area_rooms(self):
        cfg = bot.CONFIG
        self.assertIsNone(bot.cheap_filter(self.make(), cfg))
        self.assertIsNone(bot.cheap_filter(self.make(price_eur=120000), cfg))
        self.assertIn("cena", bot.cheap_filter(self.make(price_eur=120001), cfg))
        self.assertIn("m2", bot.cheap_filter(self.make(area_m2=35), cfg))
        self.assertIsNone(bot.cheap_filter(self.make(area_m2=36), cfg))
        self.assertIn("struktura", bot.cheap_filter(self.make(rooms="Garsonjera"), cfg))
        self.assertIn("struktura", bot.cheap_filter(self.make(rooms="Jednosoban"), cfg))
        for r in ("Jednoiposoban", "Dvoiposoban", "Trosoban", "Četvorosoban i više"):
            self.assertIsNone(bot.cheap_filter(self.make(rooms=r), cfg), r)

    def test_agency_in_header_only(self):
        # "BEZ AGENCIJA" u opisu vlasnika ne sme da ga proglasi posrednikom
        owner = self.make(snippet="Prodajem stan. BEZ AGENCIJA, uknjižen.")
        self.assertFalse(bot.is_agency(owner))
        self.assertTrue(bot.is_agency(self.make(snippet="Agencijski ID: 135865, uknjižen")))

    def test_registered(self):
        yes = ["Uknjižen stan 1/1", "stan je uknjizen", "UKNJIŽENO", "ima list nepokretnosti"]
        no = ["Stan nije uknjižen", "neuknjižen", "u procesu uknjižbe", "nema uknjižbu", "bez uknjižbe"]
        for t in yes:
            self.assertIs(bot.check_registered(t), True, t)
        for t in no:
            self.assertIs(bot.check_registered(t), False, t)
        self.assertIsNone(bot.check_registered("Lep stan blizu centra"))

    def test_furnished(self):
        yes = ["Stan je namešten", "sa nameštajem", "kompletno opremljen", "nameštaj ostaje"]
        no = ["nenamešten stan", "stan nije namešten", "bez nameštaja", "prazan stan", "neopremljen"]
        for t in yes:
            self.assertIs(bot.check_furnished(t, False), True, t)
        for t in no:
            self.assertIs(bot.check_furnished(t, False), False, t)
        self.assertIs(bot.check_furnished("polunamešten", False), False)
        self.assertIs(bot.check_furnished("polunamešten", True), True)
        self.assertIsNone(bot.check_furnished("Lep stan", False))

    def test_detail_filter(self):
        cfg = dict(bot.CONFIG)
        ok = self.make(full_text="Uknjižen, namešten stan.")
        self.assertIsNone(bot.detail_filter(ok, cfg))
        self.assertEqual(ok.notes, [])

        unsure = self.make(full_text="Lep stan.")
        self.assertIsNone(bot.detail_filter(unsure, cfg))
        self.assertEqual(len(unsure.notes), 2)

        strict = dict(cfg, notify_if_unconfirmed=False)
        self.assertIsNotNone(bot.detail_filter(self.make(full_text="Lep stan."), strict))

        self.assertEqual(bot.detail_filter(self.make(full_text="Nije uknjižen, namešten"), cfg),
                         "nije uknjižen")
        self.assertEqual(bot.detail_filter(self.make(full_text="Uknjižen, nenamešten"), cfg),
                         "nije namešten")

    def test_message_escapes_html(self):
        l = self.make(title="A <b> & B", url="https://x/y?a=1&b=2", location="NS")
        msg = bot.format_message(l)
        self.assertIn("A &lt;b&gt; &amp; B", msg)
        self.assertIn("100.000 €", msg)


if __name__ == "__main__":
    unittest.main()
