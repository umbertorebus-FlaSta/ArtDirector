# 🚀 Guida Rapida per Pubblicare ArtDirector su GitHub

Tutto il repository è ora già pulito e pronto:
- **`README.md`** (Inglese internazionale) & **`README.it.md`** (Italiano) con tutte le **12 immagini** dentro `docs/images/`.
- **`Richiami comandi/`** & **`docs/OSC_MIDI_REFERENCE.md`** con tutte le tabelle OSC / Art-Net DMX / MIDI.
- **`.gitignore`** già configurato per escludere automaticamente i file personali e pesanti: `.venv/`, `dist/`, `ArtDirector_PenDrive/`, `models/`, `campioni/`, `configurazioni/`, `config.json`, `Manuale ArtDirector/`.
- **`LICENSE`** (**Apache License 2.0**, `Copyright 2026 umbertorebus-FlaSta`).

---

## Step 1 — Scegli il metodo più comodo per caricare il codice su GitHub

*(Sul tuo PC al momento `git` non è installato nel PATH di sistema. Puoi scegliere uno dei due metodi qui sotto — il **Metodo A** con GitHub Desktop è il più visivo e veloce!)*

### Metodo A — Via **GitHub Desktop** (Consigliato, zero comandi complessi)
1. Scarica e installa **GitHub Desktop** da `https://desktop.github.com` e accedi col tuo account **`umbertorebus-FlaSta`**.
2. Nel programma premi **`File` → `Add local repository...`** e scegli la cartella:  
   `C:\Users\Utente\Desktop\Antigravity\ArtDirector`
3. Comparirà *"This directory does not appear to be a Git repository"* → clicca **`create a repository`**, lascia **Name:** `ArtDirector`, **Git Ignore:** `None`, **License:** `None` *(ci sono già i nostri `.gitignore` e `LICENSE` Apache 2.0!)*.
4. Controlla l'elenco dei file proposti a sinistra: grazie a `.gitignore` **non devono comparire** `ArtDirector_PenDrive/`, `.venv/`, `models/`, `config.json` o file `.wav`.
5. Scrivi un titolo in basso a sinistra (es. `ArtDirector v1.0 - Initial public release`), premi **`Commit to main`** e poi **`Publish repository`** in alto! *(Deseleziona "Keep this code private" per renderlo pubblico e visibile a tutti nel mondo).*

### Metodo B — Via **Git da Terminale (PowerShell)**
1. Installa **Git for Windows** (`https://git-scm.com/download/win`) e riapri PowerShell nella cartella `C:\Users\Utente\Desktop\Antigravity\ArtDirector`.
2. Crea su GitHub un nuovo repository vuoto chiamato **`ArtDirector`** *(senza spuntare "Add a README")*.
3. Esegui questi comandi uno dopo l'altro:
   ```powershell
   git init
   git branch -M main
   git status
   ```
   *(Verifica con `git status` che NON appaiano `config.json`, `.wav`, `.venv/`, `models/` o `ArtDirector_PenDrive/`).*
   ```powershell
   git add .
   git commit -m "ArtDirector v1.0 - Initial public release"
   git remote add origin https://github.com/umbertorebus-FlaSta/ArtDirector.git
   git push -u origin main
   ```

---

## Step 2 — Pubblica l'eseguibile `.exe` nella sezione **Releases** *(Consigliato per amici & utenti!)*

Su GitHub i file `.exe` da ~150 MB non vanno messi nel codice normale ma nella scheda **Releases** a destra!

Il pacchetto pulito e privo di tuoi dati personali (`config.json` e `.wav` rimossi) è già pronto in:  
`C:\Users\Utente\Desktop\Antigravity\ArtDirector\dist\ArtDirector_v1.0_Windows_Portable.zip`

Per pubblicarlo su GitHub:
1. Nella pagina `https://github.com/umbertorebus-FlaSta/ArtDirector` clicca **`Releases`** (colonna di destra) → **`Create a new release`** (o **`Draft a new release`**).
2. Tag version: **`v1.0.0`** · Title: **`ArtDirector v1.0.0 — Windows Portable Release`**.
3. Trascina **`ArtDirector_v1.0_Windows_Portable.zip`** dalla cartella `dist/` nel riquadro degli allegati in basso e premi **`Publish release`**!

🎉 Fatto! Da quel momento sia i tuoi amici sia gli utenti di tutto il mondo potranno scaricare direttamente **`ArtDirector_v1.0_Windows_Portable.zip`** (senza installare Python!) oppure consultare il manuale illustrato e le tabelle OSC/MIDI!
