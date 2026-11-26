# 🎛️ Behringer XR18 / X-AIR Edit v1.8.0 — Tabella Comandi OSC & Smart

**[⬅️ Indice Richiami Comandi](README.md)** · **[Manuale Italiano](../README.it.md)** · **[English Reference](../docs/OSC_MIDI_REFERENCE.md)**

> **Porta OSC UDP predefinita:** `10024` · **Host predefinito:** IP del mixer XR18 / X-AIR (es. `192.168.10.21` o `192.168.1.100`).

---

## 1. Convenzioni Indirizzi & Scale XR18

- **Canali:** sempre a 2 cifre `01`..`16` (`/ch/01/...` .. `/ch/16/...`).
- **Bus / Monitor Aux (`1`..`6`):** `/bus/1/...` .. `/bus/6/...` sui master; nelle mandate di canale a 2 cifre `01`..`06` (`/ch/XX/mix/01/level` .. `/ch/XX/mix/06/level`).
- **Mandate FX (`FX 1`..`FX 4`):** corrispondono ai bus `07`..`10` nelle mandate canale (`/ch/XX/mix/07/level` .. `/ch/XX/mix/10/level`).
- **Legge dei Fader (`float 0.000 – 1.000`):**
  - `0.000` = `-∞ dB`
  - `0.250` = `-30 dB`
  - `0.500` = `-10 dB`
  - **`0.750` = `0.0 dB (Unity / Nominal)`**
  - `1.000` = `+10.0 dB (Massimo)`
- **Stati ON / Mute (`int`):** `1` = Attivo (ON / Unmuted), `0` = Spento (OFF / Muted).

---

## 2. Channel Input, Gain, Phantom +48V, Fase, USB, Link & Volume

| Funzione | Indirizzo OSC (`XX`=`01..16`) | Tipo / Range | Comando `Behringer XR18 Smart` |
| :--- | :--- | :--- | :--- |
| **Fader / Volume Canale** | `/ch/XX/mix/fader` | `float` `0.0..1.0` (`0.75 = 0 dB`) | `"alza canale 7"`, `"canale 1 a 0 db"`, `"voce fader 75%"` |
| **Mute / Unmute Canale** | `/ch/XX/mix/on` | `int` (`1=ON`, `0=MUTE`) | `"muta canale 3"`, `"smuta voce"` |
| **Analog Gain (Preamp)** | `/headamp/XX/gain` | `float` `0.0..1.0` (`-12..+60 dB`) | `"canale 1 gain +24"`, `"alza gain chitarra"` |
| **Phantom +48V** | `/headamp/XX/phantom` | `int` (`0/1`) | `"canale 1 phantom on"` / `"off"` |
| **Invert Fase (Ø)** | `/ch/XX/preamp/invert` | `int` (`0/1`) | `"inverti fase canale 3"` |
| **Sorgente Analog / USB** | `/ch/XX/preamp/rtnsw` | `int` (`0=Analog`, `1=USB`) | `"canale 1 usb on"`, `"canale 1 analogico"` |
| **USB Return Trim** | `/ch/XX/preamp/rtntrim` | `float` `0.0..1.0` (`-18..+18 dB`) | `"canale 1 trim -3 db"` |
| **Stereo Link** | `/config/chlink/{1-2..15-16}` | `int` (`0/1`) | `"collega canali 1 2"`, `"separa canali 3 4"` |

---

## 3. Noise Gate (Scheda `Gate`)

| Funzione | Indirizzo OSC (`XX`=`01..16`) | Tipo / Range | Comando `Behringer XR18 Smart` |
| :--- | :--- | :--- | :--- |
| **Gate On / Off** | `/ch/XX/gate/on` | `int` (`0/1`) | `"gate canale 1 on"` / `"off"` |
| **Gate Mode** | `/ch/XX/gate/mode` | `int` (`0=Exp2:1`, `1=Exp3:1`, `2=Exp4:1`, `3=Gate`, `4=Ducker`) | `"canale 1 gate ducker"`, `"canale 2 gate exp3"` |
| **Threshold (Soglia)** | `/ch/XX/gate/thr` | `float` `0.0..1.0` (`-80..0 dB`) | `"gate canale 1 soglia -54"` |
| **Range (Attenuazione)** | `/ch/XX/gate/range` | `float` `0.0..1.0` (`3..60 dB`) | `"gate canale 1 range 40"` |
| **Attack / Hold / Release** | `/ch/XX/gate/attack` · `/hold` · `/release` | `float` (`0..120ms` · `0.02..2000ms` · `5..4000ms`) | `"gate ch 1 attack 2 ms"`, `"gate ch 1 release 150 ms"` |
| **Sidechain Filter** | `/ch/XX/gate/filter/on` · `/type` · `/f` | `0/1` · `0..8` (`LC6/LC12/HC6/HC12/1..10`) · `20Hz..20kHz` | `"gate ch 1 filter on"`, `"gate ch 1 filter 990 hz"` |
| **Sidechain KeySrc** | `/ch/XX/gate/keysrc` | `int` (`0=Self`, `1..16=Ch`, `17..22=Bus1..6`) | `"gate ch 4 keysrc canale 6"` |

---

## 4. Equalizzatore & HPF (Scheda `EQ`)

| Funzione | Indirizzo OSC | Tipo / Range | Comando `Behringer XR18 Smart` |
| :--- | :--- | :--- | :--- |
| **Low Cut / HPF Canale** | `/ch/XX/preamp/hpon` · `/preamp/hpf` | `int` `0/1` · `float` (`20..400 Hz`) | `"canale 1 low cut 100 hz"`, `"hpf voce off"` |
| **EQ Strip On / Bypass** | `/ch/XX/eq/on` · `/lr/eq/on` · `/bus/{1..6}/eq/on` | `int` (`0/1`) | `"eq canale 1 on"`, `"bypass eq master"` |
| **Tipo Filtro Banda `B`** | `/.../eq/B/type` (`B=1..4` Ch, `1..6` Bus/LR) | `0=LCut`, `1=LShv`, `2=PEQ`, `3=VEQ`, `4=HShv`, `5=HCut` | `"eq ch 1 banda 1 lshv"` *(Bus/LR: solo LShv, PEQ, VEQ, HShv)* |
| **Frequenza Banda `B`** | `/.../eq/B/f` | `float` (`20 Hz..20 kHz` log) | `"eq ch 1 banda 2 freq 500 hz"` |
| **Gain Banda `B`** | `/.../eq/B/g` | `float` `0.0..1.0` (`0.5=0dB`, `-15..+15dB`) | `"canale 11 bassi -3 db"`, `"alza medi voce di 2 db"` |
| **Q (Larghezza) Banda `B`** | `/.../eq/B/q` | `float` (`Q 10.0..0.3` in 72 step) | `"eq ch 1 banda 2 stringi"`, `"eq ch 1 b2 q 4.0"` |
| **Flat / Reset / Modo Bus** | `/lr/eq/mode` · `/bus/{1..6}/eq/mode` | `0=PEQ`, `1=GEQ`, `2=TEQ` | `"eq ch 1 flat"`, `"eq master reset"`, `"eq master geq"` |

---

## 5. Compressore (Scheda `Comp`)

| Funzione | Indirizzo OSC (`XX`=`01..16`) | Tipo / Range | Comando `Behringer XR18 Smart` |
| :--- | :--- | :--- | :--- |
| **Compressor On / Off** | `/ch/XX/dyn/on` | `int` (`0/1`) | `"attiva compressore ch 1"` |
| **Mode / Detector / Env** | `/ch/XX/dyn/mode` (`0=Comp,1=Exp`) · `/det` (`0=Peak,1=RMS`) · `/env` (`0=Lin,1=Log`) | `int` (`0/1`) | `"comp ch 1 rms"`, `"comp ch 1 log"` |
| **Auto Time** | `/ch/XX/dyn/auto` | `int` (`0/1`) | `"comp ch 1 auto time on"` |
| **Threshold / Ratio / Knee** | `/ch/XX/dyn/thr` (`-60..0dB`) · `/ratio` (`0..11`: `1.1..100:1`) · `/knee` (`0..5` -> `0..1`) | `float` / `int` | `"comp ch 1 soglia -25"`, `"comp ch 1 ratio 3"`, `"comp ch 1 knee 5"` |
| **Mix (%) & Makeup Gain** | `/ch/XX/dyn/mix` (`0..100%`) · `/mgain` (`0..24 dB`) | `float` `0.0..1.0` | `"comp ch 1 mix 100%"`, `"comp ch 1 makeup +6 db"` |
| **Attack / Hold / Release** | `/ch/XX/dyn/attack` · `/hold` · `/release` | `float` `0.0..1.0` | `"comp ch 1 attack 10 ms"`, `"comp ch 1 release 150 ms"` |
| **Sidechain Filter & KeySrc** | `/ch/XX/dyn/filter/on|type|f` · `/keysrc` | come Gate | `"comp ch 4 keysrc canale 1"` |

---

## 6. Sends / Mandate, Tap Point & Routing (Scheda `Sends`)

| Funzione | Indirizzo OSC (`XX`=`01..16`, `BB`=`01..10`) | Tipo / Range | Comando `Behringer XR18 Smart` |
| :--- | :--- | :--- | :--- |
| **Livello Mandata → Bus/FX** | `/ch/XX/mix/BB/level` (`01..06=Bus`, `07..10=FX`) | `float` `0.0..1.0` | `"alza send canale 2 su fx 1"`, `"mandata voce spia 1 -6 db"` |
| **On / Off Mandata** | `/ch/XX/mix/BB/on` | `int` (`0/1`) | `"muta mandata chitarra su bus 2"` |
| **Pan Mandata** | `/ch/XX/mix/BB/pan` | `float` (`0.5=Centro`) | `"pan mandata ch 1 bus 2 centro"` |
| **Tap Point Mandata** | `/ch/XX/mix/BB/tap` | `0=Input`, `1=PreEQ`, `2=PostEQ`, `3=PreFader`, `4=PostFader`, `5=SubGroup` | `"mandata ch 1 bus 1 pre fader"`, `"ch 1 fx 1 post fader"` |

---

## 7. Main LR, Bus Masters, FX, DCA, Mute Groups, AutoMix, Scene & RTA

| Funzione | Indirizzo OSC | Tipo / Range | Comando `Behringer XR18 Smart` |
| :--- | :--- | :--- | :--- |
| **Main LR Fader & Mute** | `/lr/mix/fader` · `/lr/mix/on` | `float 0.0..1.0` · `int 0/1` | `"master a 0 db"`, `"muta master"` |
| **Bus 1..6 Master & Mute** | `/bus/{1..6}/mix/fader` · `/bus/{1..6}/mix/on` | `float 0.0..1.0` · `int 0/1` | `"alza master bus 6"`, `"muta monitor 1"` |
| **FX Send 1..4 & Return 1..4** | `/fxsend/{1..4}/mix/on|fader` · `/rtn/{1..4}/mix/on|fader` | `int` / `float` | `"alza fx return 1"`, `"muta fx send 2"` |
| **Aux / USB Return Master** | `/rtn/aux/mix/on` · `/rtn/aux/mix/fader` | `int` / `float` | `"alza aux return"`, `"muta usb return"` |
| **Pan & Main LR Assign (Ch)** | `/ch/XX/mix/pan` · `/ch/XX/mix/lr` | `float` (`0.5=Centro`) · `int 0/1` | `"pan ch 3 sinistra 40"`, `"canale 5 lr off"` |
| **Insert Canale & FX Insert** | `/ch/XX/insert/on|sel` (`0=OFF,1..8=FX1L..4R`) · `/fx/{1..4}/insert` | `int` | `"canale 1 insert fx 2"`, `"fx 1 insert on"` |
| **DCA 1..4 & Mute Grp 1..4 (Ch)** | `/ch/XX/grp/dca` · `/ch/XX/grp/mute` | Bitmask `int` (`0..15`) | `"canale 1 dca 2 on"`, `"canale 3 mute group 1"` |
| **Mute Group Globali 1..4** | `/config/mute/{1..4}` | `int` (`0/1`) | `"attiva mute group 1"` |
| **AutoMix X/Y & Weight** | `/config/amixenable/{X|Y}` · `/ch/XX/automix/group|weight` | `int` · `0..2` · `-12..+12 dB` | `"automix x on"`, `"ch 1 automix weight +3 db"` |
| **Richiamo Scena / Snapshot** | `/-snap/load` | `int` (`1..64`) | `"richiama scena 3"`, `"preset acustica"` |
| **RTA Posizione & Sorgente** | `/-stat/rta/pos` (`0=Pre,1=Post`) · `/-stat/rta/source` (`0..15=Ch, 32=Mon`) | `int` | `"rta post"`, `"rta canale 1"` |

---

## 8. Navigazione Tab & Finestre `X-AIR-Edit` v1.8.0 (via Smart Command)

ArtDirector può cambiare schermata direttamente dentro **`X-AIR-Edit`** con comandi `xr18_cmd`:
- **Tab principali (0–9):** `"apri tab mixer"`, `"apri tab channel"`, `"apri tab input"`, `"apri tab gate"`, `"apri eq canale 3"`, `"apri comp canale 1"`, `"apri tab sends"`, `"apri tab main"`, `"apri tab fx"`, `"apri tab meter"`.
- **Finestre utility (`F1..F10` / `Shift+F...`):** `"finestra fx 1"`, `"finestra snapshot"`, `"finestra recorder"`, `"finestra meter"`, `"finestra rta"`, `"apri setup"`, `"apri routing"`, `"apri dca"`.
