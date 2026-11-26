# 🎚️ Appendix B — Understanding Mackie Control (MCU) & MIDI for DAWs, Keyboards & Multi-FX (*"If you want to do X, do this"*)

**[⬅️ Back to README](../README.md)** · **[📡 OSC & MIDI Reference](OSC_MIDI_REFERENCE.md)** · **[🇮🇹 Versione Italiana](../Richiami%20comandi/Appendice_B_Mackie_Control_e_MIDI.md)**

Want hands-free voice control over **Sonar / Cakewalk, REAPER, Cubase, Ableton**, or instant patch changes on **hardware keyboards and guitar/vocal multi-FX units**? Here is the practical, zero-guesswork guide.

---

## 1. Connecting ArtDirector to a DAW on the Same PC (`loopMIDI`)

- **External hardware (synth, stage piano, guitar multi-FX):** pick your USB/MIDI output port directly in **`Porta MIDI Out:`** (e.g. `XR18 MIDI Out 2`).
- **Software DAW on the same Windows PC:** Windows does not let two apps open the same physical MIDI port together, so create one free virtual MIDI cable with **`loopMIDI`**:
  1. Launch **`loopMIDI`**, type a name (e.g. `ArtDirector_MIDI`), and click **`+`**.
  2. In **ArtDirector** (`+ Azione Avanzata`), choose **`ArtDirector_MIDI`** as `Porta MIDI Out:`.
  3. Inside your **DAW**, enable **`ArtDirector_MIDI`** as a **MIDI Input** / **Control Surface Input**.

---

## 2. How Mackie Control Universal (MCU) Works

**Mackie Control (MCU)** is supported out of the box by almost every DAW (**Cakewalk / Sonar, REAPER, Cubase, Studio One, Ableton Live, Logic**).  
Every MCU transport and channel button is triggered by a **standard `MIDI Note` message on Channel `1` (Velocity `127`)**:

| DAW Action (MCU Standard) | ArtDirector Step | Channel | Note Number (`0–127`) | Value (`Velocity`) |
| :--- | :--- | :---: | :---: | :---: |
| **Play** | `Invio MIDI Note` | `1` | **`94`** | `127` |
| **Stop** | `Invio MIDI Note` | `1` | **`93`** | `127` |
| **Record** | `Invio MIDI Note` | `1` | **`95`** | `127` |
| **Rewind (<<)** | `Invio MIDI Note` | `1` | **`91`** | `127` |
| **Fast Forward (>>)** | `Invio MIDI Note` | `1` | **`92`** | `127` |
| **Cycle / Loop Toggle** | `Invio MIDI Note` | `1` | **`86`** | `127` |
| **Click / Metronome** | `Invio MIDI Note` | `1` | **`89`** | `127` |
| **Bank Left / Right (-8 / +8 Tracks)** | `Invio MIDI Note` | `1` | **`46`** / **`47`** | `127` |
| **Channel Left / Right (-1 / +1)** | `Invio MIDI Note` | `1` | **`48`** / **`49`** | `127` |
| **Mute Track `1..8`** | `Invio MIDI Note` | `1` | **`16..23`** *(16=Tr.1 .. 23=Tr.8)* | `127` |
| **Solo Track `1..8`** | `Invio MIDI Note` | `1` | **`8..15`** *(8=Tr.1 .. 15=Tr.8)* | `127` |
| **Rec Arm Track `1..8`** | `Invio MIDI Note` | `1` | **`0..7`** *(0=Tr.1 .. 7=Tr.8)* | `127` |
| **Select Track `1..8`** | `Invio MIDI Note` | `1` | **`24..31`** *(24=Tr.1 .. 31=Tr.8)* | `127` |

> ⚠️ **About MCU Continuous Faders:** Standard Mackie Control faders use MIDI *Pitch Bend*, whereas ArtDirector currently sends **`MIDI Note`**, **`MIDI CC`**, and **`MIDI Program Change`**. For continuous DAW faders/pan via MIDI, use your DAW's **Generic Control Surface / ACT MIDI / Action MIDI Learn** with **`Invio MIDI CC`** (or use **OSC** / visual **Picking**)!

---

## 3. Cookbook: *"If You Want to Do X ➔ Do This"*

### ▶️ "If you want **Play / Stop / Mute in Cakewalk or REAPER via Mackie Control** ➔ Do this:"
1. Create `ArtDirector_MIDI` in **`loopMIDI`**.
2. Add a **Mackie Control** surface in your DAW pointing its MIDI Input to `ArtDirector_MIDI`.
3. In ArtDirector: **`App / Settings` → DAW tab → `Nuova Funzione / Macro`**, record your voice trigger, click **`+ Azione Avanzata`**:  
   **`Invio MIDI Note`** · Port **`ArtDirector_MIDI`** · Channel **`1`** · Note **`94`** (Play) or **`93`** (Stop) or **`16`** (Mute Track 1) · Velocity **`127`**.

### 🎚️ "If you want to **control DAW Track Volume or Plugin Bypass via MIDI Learn** ➔ Do this:"
1. Arm **MIDI Learn** / **ACT** in your DAW (REAPER Action List `Add`, Cakewalk ACT, Ableton `MIDI` mode).
2. Add **`+ Azione Avanzata` → `Invio MIDI Control Change (CC)`** (Port `ArtDirector_MIDI`, Channel `1`, unused CC e.g. `20`, Value `0` or `100`).
3. Click **`► Testa`** once in ArtDirector while the DAW is listening in Learn mode.

### 🎹 "If you want to **switch Patches/Sounds on a Keyboard or Multi-FX Pedal** ➔ Do this:"
1. Choose **`+ Azione Avanzata` → `Invio MIDI Program Change (Cambio Patch/Suono)`**.
2. Pick your hardware MIDI Out port, set **`Canale MIDI`** (`1–16`), set **`Programma / Patch (0–127)`** *(remember: hardware displays numbered `1–128` correspond to MIDI value `- 1`, so Patch `15` on screen = `14` in MIDI)*, and set optional **`Bank MSB (CC#0)`** / **`Bank LSB (CC#32)`** if needed.
