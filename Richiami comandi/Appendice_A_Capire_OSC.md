# 🎓 Appendice A — Capire la Sintassi OSC Passo-Passo (*"Se vuoi fare quello, fa' questo"*)

**[⬅️ Torna al Manuale Italiano](../README.it.md)** · **[📋 Indice Prontuari](README.md)** · **[🇬🇧 English Version](../docs/APPENDIX_A_OSC_GUIDE.md)**

Non hai mai scritto un comando OSC in vita tua? Perfetto: **in 5 minuti capisci tutto quello che ti serve**, usando parole semplici ed esempi pronti da copiare dentro **`+ Azione Avanzata` → `Invio OSC universale`**.

---

## 1. Cos'è un messaggio OSC? (Analogia della Lettera Postale)

Immagina di dover mandare un ordine a distanza al tuo mixer o al programma luci. Un comando **OSC** ha solo **4 pezzi**, come una lettera:

| Campo in ArtDirector | Cos'è in parole povere | Esempio pratico |
| :--- | :--- | :--- |
| **1. Host IP** | **L'indirizzo della casa** (su quale macchina gira l'app/mixer) | • **`127.0.0.1`** = questo stesso PC *(es. QLC+, REAPER, VirtualDJ)*<br>• **`192.168.10.21`** = il tuo Behringer XR18 collegato via Wi-Fi o cavo LAN |
| **2. Porta UDP** | **Il numero del citofono / interno** di quel programma | • Behringer XR18: **`10024`**<br>• QLC+ Luci: **`7700`**<br>• VirtualDJ: **`9000`**<br>• REAPER / TouchOSC: **`8000`** *(o quella scelta nelle impostazioni dell'app)* |
| **3. Indirizzo OSC** | **Quale bottone o fader stai toccando** (scritto a blocchi separati da `/`) | `/ch/01/mix/fader` = *"Canale `01` ➔ sezione Mix ➔ Fader"* |
| **4. Valore + Tipo** | **Dove lo vuoi portare** | • **`int` `0` o `1`** = Interruttore (Spento / Acceso)<br>• **`float` da `0.000` a `1.000`** = Cursore o manopola (da `0%` al `100%`) |

> 💡 **Regola d'oro per non sbagliare mai `int` vs `float`:**  
> Se il controllo è **Acceso/Spento** (Mute, Phantom +48V, Scena, Gate ON) usa quasi sempre **`int`** (`0` oppure `1`).  
> Se il controllo è una **corsa continua** (Fader, Volume, Pan, Frequenza, Gain, Strobo dimmer) usa sempre **`float`** tra **`0.000`** e **`1.000`**.

---

## 2. Il Segreto della Scala Fader (`0.000` … `1.000`)

Sui mixer digitali (Behringer XR18/X32, Midas) e su quasi tutte le app OSC, i fader **non si scrivono in dB**, ma con un numero decimale tra **`0.000`** (tutto giù) e **`1.000`** (tutto su):

| Posizione Fader XR18 | Valore da mettere in `Valore OSC` | Significato sul palco |
| :--- | :--- | :--- |
| **Fondo corsa** | **`0.000`** | Silenzio (`-∞ dB`) |
| **Un quarto** | **`0.250`** | Molto basso (`-30 dB`) |
| **Metà corsa** | **`0.500`** | Basso / Sottofondo (`-10 dB`) |
| **Posizione `0 dB` (Unity)** | **`0.750`** | **Volume nominale standard (`0.0 dB`)** *(il valore più utile!)* |
| **Tutto su** | **`1.000`** | Massimo (`+10 dB`) |

---

## 3. Quale "Modalità OSC" devo scegliere?

In `+ Azione Avanzata` vedi 3 modalità. Ecco quando usare ciascuna:

1. **`Imposta valore fisso` (`set`)** — *"Porta quel fader sempre lì / Richiama sempre la Scena 3"*  
   Ogni volta che parli, invia esattamente quel numero. Perfetto per **Scene**, **Preset**, **Mute fisso**, o **Volume di partenza sicuro (`0.750`)**.
2. **`Varia di +/- (relativo tra Min e Max)` (`relative`)** — *"Alza un po' la voce / Abbassa un po' la chitarra"*  
   Legge dove si trova adesso il fader (spunta **"Leggi stato reale dal mixer prima di variare (UDP query)"**!) e aggiunge o toglie un passo (es. **`+0.050`** per alzare, **`-0.050`** per abbassare).
3. **`Alterna ON / OFF (Toggle Min <-> Max)` (`toggle`)** — *"Accendi/Spegni FX, Muta/Smuta con la stessa parola"*  
   Se ora è `0` invia `1`; se è già `1` invia `0`. Metti `Min = 0.000`, `Max = 1.000`, Tipo = `int`, e spunta **UDP query**.

---

## 4. Prontuario Pratico: *"Se vuoi fare quello ➔ Fa' questo"*

*(Nell'esempio immaginiamo il mixer XR18 su `192.168.10.21`, Porta `10024`. Sostituisci l'IP con il tuo!)*

### 🎤 "Se vuoi **mutare o smutare il Canale 1 con una sola parola (Toggle)** ➔ Fa' questo:"
1. Vai in **`App / Settings` ➔ scheda mixer ➔ `Nuova Funzione / Macro`**.
2. Registra la tua voce (es. *"Muta microfono"*), poi a destra clicca **`+ Azione Avanzata`**.
3. Compila così:
   - **Tipo azione:** `Invio OSC universale`
   - **Host IP:** `192.168.10.21` · **Porta UDP:** `10024`
   - **Indirizzo OSC:** `/ch/01/mix/on`
   - **Modalità OSC:** `Alterna ON / OFF (Toggle Min <-> Max)`
   - **Min:** `0.000` · **Max:** `1.000` · **Tipo OSC:** `int`
   - Spunta **"Leggi stato reale dal mixer (UDP query)"** → **`OK`** → **`CONFERMA`**.

### 🔊 "Se vuoi **alzare leggermente il Canale 2 (voce/chitarra) ogni volta che dici *Alza*** ➔ Fa' questo:"
1. Crea una nuova funzione, registra *"Alza chitarra"*, clicca **`+ Azione Avanzata`**.
2. Compila:
   - **Tipo azione:** `Invio OSC universale`
   - **Host IP:** `192.168.10.21` · **Porta UDP:** `10024`
   - **Indirizzo OSC:** `/ch/02/mix/fader`
   - **Modalità OSC:** `Varia di +/- (relativo tra Min e Max)`
   - **Valore / Step (+/-):** **`0.050`** *(per un secondo comando "Abbassa chitarra", crea un'altra funzione identica mettendo **`-0.050`**!)*
   - **Intervallo:** `Min = 0.000`, `Max = 1.000` · **Tipo OSC:** `float`
   - Spunta **UDP query** → **`OK`**.

### 🔁 "Se vuoi **togliere subito il riverbero (FX 1) quando parli col pubblico tra i brani** ➔ Fa' questo:"
- **Modo semplice (Smart):** **`+ Azione Avanzata`** → Tipo: **`Behringer XR18 / X-Air Smart`** → Comando: `muta fx return 1` *(e un altro comando `smuta fx return 1`)*.
- **Modo OSC diretto:** Tipo: `Invio OSC universale` → Indirizzo: `/rtn/1/mix/on` → Modalità: `Alterna ON / OFF`, Min `0`, Max `1`, Tipo `int`.

### 🎭 "Se vuoi **richiamare subito la Scena / Snapshot 3 del mixer** ➔ Fa' questo:"
- **Tipo azione:** `Invio OSC universale`
- **Indirizzo OSC:** `/-snap/load`
- **Modalità OSC:** `Imposta valore fisso` · **Valore:** `3` · **Tipo OSC:** `int`.

### 💡 "Se vuoi **accendere/spegnere lo Strobo in QLC+** ➔ Fa' questo:"
1. In **QLC+** attiva l'ingresso OSC (`Input/Output` ➔ plugin `OSC` su porta `7700`), crea un pulsante Strobo nella Virtual Console e clicca *Auto Detect* (oppure assegna percorso OSC `/vc/strobo`).
2. In ArtDirector: **`+ Azione Avanzata`** → **`Invio OSC universale`**:
   - **Host IP:** `127.0.0.1` · **Porta UDP:** `7700`
   - **Indirizzo OSC:** `/vc/strobo`
   - **Modalità OSC:** `Alterna ON / OFF` (`Min = 0`, `Max = 1`, `Tipo = float`) — oppure `Imposta valore fisso = 1.0` se il pulsante QLC+ fa già toggle da solo.

### 🎚️ "Se vuoi **cambiare 2 o 3 cose insieme con UNA sola frase (Macro Multi-Azione)** ➔ Fa' questo:"
*Esempio: Dici "Momento Acustico" ➔ abbassi la cassa, accendi il riverbero voce e accendi la luce calda!*  
Dentro **la stessa** `Nuova Funzione / Macro` (una sola registrazione vocale a sinistra!), clicca **`+ Azione Avanzata` tre volte** una sotto l'altra:
1. OSC `192.168.10.21:10024` ➔ `/ch/06/mix/fader` = `0.300` (`float`)
2. OSC `192.168.10.21:10024` ➔ `/rtn/1/mix/on` = `1` (`int`)
3. OSC `127.0.0.1:7700` ➔ `/vc/acustica` = `1.0` (`float`)  
Con un solo ordine vocale partono tutti e tre in pochi millisecondi!

---

## 5. Come scoprire il comando OSC di un programma o mixer nuovo?
1. Cerca su Google `<nome mixer o programma> OSC documentation` *(es. Behringer X-AIR OSC Protocol, TouchOSC, REAPER Default.ReaperOSC)*.
2. Molti programmi (come **QLC+**, **REAPER**, **VirtualDJ**, **TouchOSC**) mostrano o lasciano scegliere direttamente il path nella finestra **OSC / Control Surface** o hanno un pulsante **"Learn / Auto Detect"**: ti basta mandare un comando OSC di prova da ArtDirector (es. `/mio/comando/1`) mentre il software è in **Learn**, e il programma se lo associa da solo!
