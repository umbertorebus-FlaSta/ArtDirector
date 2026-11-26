# 📋 Richiami Comandi — Tabelle OSC, Art-Net DMX & MIDI

**[⬅️ Torna al Manuale Italiano](../README.it.md)** · **[🇬🇧 English Technical Reference](../docs/OSC_MIDI_REFERENCE.md)**

Qui trovi tutti i prontuari rapidi verificati sul codice reale di **ArtDirector**, divisi per famiglia di apparati e protocolli. Puoi copiarli direttamente in **`+ Azione Avanzata`** (abbinati ai tuoi campioni audio vocali) oppure usarli via test/motore ibrido.

---

## Indice dei Prontuari

| Scheda | Apparati / Software | Protocolli / Livello |
| :--- | :--- | :--- |
| **[Appendice_A_Capire_OSC.md](Appendice_A_Capire_OSC.md)** | **Guida Passo-Passo OSC** (*"Se vuoi fare quello, fa' questo"*) | **Base** — Spiegato semplice + ricette pronte |
| **[Appendice_B_Mackie_Control_e_MIDI.md](Appendice_B_Mackie_Control_e_MIDI.md)** | **Mackie Control (MCU), `loopMIDI`, Tastiere & Multieffetti** | **Base** — Note MCU, CC, Program Change |
| **[OSC_Behringer_XR18_XAir.md](OSC_Behringer_XR18_XAir.md)** | Mixer **Behringer XR18 / X-AIR Edit v1.8.0** *(estendibile a XR16/XR12)* | OSC UDP `10024` + Smart Parser + Navigazione UI |
| **[OSC_ArtNet_QLC_VirtualDJ.md](OSC_ArtNet_QLC_VirtualDJ.md)** | **QLC+ Luci** · Centraline DMX Art-Net · **VirtualDJ** | OSC (`7700` / `9000`) · Art-Net UDP `6454` · WebSocket `9999` · MIDI · Hotkey |
| **[OSC_MIDI_Universale.md](OSC_MIDI_Universale.md)** | **Tastiere, Expander, Multieffetti, REAPER, Sonar, OBS, TouchOSC** | OSC Universale (`set` / `relative` / `toggle`) · MIDI `CC` / `Note` / `Program Change` · Hotkey & Macro |

---

## Promemoria Veloce d'Uso in ArtDirector

1. **Modalità 100% Campioni (`samples_only` / `samples_hybrid`, consigliata dal vivo):**  
   Apri `📱 App / Settings` ➔ scegli il programma ➔ **`Nuova Funzione / Macro`** (o **`+ Azione Avanzata`**), registra la tua parola/frase vocale e associa lo step **`OSC`**, **`Behringer XR18 Smart`**, **`Art-Net DMX`** o **`MIDI CC / Note / Program Change`**. Zero errori di trascrizione anche con nomi inventati o rumore di palco!
2. **Modalità Testo Ibrido (Vosk / Whisper):**  
   Con i motori testuali puoi anche pronunciare comandi variabili come `"UehBerì alza canale 7"`, `"UehBerì richiamo scena 3"` o `"Uesonà chiudi il progetto e apri {nome}"`.
