# Bot za oglase stanova (Novi Sad, od vlasnika)

Prati **oglasi.rs** i javlja na Telegram čim se pojavi stan koji ispunjava uslove:
od vlasnika · do 120.000 € · 36+ m² · jednoiposoban i veći · uknjižen · namešten.

KupujemProdajem je pripremljen kao poseban modul (`kupujemprodajem.py`), ali još nije aktivan
(vidi dole).

## 1. Telegram bot (5 min)

1. U Telegramu otvori **@BotFather** → `/newbot` → izaberi ime → dobićeš **token**.
2. Otvori svog novog bota i pošalji mu bilo koju poruku (npr. "start").
3. U browseru otvori `https://api.telegram.org/bot<TOKEN>/getUpdates` i u odgovoru nađi
   `"chat":{"id": 123456789 ...}`. To je tvoj **chat id**.

## 2. Prvi test na računaru

```bash
pip install -r requirements.txt
python bot.py --dry-run          # samo ispiše šta nalazi, ništa ne šalje
```

**Ovo uradi pre svega ostalog.** Parser je pisan prema strukturi stranice, ali nije testiran na
živom sajtu. Ako ispiše `Pročitano oglasa: 0` ili čudne vrednosti, javi mi izlaz i popravljam.

Zatim probaj Telegram:

```bash
export TELEGRAM_BOT_TOKEN="..."  TELEGRAM_CHAT_ID="..."
python bot.py --test-telegram
```

## 3. Pokretanje u oblaku (GitHub Actions)

1. Napravi GitHub repozitorijum (**public** je besplatan bez ograničenja minuta; u privatnom
   imaš 2000 min mesečno, što je oko granice za ovaj raspored) i okači ovaj folder.
2. *Settings → Secrets and variables → Actions → New repository secret*:
   `TELEGRAM_BOT_TOKEN` i `TELEGRAM_CHAT_ID`.
3. Tab *Actions* → "proveri-oglase" → **Run workflow** za prvi ručni start.

Posle toga radi sam na svakih ~15 min (06–24h). GitHub ume da kasni nekoliko minuta, i da pauzira
zakazane zadatke posle 60 dana bez aktivnosti u repozitorijumu (bot sam commit-uje
`state/seen.json`, što to sprečava).

> Rizik: ako Oglasi.rs blokira GitHub-ove IP adrese, workflow će pasti sa greškom. Tada bot može
> da radi na tvom računaru ili jeftinom VPS-u, isti kod.

## Kako odlučuje

| Kriterijum | Kako se proverava |
|---|---|
| Vlasnik | filter `rt=vlasnik` u URL-u + odbacuje oglase sa "Reg. br." / agencijskim imenom |
| Cena ≤ 120.000 € | iz kartice oglasa |
| 36+ m² | iz kartice |
| Jednoiposoban i veći | iz polja "Sobnost" (garsonjera i jednosoban otpadaju) |
| Uknjižen / namešten | traži u punom tekstu oglasa; izričita negacija ("nije uknjižen", "nenamešten", "polunamešten") odbacuje oglas |

Ako oglas **ne pominje** uknjiženost ili nameštenost, bot ga ipak šalje sa ⚠️ upozorenjem šta
da proveriš. Ako želiš strogo, u `bot.py` stavi `"notify_if_unconfirmed": False`.

Svi kriterijumi su na vrhu `bot.py` u `CONFIG`. Ako želiš dodatne filtere (kvart, sprat), primeni ih
na sajtu i zalepi dobijeni URL u `oglasi_rs_urls`.

## KupujemProdajem

Njihove stranice se učitavaju JavaScriptom, pa treba tačan API zahtev. Uputstvo je na vrhu
`kupujemprodajem.py`. Pošalji mi taj zahtev i dopisujem modul.

## Testovi

```bash
python -m unittest discover -s tests -v
```
