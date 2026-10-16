"""Test celog toka (lista -> detalj -> filter -> Telegram -> state) sa lažnom mrežom."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bot  # noqa: E402
from test_bot import card  # noqa: E402

LIST_HTML = "<body>" + "".join([
    card("03-1", title="Dobar stan", price="110.000,00", area="45", desc="Uknjižen, namešten."),
    card("03-2", title="Skup stan", price="150.000,00", area="60"),
    card("03-3", title="Agencija", by="X NEKRETNINE Reg. br. 5", price="90.000,00", area="50"),
    card("03-4", title="Nenamešten", price="100.000,00", area="50", desc="Uknjižen."),
]) + "</body>"

DETAIL = {
    "03-1": "Uknjižen, namešten stan, vlasnik.",
    "03-4": "Uknjižen ali nenamešten.",
}


class FlowTest(unittest.TestCase):
    def test_flow(self):
        sent = []
        with tempfile.TemporaryDirectory() as d:
            cfg = dict(bot.CONFIG, state_file=str(Path(d) / "seen.json"),
                       pages_per_url=1, request_delay_s=0)

            def fake_fetch(session, url):
                if "/oglas/" in url:
                    ad = url.rsplit("/oglas/", 1)[1].split("/")[0]
                    return f"<body><h1>x</h1><p>{DETAIL[ad]}</p></body>"
                return LIST_HTML

            with mock.patch.object(bot, "CONFIG", cfg), \
                 mock.patch.object(bot, "fetch", fake_fetch), \
                 mock.patch.object(bot, "send_telegram", lambda s, t: sent.append(t)):
                self.assertEqual(bot.run(dry_run=False), 0)
                self.assertEqual(len(sent), 1)
                self.assertIn("Dobar stan", sent[0])

                state = json.loads(Path(cfg["state_file"]).read_text())
                self.assertEqual(state["03-1"]["status"], "notified")
                self.assertEqual({k: v["status"] for k, v in state.items() if k != "03-1"},
                                 {"03-2": "rejected", "03-3": "rejected", "03-4": "rejected"})

                # drugi krug: ništa novo -> nema novih poruka
                self.assertEqual(bot.run(dry_run=False), 0)
                self.assertEqual(len(sent), 1)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = dict(bot.CONFIG, state_file=str(Path(d) / "seen.json"),
                       pages_per_url=1, request_delay_s=0)
            with mock.patch.object(bot, "CONFIG", cfg), \
                 mock.patch.object(bot, "fetch",
                                   lambda s, u: "<body><p>Uknjižen namešten</p></body>" if "/oglas/" in u else LIST_HTML), \
                 mock.patch.object(bot, "send_telegram", side_effect=AssertionError("ne sme da šalje")):
                bot.run(dry_run=True)
            self.assertFalse(Path(cfg["state_file"]).exists())


if __name__ == "__main__":
    unittest.main()
