# 🌐 OSC Universale, MIDI (`CC` / `Note` / `Program Change`) & Macro

**[⬅️ Indice Richiami Comandi](README.md)** · **[Manuale Italiano](../README.it.md)** · **[English Reference](../docs/OSC_MIDI_REFERENCE.md)**

Con **`+ Azione Avanzata`** ArtDirector controlla **qualsiasi** apparato o software compatibile **OSC (UDP)** o **MIDI Out** (DAW come `REAPER`, `Sonar/Cakewalk`, `Ableton`, tastiere/stage piano, synth hardware, processori chitarra/voce, `OBS Studio`, `TouchOSC`).

---

## 1. Invio OSC Universale (`kind: "osc"`)

| Campo | Cosa inserire | Note pratiche |
| :--- | :--- | :--- |
| **Host IP** | IP destinazione (es. `127.0.0.1` sullo stesso PC, `192.168.x.x` in rete) | Per XR18 / tablet / altro PC usa l'IP locale dell'apparato |
| **Porta UDP** | Porta OSC in ascolto sul software/mixer | XR18: `10024` · QLC+: `7700` · VirtualDJ: `9000` · REAPER / TouchOSC: `8000` / `9000` (vedi impostazioni dell'app) |
| **Indirizzo OSC** | Path standard OSC (es. `/ch/01/mix/fader`, `/track/1/mute`, `/vc/strobo`) | Deve iniziare con `/` |
| **Modalità OSC** | • **`Imposta valore fisso` (`set`)** — invia sempre il valore scelto<br>• **`Varia di +/-` (`relative`)** — somma/sottrae lo step tra `Min` e `Max`<br>• **`Alterna ON / OFF` (`toggle`)** — commuta automaticamente tra `Min` e `Max` | Con **`Varia di +/-`** usa passi piccoli (es. `0.050` o `0.100` su range `0.000..1.000`) e attiva **UDP Query** sui mixer Behringer per leggere la posizione reale del fader! |
| **Tipo OSC** | `float` o `int` | `float` per fader/percentuali (`0.0–1.0`); `int` per mute/switch (`0`/`1`) o scene |

### Esempi OSC Universali Pronti (REAPER / DAW / OBS)
- **REAPER Play / Stop / Record** *(dopo aver attivato Control Surface OSC su REAPER, porta `8000`)*:
  - Play: `/play` (`int` `1`) · Stop: `/stop` (`int` `1`) · Record: `/record` (`int` `1`)
  - Mute Traccia 1 (Toggle): `/track/1/mute/toggle` (`int` `1`, oppure `/track/1/mute` in modalità **`Alterna ON / OFF`** `Min=0, Max=1`)
  - Volume Traccia 1 (`+/-`): `/track/1/volume` in modalità **`Varia di +/-`**, Step `+0.050` / `-0.050`, `Min=0.0`, `Max=1.0`

---

## 2. MIDI Out (`CC`, `Note`, `Program Change`)

> **Prerequisito Windows per DAW sullo stesso PC:** se devi inviare MIDI verso un software sullo stesso PC (es. Cakewalk, REAPER, Kontakt, Ableton), crea una porta virtuale con **`loopMIDI`**. Per tastiere/expander hardware scegli direttamente l'interfaccia USB/MIDI nella tendina **`Porta MIDI Out:`**.

| Tipo Azione MIDI | Parametri | A cosa serve |
| :--- | :--- | :--- |
| **`Invio MIDI Program Change (Cambio Patch/Suono)`** | • `Porta MIDI Out`<br>• `Canale MIDI (1–16)`<br>• **`Programma / Patch (0–127)`**<br>• **`Bank MSB (CC#0, opzionale)`** *(-1 = Off)*<br>• **`Bank LSB (CC#32, opzionale)`** *(-1 = Off)* | **Tastiere & Stage Piano** (Yamaha, Roland, Nord, Korg…), **Pedaliere & Multieffetti Chitarra** (Helix, Kemper, Quad Cortex, Fractal, Boss), **Processori Voce** (TC Helicon). Richiama al volo un suono preciso semplicemente dicendo *"Piano & Pad"* o *"Solo Crunch"*! |
| **`Invio MIDI Control Change (CC)`** | `Porta MIDI Out`, `Canale (1–16)`, `Numero CC (0–127)`, `Valore (0–127)` | Controllo Volume (`CC#7`), Expression (`CC#11`), Modulation/Rotor (`CC#1`), Hold/Sustain (`CC#64`), Bypass blocchi FX (`0=OFF`, `127=ON`), Fader DAW |
| **`Invio MIDI Note`** | `Porta MIDI Out`, `Canale (1–16)`, `Nota (0–127)`, `Velocity (0–127)` | Avvio clip/pad su Ableton/sampler, trigger drum machine, cambio scena luci via MIDI-to-DMX (`Note On + Note Off`) |

> **Nota numerazione Program Change:** alcuni manuali di tastiere/pedaliere numerano i preset da `1 a 128` invece che da `0 a 127`. In quel caso **sottrai 1**: ad esempio il Preset `15` sul display corrisponde a **`Programma / Patch = 14`** in MIDI standard (`0–127`).

---

## 3. Macro DAW, Pop-up & Scorciatoie da Tastiera (`hotkey`)

### Sintassi Valida per `Scorciatoia da Tastiera (Hotkey)`
I tasti vanno separati da **`+`** e premuti **simultaneamente**:
- **Modificatori:** `<ctrl>`, `<alt>`, `<shift>`, `<cmd>` (o `<win>`)
- **Tasti speciali principali:** `space`, `enter`, `esc`, `tab`, `backspace`, `delete`, `insert`, `home`, `end`, `page_up`, `page_down`, **`up`**, **`down`**, **`left`**, **`right`**, `f1`..`f12`
- **Esempi validi:** `space`, `enter`, `<ctrl>+w`, `<ctrl>+s`, `<ctrl>+<up>`, `<alt>+f4` *(⚠️ scrivi `up` / `freccia su`, non `up arrow`)*.

### Ricetta Macro Sicura DAW: "Chiudi progetto attuale e apri brano `{nome}`"
1. **`Apri Progetto/File da Cartella`** *(ArtDirector verifica PRIMA che il brano esistente esista davvero — se non lo trova, annulla tutta la macro prima di chiudere il brano in esecuzione!)*
2. **`Scorciatoia da Tastiera`:** `<ctrl>+w` *(chiude progetto corrente)*
3. **`Tasto su eventuale Pop-up`:** `n`, Timeout `800 ms` *(risponde "No" se chiede di salvare modifiche, oppure non fa nulla se non compare alcun pop-up)*
4. **`Pausa (Wait)`:** `500 ms`
5. *(Se il passo 1 usa `Scorciatoia Apri` o apre da CLI, esegue automaticamente il caricamento del nuovo brano!)*
