# 💡 QLC+ Luci & 🎧 VirtualDJ — Tabelle Comandi (OSC · Art-Net · MIDI · Hotkey)

**[⬅️ Indice Richiami Comandi](README.md)** · **[Manuale Italiano](../README.it.md)**

---

## 1. QLC+ (OSC UDP `7700` · Art-Net UDP `6454` · WebSocket `9999`)

ArtDirector supporta **QLC+** in quattro modalità configurabili (`osc`, `artnet`, `websocket`, `osc_and_artnet`) oppure con invio diretto da **`+ Azione Avanzata`**.

| Funzione QLC+ | Indirizzo / Protocollo | Valori | Come usarlo al meglio |
| :--- | :--- | :--- | :--- |
| **Blackout Generale** | OSC `/blackout` | `float` (`1.0 = Attivo`, `0.0 = Off`) | In `artnet` azzera i 512 canali; in `websocket` invia `QLC+API\|setBlackout\|1\|0` |
| **Grand Master (Fader Generale)** | OSC `/grandmaster` | `float` `0.0 – 1.0` (`0% – 100%`) | Su Art-Net invia `0..255` sul canale Grand Master; su WebSocket `QLC+API\|setGMValue\|<0..255>` |
| **Pulsanti Virtual Console** | OSC `/vc/<nomepulsante>` *(es. `/vc/strobo`, `/vc/fumo`, `/vc/acustica`)* | `float` (`1.0 = ON`, `0.0 = OFF`) | In QLC+ abilita **External Input OSC** su `127.0.0.1:7700` e associa lo stesso indirizzo al pulsante/slider nella Virtual Console (con `momentary=True` invia impulso `80 ms`) |
| **DMX Diretto via Art-Net (`artnet`)** | UDP `127.0.0.1` o IP centralina, Porta **`6454`**, Universo `0..32767` | Canale `1..512`, Valore `0..255` | Usa **`+ Azione Avanzata` → `Invio Art-Net DMX diretto`** per accendere/regolare subito un canale DMX fisso o fare Blackout su tutto l'universo |

---

## 2. VirtualDJ (OSC `9000` · MIDI · Scorciatoie Ibride)

Puoi comandare **VirtualDJ** sia tramite **`+ Azione Avanzata` → `OSC` / `MIDI` / `Cerca & Scrivi Testo` / `Picking`**, sia tramite il routing automatico (`hybrid`, `osc`, `midi`, `shortcuts`).

| Azione | Indirizzo OSC (`Porta 9000`) | MIDI Default | Scorciatoia Ibrida Default |
| :--- | :--- | :--- | :--- |
| **Play / Pausa Deck 1** | `/vdj/deck/1/play_pause` (`1.0`) | Ch `1`, Note `60` | `<ctrl>+1` (o `space` su Deck attivo) |
| **Play / Pausa Deck 2** | `/vdj/deck/2/play_pause` (`1.0`) | Ch `2`, Note `60` | `<ctrl>+2` |
| **Stop Deck 1** | `/vdj/deck/1/stop` (`1.0`) | Ch `1`, Note `61` | `<ctrl>+<shift>+1` |
| **Stop Deck 2** | `/vdj/deck/2/stop` (`1.0`) | Ch `2`, Note `61` | `<ctrl>+<shift>+2` |
| **Carica Brano Deck 1 / 2** | `/vdj/deck/{1\|2}/load` (`1.0`) | Ch `1/2`, Note `62` | `<ctrl>+<left>` / `<ctrl>+<right>` (`enter` su attivo) |
| **Carica da Sidelist** | `/vdj/deck/{1\|2}/load_sidelist` (`1.0`) | Ch `1/2`, Note `62` | `<alt>+l` |
| **Naviga Lista (Su / Giù)** | `/vdj/browser/prev` · `/vdj/browser/next` (`1.0`) | — | `up` / `down` |
| **Next Cue** | `/vdj/deck/{1\|2}/goto_cue` (`1.0`) | Ch `1/2`, Note `63` | `n` |
| **Crossfader** | `/vdj/crossfader` (`0.0`=Deck1, `1.0`=Deck2) | Ch `1`, CC `8` | `<ctrl>+<alt>+1` / `<ctrl>+<alt>+2` |
| **Automix** | `/vdj/automix` (`1.0`) | — | `<ctrl>+m` |
| **Gain Deck 1 / 2** | `/vdj/deck/{1\|2}/gain` (`float 0.0–1.0`) | Ch `1/2`, CC `10` | — |
| **EQ Low / Mid / High Deck 1–2** | `/vdj/deck/{1\|2}/eq_{low\|mid\|high}` (`0.0–1.0`) | Ch `1/2`, CC `11`, `12`, `13` | — |

### 💡 Ricetta Veloce VirtualDJ: "Carica Brano Specifico a Voce"
1. In `App / Settings → VirtualDJ` premi **`+ Azione Avanzata`**.
2. Passo 1: **`Cerca / Scrivi Testo`** → `Scorciatoia prima`: tasto di ricerca VDJ (es. `F3`), `Testo`: nome esatto del brano (oppure `Sfoglia brano...`), spunta `Cancella testo precedente prima (<ctrl>+a)`, `Tasto dopo`: `enter` (o lascia vuoto).
3. Passo 2 *(opzionale)*: **`Pausa (200 ms)`** + **`Picking`** cliccando sul **Deck 1** o **Deck 2** per caricarlo subito!
