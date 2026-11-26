# 📡 ArtDirector — Complete OSC, Art-Net DMX & MIDI Reference (English)

**[⬅️ Back to README](../README.md)** · **[🇮🇹 Versione Italiana](../Richiami%20comandi/README.md)**

Every address, curve, and step type listed below matches the actual implementation inside `art_director/targets/` and `art_director/core/executor.py`. Use these directly inside **`+ Azione Avanzata` → `Invio OSC universale`**, **`Behringer XR18 / X-Air Smart`**, **`Invio Art-Net DMX diretto`**, or **`Invio MIDI CC / Note / Program Change`**.

---

## 1. Behringer XR18 / X-AIR Edit v1.8.0 (OSC UDP Port `10024`)

### Value & Indexing Conventions
- **Channels:** Zero-padded `01..16` (`/ch/01/...` through `/ch/16/...`).
- **Bus / Aux Masters:** `1..6` (`/bus/1/...` .. `/bus/6/...`).
- **Channel Sends (`BB`):** `01..06` = Aux/Bus 1–6; `07..10` = FX Send 1–4 (`/ch/XX/mix/07/level` .. `/ch/XX/mix/10/level`).
- **X-AIR Fader Law (`float 0.0 – 1.0`):** `0.000` = `-∞ dB`, `0.250` = `-30 dB`, `0.500` = `-10 dB`, **`0.750` = `0.0 dB (Unity)`**, `1.000` = `+10 dB`.
- **Mute / Enable (`int`):** `1` = ON / Unmuted, `0` = OFF / Muted.

### 1.1 Input, Headamp, Link, Volume & Mute

| Control | OSC Address (`XX` = `01..16`) | Type / Range | `xr18_cmd` Smart Example |
| :--- | :--- | :--- | :--- |
| Channel Fader | `/ch/XX/mix/fader` | `float` `0.0..1.0` (`0.75 = 0 dB`) | `alza canale 7`, `canale 1 a 0 db` |
| Channel On / Mute | `/ch/XX/mix/on` | `int` (`1=ON`, `0=Mute`) | `muta canale 3`, `smuta voce` |
| Analog Gain | `/headamp/XX/gain` | `float` `0.0..1.0` (`-12..+60 dB`) | `canale 1 gain +24` |
| Phantom +48V | `/headamp/XX/phantom` | `int` (`0/1`) | `canale 1 phantom on` |
| Phase Invert (Ø) | `/ch/XX/preamp/invert` | `int` (`0/1`) | `inverti fase canale 3` |
| Analog / USB Switch | `/ch/XX/preamp/rtnsw` | `int` (`0=Analog`, `1=USB`) | `canale 1 usb on` |
| USB Return Trim | `/ch/XX/preamp/rtntrim` | `float` `0.0..1.0` (`-18..+18 dB`) | `canale 1 trim -3 db` |
| Stereo Channel Link | `/config/chlink/{1-2..15-16}` | `int` (`0/1`) | `collega canali 1 2` |

### 1.2 Noise Gate (`Gate` Tab)

| Control | OSC Address (`XX` = `01..16`) | Type / Range |
| :--- | :--- | :--- |
| Gate On / Off | `/ch/XX/gate/on` | `int` (`0/1`) |
| Mode | `/ch/XX/gate/mode` | `int`: `0=Exp 2:1`, `1=Exp 3:1`, `2=Exp 4:1`, `3=Gate`, `4=Ducker` |
| Threshold | `/ch/XX/gate/thr` | `float` `0.0..1.0` (`-80..0 dB`) |
| Range | `/ch/XX/gate/range` | `float` `0.0..1.0` (`3..60 dB`) |
| Attack / Hold / Release | `/ch/XX/gate/attack` · `/hold` · `/release` | `float` `0.0..1.0` (`0..120 ms` / `0.02..2000 ms` / `5..4000 ms`) |
| Sidechain Filter | `/ch/XX/gate/filter/on` · `/type` · `/f` | `0/1` · `0..8` (`LC6..HC12 / Q`) · `20 Hz..20 kHz` |
| Key Source | `/ch/XX/gate/keysrc` | `int`: `0=Self`, `1..16=Ch 1..16`, `17..22=Bus 1..6` |

### 1.3 Equalizer & HPF (`EQ` Tab)

| Control | OSC Address | Type / Range |
| :--- | :--- | :--- |
| Channel HPF On & Freq | `/ch/XX/preamp/hpon` · `/ch/XX/preamp/hpf` | `int` `0/1` · `float` `0.0..1.0` (`20..400 Hz` log) |
| Strip EQ On / Off | `/ch/XX/eq/on` · `/lr/eq/on` · `/bus/{1..6}/eq/on` | `int` (`0/1`) |
| Band Mode (`B=1..4` Ch, `1..6` Bus/LR) | `/.../eq/B/type` | `int`: `0=LCut`, `1=LShv`, `2=PEQ`, `3=VEQ`, `4=HShv`, `5=HCut` *(Bus/LR: no `0`/`5`)* |
| Band Frequency | `/.../eq/B/f` | `float` `0.0..1.0` (`20 Hz..20 kHz` log) |
| Band Gain | `/.../eq/B/g` | `float` `0.0..1.0` (`0.5 = 0 dB`, `-15..+15 dB`) |
| Band Q | `/.../eq/B/q` | `float` `0.0..1.0` (`Q 10.0..0.3` in 72 steps) |
| Main LR / Bus Global EQ Mode | `/lr/eq/mode` · `/bus/{1..6}/eq/mode` | `int`: `0=PEQ`, `1=GEQ`, `2=TEQ` |

### 1.4 Compressor (`Comp` Tab)

| Control | OSC Address (`XX` = `01..16`) | Type / Range |
| :--- | :--- | :--- |
| Comp On / Off | `/ch/XX/dyn/on` | `int` (`0/1`) |
| Mode / Detector / Env / Auto | `/ch/XX/dyn/mode` (`0=Comp,1=Exp`) · `/det` (`0=Peak,1=RMS`) · `/env` (`0=Lin,1=Log`) · `/auto` (`0/1`) | `int` |
| Threshold / Ratio / Knee | `/ch/XX/dyn/thr` (`-60..0 dB`) · `/ratio` (`0..11`: `1.1..100:1`) · `/knee` (`0..5` -> `0.0..1.0`) | `float` / `int` |
| Mix & Makeup Gain | `/ch/XX/dyn/mix` (`0..100%`) · `/mgain` (`0..24 dB`) | `float` `0.0..1.0` |
| Attack / Hold / Release | `/ch/XX/dyn/attack` · `/hold` · `/release` | `float` `0.0..1.0` |
| Sidechain Filter & KeySrc | `/ch/XX/dyn/filter/on\|type\|f` · `/keysrc` | Same mapping as Gate |

### 1.5 Sends, Main LR, FX, DCA, Mute Groups, AutoMix, Snapshots & RTA

| Control | OSC Address | Type / Range |
| :--- | :--- | :--- |
| Channel Send Level / On | `/ch/XX/mix/BB/level` · `/on` (`BB=01..10`) | `float` `0.0..1.0` · `int` `0/1` |
| Channel Send Pan / Tap | `/ch/XX/mix/BB/pan` · `/tap` | `float` (`0.5=Center`) · `int` (`0=In,1=PreEQ,2=PostEQ,3=PreFdr,4=PostFdr,5=SubGrp`) |
| Channel Pan & LR Assign | `/ch/XX/mix/pan` · `/ch/XX/mix/lr` | `float` (`0.5=Center`) · `int` `0/1` |
| Channel Insert | `/ch/XX/insert/on` · `/sel` (`0=OFF, 1..8=FX1L..FX4R`) | `int` |
| Main LR Fader & Mute | `/lr/mix/fader` · `/lr/mix/on` | `float` `0.0..1.0` · `int` `0/1` |
| Bus 1–6 Master & Mute | `/bus/{1..6}/mix/fader` · `/on` | `float` `0.0..1.0` · `int` `0/1` |
| FX Send / Return / Aux Return | `/fxsend/{1..4}/mix/...` · `/rtn/{1..4\|aux}/mix/...` · `/fx/{1..4}/insert` | `float` / `int` |
| DCA & Mute Group Flags | `/ch/XX/grp/dca` · `/ch/XX/grp/mute` | Bitmask `int` (`1..15` for groups `1..4`) |
| Global Mute Group 1–4 | `/config/mute/{1..4}` | `int` (`0/1`) |
| AutoMix | `/config/amixenable/{X\|Y}` (`0/1`) · `/ch/XX/automix/group` (`0=OFF,1=X,2=Y`) · `/weight` (`-12..+12 dB`) | `int` / `float` |
| Scene / Snapshot Recall | `/-snap/load` | `int` (`1..64`) |
| RTA Pos & Source | `/-stat/rta/pos` (`0=Pre, 1=Post`) · `/-stat/rta/source` (`0..15=Ch 1..16, 32=Monitor`) | `int` |

---

## 2. QLC+ Lighting (OSC `7700` · Art-Net UDP `6454` · WebSocket `9999`)

| Action | Protocol / Address | Values |
| :--- | :--- | :--- |
| Global Blackout | OSC `/blackout` | `float` (`1.0 = Active`, `0.0 = Off`); Art-Net zeros all 512 channels; WS `QLC+API\|setBlackout\|1\|0` |
| Grand Master Fader | OSC `/grandmaster` | `float 0.0–1.0` (`0–255` DMX; WS `QLC+API\|setGMValue\|<0..255>`) |
| Virtual Console Button | OSC `/vc/<button_slug>` (e.g. `/vc/strobo`, `/vc/fumo`) | `float` (`1.0 = ON`, `0.0 = OFF`; 80 ms pulse if `momentary=True`) |
| Direct Art-Net DMX (`artnet`) | UDP `6454`, Universe `0..32767` | Channel `1..512`, DMX `0..255` (`Art-Net\0` OpCode `0x5000`) |

---

## 3. VirtualDJ (OSC `9000` · MIDI · Hotkeys)

| Action | OSC Address | Default Hybrid Shortcuts / MIDI |
| :--- | :--- | :--- |
| Deck 1 / 2 Play-Pause | `/vdj/deck/{1\|2}/play_pause` (`1.0`) | `<ctrl>+1`, `<ctrl>+2` / Note `60` Ch `1..2` |
| Deck 1 / 2 Stop | `/vdj/deck/{1\|2}/stop` (`1.0`) | `<ctrl>+<shift>+1`, `<ctrl>+<shift>+2` / Note `61` Ch `1..2` |
| Load Track / Sidelist | `/vdj/deck/{1\|2}/load` · `/load_sidelist` (`1.0`) | `<ctrl>+<left>`, `<ctrl>+<right>`, `<alt>+l` / Note `62` |
| Browser Prev / Next | `/vdj/browser/prev` · `/vdj/browser/next` (`1.0`) | `up` / `down` |
| Next Cue | `/vdj/deck/{1\|2}/goto_cue` (`1.0`) | `n` / Note `63` Ch `1..2` |
| Crossfader / Automix | `/vdj/crossfader` (`0.0–1.0`) · `/vdj/automix` (`1.0`) | `<ctrl>+<alt>+1/2`, `<ctrl>+m` / CC `8` Ch `1` |
| Deck Gain & 3-Band EQ | `/vdj/deck/{1\|2}/gain` · `/eq_{low\|mid\|high}` (`0.0–1.0`) | CC `10`, `11`, `12`, `13` Ch `1..2` |

---

## 4. Universal OSC, MIDI & Hotkey Step Syntax (`+ Azione Avanzata`)

### Universal OSC Modes
- **`Imposta valore fisso` (`set`):** sends `osc_value` (`float` or `int`) directly.
- **`Varia di +/-` (`relative`):** queries live state via UDP *(recommended on XR18)* and adds/subtracts `osc_value` clamped between `Min` and `Max`.
- **`Alterna ON / OFF` (`toggle`):** toggles cleanly between `Min` and `Max`.

### MIDI Steps (`midi_cc`, `midi_note`, `midi_pc`)
- **MIDI Program Change (`midi_pc`):** `Port`, `Channel (1–16)`, `Program / Patch (0–127)`, optional `Bank MSB (CC#0, -1 = off)` and `Bank LSB (CC#32, -1 = off)` — built for hardware keyboards, stage pianos, synth modules, and guitar/vocal multi-FX pedals.
- **MIDI Control Change (`midi_cc`):** `Port`, `Channel (1–16)`, `CC (0–127)`, `Value (0–127)`.
- **MIDI Note (`midi_note`):** `Port`, `Channel (1–16)`, `Note (0–127)`, `Velocity (0–127)` (sends `note_on` + `note_off`).

### Keyboard Hotkeys (`hotkey`, `hotkey_if_dialog`)
Valid key tokens joined with `+` (simultaneous press):  
Modifiers: `<ctrl>`, `<alt>`, `<shift>`, `<cmd>`/`<win>`  
Special keys: `space`, `enter`, `esc`, `tab`, `backspace`, `delete`, `insert`, `home`, `end`, `page_up`, `page_down`, `up`, `down`, `left`, `right`, `f1`..`f12`, `num_0`..`num_9`, `num_add`, `num_sub`  
Examples: `space`, `<ctrl>+w`, `<ctrl>+<up>`, `<alt>+f`.
