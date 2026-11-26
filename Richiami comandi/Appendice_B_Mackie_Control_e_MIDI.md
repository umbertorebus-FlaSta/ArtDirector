# 🎚️ Appendice B — Capire Mackie Control (MCU) & MIDI per DAW, Tastiere e Multieffetti (*"Se vuoi fare quello, fa' questo"*)

**[⬅️ Torna al Manuale Italiano](../README.it.md)** · **[📋 Indice Prontuari](README.md)** · **[🇬🇧 English Version](../docs/APPENDIX_B_MACKIE_CONTROL.md)**

Vuoi comandare **Sonar / Cakewalk, REAPER, Cubase, Ableton** (via **Mackie Control** o **MIDI Learn**) oppure cambiare suono su **tastiere e multieffetti** senza usare le mani? Qui trovi tutto spiegato in pratica, passo per passo.

---

## 1. Come collega ArtDirector una DAW sullo stesso PC? (Il "Cavo Virtuale" `loopMIDI`)

- **Se mandi MIDI a una tastiera o pedaliera esterna** *(collegata via USB o interfaccia esterna come `XR18 MIDI Out`)*: selezioni direttamente quella porta fisica nella tendina **`Porta MIDI Out:`** di ArtDirector.
- **Se mandi MIDI a un programma aperto sullo STESSO computer** *(es. Sonar/Cakewalk, REAPER, Cubase, Kontakt, Ableton)*: due programmi Windows non possono condividere un cavo fisico, quindi serve un **"cavo virtuale" gratuito** chiamato **`loopMIDI`** *(di Tobias Erichsen, installabile in 30 secondi)*.
  1. Apri **`loopMIDI`**, scrivi un nome in basso (es. `ArtDirector_MIDI`) e premi **`+`**.
  2. In **ArtDirector** (`+ Azione Avanzata` → `Invio MIDI...`) scegli **`ArtDirector_MIDI`** in `Porta MIDI Out:`.
  3. Nella tua **DAW**, apri le impostazioni **MIDI / Control Surfaces** e abilita in **Ingresso (Input)** la porta **`ArtDirector_MIDI`**.

---

## 2. Che cos'è Mackie Control (MCU) spiegato facile?

**Mackie Control Universal (MCU)** è un linguaggio MIDI standard inventato per far parlare le superfici di controllo con quasi tutte le DAW al mondo (**Sonar / Cakewalk, REAPER, Cubase, Studio One, Ableton, Logic**).  
Il suo grande vantaggio è che **tutti i pulsanti principali usano semplicemente dei normali messaggi `MIDI Note` sul Canale 1**: invece di inventare mappature da zero, attivi *Mackie Control* nella DAW e ArtDirector può già premere Play, Stop, Rec, Loop, Mute, Solo, Rec Arm e cambio banchi tracce!

### Tabella Comandi Standard Mackie Control (`Invio MIDI Note` · Canale `1` · Valore `127`)

| Comando sulla DAW | Azione ArtDirector | Canale MIDI | Numero Nota (`0–127`) | Valore (`Velocity`) |
| :--- | :--- | :---: | :---: | :---: |
| **Play** | `Invio MIDI Note` | `1` | **`94`** | `127` |
| **Stop** | `Invio MIDI Note` | `1` | **`93`** | `127` |
| **Record (Rec)** | `Invio MIDI Note` | `1` | **`95`** | `127` |
| **Rewind (<<)** | `Invio MIDI Note` | `1` | **`91`** | `127` |
| **Fast Forward (>>)** | `Invio MIDI Note` | `1` | **`92`** | `127` |
| **Cycle / Loop On-Off** | `Invio MIDI Note` | `1` | **`86`** | `127` |
| **Click / Metronomo On-Off** | `Invio MIDI Note` | `1` | **`89`** | `127` |
| **Bank Sinistra / Destra (-8 / +8 tracce)** | `Invio MIDI Note` | `1` | **`46`** / **`47`** | `127` |
| **Canale Precedente / Successivo (-1 / +1)** | `Invio MIDI Note` | `1` | **`48`** / **`49`** | `127` |
| **Mute Traccia `1..8`** | `Invio MIDI Note` | `1` | **`16..23`** *(16=Tr.1, 17=Tr.2 … 23=Tr.8)* | `127` |
| **Solo Traccia `1..8`** | `Invio MIDI Note` | `1` | **`8..15`** *(8=Tr.1 … 15=Tr.8)* | `127` |
| **Rec Arm Traccia `1..8`** | `Invio MIDI Note` | `1` | **`0..7`** *(0=Tr.1 … 7=Tr.8)* | `127` |
| **Seleziona Traccia `1..8`** | `Invio MIDI Note` | `1` | **`24..31`** *(24=Tr.1 … 31=Tr.8)* | `127` |

> ⚠️ **Nota tecnica importante sui Fader MCU:** nello standard Mackie Control originale i fader continui usano messaggi MIDI *Pitch Bend*, mentre ArtDirector invia **`MIDI Note`**, **`MIDI CC`** e **`MIDI Program Change`**.  
> Per muovere **fader di volume o pan** nella DAW a voce, vedi il caso pratico qui sotto (**ACT / MIDI Learn con `MIDI CC`**, oppure **OSC / Picking**)!

---

## 3. Prontuario Pratico: *"Se vuoi fare quello ➔ Fa' questo"*

### ▶️ "Se vuoi dare **Play / Stop / Mute in Sonar o REAPER con Mackie Control** (anche a finestra nascosta!) ➔ Fa' questo:"
1. Crea la porta **`ArtDirector_MIDI`** in **loopMIDI**.
2. Nella DAW aggiungi una superficie di controllo (**Sonar/Cakewalk:** *Preferenze → Superfici di controllo → `+` → Mackie Control* su Input `ArtDirector_MIDI`; **REAPER:** *Options → Preferences → Control/OSC/web → Add → Mackie Control Universal*, MIDI Input `ArtDirector_MIDI`).
3. In ArtDirector vai in **`App / Settings` → scheda DAW → `Nuova Funzione / Macro`**, registra *"Vai col Play"* (o *"Muta Traccia 1"*), poi clicca **`+ Azione Avanzata`**:
   - **Tipo azione:** `Invio MIDI Note`
   - **Porta MIDI Out:** `ArtDirector_MIDI` · **Canale MIDI:** `1`
   - **Numero Nota:** **`94`** per Play *(oppure **`93`** per Stop, **`16`** per Mute Traccia 1)*
   - **Valore (Velocity):** **`127`** → **`OK`** → **`CONFERMA`**.

### 🎚️ "Se vuoi **impostare Volume / Pan di una traccia DAW via MIDI** ➔ Fa' questo:"
*(In Sonar/Cakewalk con **ACT MIDI Controller** o in REAPER/Ableton con **MIDI Learn / Actions**)*:
1. Sulla traccia o azione della DAW apri **MIDI Learn** / **Add MIDI Shortcut** (in Cakewalk/Sonar usa *ACT MIDI Controller / Remote Control* sul fader; in REAPER usa *Actions → Show Action List → Add → MIDI CC*).
2. In ArtDirector aggiungi **`+ Azione Avanzata` → `Invio MIDI Control Change (CC)`**:
   - **Porta MIDI Out:** `ArtDirector_MIDI` · **Canale MIDI:** `1`
   - **Numero CC:** ad es. **`7`** *(o un CC libero da `20` a `31`)* · **Valore (`0–127`):** `100` *(circa 78%)* o `0` *(silenzio)* / `127` *(massimo)*.
3. Premi **`► Testa`** una volta dentro ArtDirector mentre la DAW è in **Learn**: la DAW riconosce il CC al volo!

### 🎹 "Se vuoi **cambiare suono/patch su una Tastiera o Multieffetti chitarra/voce** ➔ Fa' questo:"
1. Collega l'interfaccia MIDI/USB e assicurati che la tastiera/pedaliera riceva sullo stesso **Canale MIDI** (di solito **`1`**).
2. In ArtDirector: **`App / Settings` → `+ Azione Avanzata` → `Invio MIDI Program Change (Cambio Patch/Suono)`**:
   - **Porta MIDI Out:** la tua interfaccia (es. `XR18 MIDI Out 2` o USB Synth)
   - **Canale MIDI:** `1`
   - **Programma / Patch (`0–127`):** numero del preset *(se sulla tastiera leggi Preset `15`, inserisci **`14`** perché i display spesso partono da 1 mentre il MIDI parte da 0!)*
   - **Bank MSB (`CC#0`) / Bank LSB (`CC#32`):** lascia `Nessuno (off)` se i suoni sono nello stesso banco, oppure inserisci i due numeri dal manuale della tastiera per cambiare banco suoni!

### 🖱️ "Se la tua DAW o plugin non usa né MIDI né OSC (o vuoi la via più veloce!) ➔ Fa' questo:"
Usa semplicemente il **Picking Visivo (`Step 7–8`)** oppure **`Scorciatoia da Tastiera (Hotkey)`** (es. `space` per Play/Stop, `<ctrl>+w` per chiudere il progetto, `m` per mettere un Marker)!
