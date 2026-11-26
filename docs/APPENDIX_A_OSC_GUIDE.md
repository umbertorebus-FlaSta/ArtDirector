# 🎓 Appendix A — Understanding OSC Step-by-Step (*"If you want to do X, do this"*)

**[⬅️ Back to README](../README.md)** · **[📡 Technical Reference](OSC_MIDI_REFERENCE.md)** · **[🇮🇹 Versione Italiana](../Richiami%20comandi/Appendice_A_Capire_OSC.md)**

Never written an OSC message before? **Five minutes is all you need.** Everything below maps directly to the fields inside **`+ Azione Avanzata` → `Invio OSC universale`**.

---

## 1. What Is an OSC Message? (The Postcard Analogy)

Think of an OSC message as sending an instruction across your network or inside your computer. It has just **4 simple parts**:

| Field in ArtDirector | Plain-English Meaning | Real Example |
| :--- | :--- | :--- |
| **1. Host IP** | **Which machine** receives it | • **`127.0.0.1`** = this very PC *(QLC+, REAPER, VirtualDJ, OBS)*<br>• **`192.168.10.21`** = your Behringer XR18 / tablet / second PC on LAN/Wi-Fi |
| **2. Porta UDP** | **Which door / intercom number** that app listens on | • Behringer XR18: **`10024`**<br>• QLC+ Lights: **`7700`**<br>• VirtualDJ: **`9000`**<br>• REAPER / TouchOSC: **`8000`** *(check the app's OSC settings)* |
| **3. Indirizzo OSC** | **Which knob, button, or fader** to touch (separated by `/`) | `/ch/01/mix/fader` = *"Channel `01` ➔ Mix section ➔ Fader"* |
| **4. Valore + Tipo** | **Where to set it** | • **`int` `0` or `1`** = Switch (OFF / ON) or Scene number<br>• **`float` `0.000` to `1.000`** = Slider / Knob position (`0%` to `100%`) |

> 💡 **Simple rule for `int` vs `float`:**  
> Switch (Mute, Phantom +48V, Gate ON, Snapshot number) ➔ **`int`**.  
> Continuous level/position (Fader, Pan, Gain, EQ, Frequency, Dimmer) ➔ **`float`** between **`0.000`** and **`1.000`**.

---

## 2. The Fader Scale (`0.000` … `1.000`) Explained

Digital mixers like the Behringer XR18 / X-AIR use normalized decimals instead of decibels:

| Physical Fader Position | OSC `float` Value | Real Stage Level |
| :--- | :--- | :--- |
| Bottom | **`0.000`** | Silence (`-∞ dB`) |
| Quarter | **`0.250`** | `-30 dB` |
| Halfway | **`0.500`** | `-10 dB` |
| **`0 dB` Mark (Unity)** | **`0.750`** | **Nominal `0.0 dB`** *(most common target!)* |
| Top | **`1.000`** | `+10 dB` |

---

## 3. Choosing the Right OSC Mode

- **`Imposta valore fisso` (`set`):** Always sends that exact number (great for Scene recalls, Unity `0.750`, fixed Mute/Unmute).
- **`Varia di +/-` (`relative`):** Queries current live value via UDP *(tick "Leggi stato reale / UDP query"!)* and nudges it up/down by your step (e.g. **`0.050`** up, **`-0.050`** down).
- **`Alterna ON / OFF` (`toggle`):** Automatically flips `0 <-> 1` on each spoken command using one single voice trigger!

---

## 4. Cookbook: *"If You Want to Do X ➔ Do This"*

*(Replace `192.168.10.21:10024` with your own mixer IP if different.)*

### 🎤 "If you want to **Mute/Unmute Channel 1 with one phrase (Toggle)** ➔ Do this:"
1. Open **`App / Settings` → Mixer tab → `Nuova Funzione / Macro`**.
2. Record your voice sample (e.g. *"Mute vocal"*), then click **`+ Azione Avanzata`**.
3. Set: **Invio OSC universale** · Host **`192.168.10.21`** · Port **`10024`** · Address **`/ch/01/mix/on`** · Mode **`Alterna ON / OFF`** · Min `0`, Max `1`, Type **`int`** · Tick **UDP query** ➔ **OK** ➔ **CONFERMA**.

### 🔊 "If you want to **nudge Channel 2 up slightly every time you say *Guitar up*** ➔ Do this:"
- Record *"Guitar up"* → **`+ Azione Avanzata`** → **Invio OSC universale**:  
  Host `192.168.10.21`, Port `10024`, Address **`/ch/02/mix/fader`**, Mode **`Varia di +/-`**, Step **`0.050`**, Min `0.000`, Max `1.000`, Type **`float`**, tick **UDP query**.  
  *(Make a second function `"Guitar down"` with Step **`-0.050`**!)*

### 🔁 "If you want to **kill Reverb (FX 1) immediately while speaking between songs** ➔ Do this:"
- **Quick Smart way:** **`+ Azione Avanzata`** → **`Behringer XR18 / X-Air Smart`** → Command: `muta fx return 1`.
- **Direct OSC way:** Address **`/rtn/1/mix/on`**, Toggle `0 <-> 1`, Type `int`.

### 🎭 "If you want to **recall Scene / Snapshot 3 on XR18** ➔ Do this:"
- Address **`/-snap/load`**, Mode `Imposta valore fisso`, Value **`3`**, Type **`int`**.

### 💡 "If you want to **toggle Strobe in QLC+** ➔ Do this:"
- Enable OSC input in QLC+ (`7700`), link your Virtual Console Strobe button to `/vc/strobo`, then in ArtDirector set Host **`127.0.0.1`**, Port **`7700`**, Address **`/vc/strobo`**, Mode **`Alterna ON / OFF`** (`0` to `1`, `float`).

### ⚡ "If you want **ONE spoken phrase to trigger Mixer + FX + Lights together** ➔ Do this:"
Record **one** voice sample (e.g. *"Acoustic Set"*) inside `Nuova Funzione / Macro`, then click **`+ Azione Avanzata`** three times in the right-hand step list:
1. `192.168.10.21:10024` ➔ `/ch/06/mix/fader` = `0.300` (`float`)
2. `192.168.10.21:10024` ➔ `/rtn/1/mix/on` = `1` (`int`)
3. `127.0.0.1:7700` ➔ `/vc/acustica` = `1.0` (`float`)

---

## 5. Finding OSC Paths for Any New Software or Gear
1. Search `<app or mixer name> OSC specification` (Behringer X-AIR, REAPER `Default.ReaperOSC`, TouchOSC, OBS WebSocket/OSC bridge).
2. In apps that offer **OSC Learn / Auto Detect** (QLC+, REAPER, VirtualDJ, TouchOSC), invent a clean custom path in ArtDirector (like `/stage/scene1`), trigger **Test (`► Testa`)**, and let the target software learn it automatically!
