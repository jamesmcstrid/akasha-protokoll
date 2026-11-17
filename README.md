# <img src="app/static/elefant.svg" alt="" width="44" align="top"> Akasha Meet

Transkribera möten på din egen Mac. Spela in direkt i webbläsaren, eller ladda upp en ljudfil.
Du får texten uppdelad per talare: **Talare 1**, **Talare 2** och så vidare, och du kan byta till riktiga namn.

- **Allt stannar på datorn.** Tal till text och talaruppdelning görs lokalt. Inget skickas till
  någon molntjänst.
- **Svensk taligenkänning** med [KB-Whisper](https://huggingface.co/KBLab/kb-whisper-medium) från
  Kungliga biblioteket. På Mac med Apple Silicon används grafikprocessorn (Metal).
- **Inspelningen tappas inte.** Ljudet sparas på disken var femte sekund under mötet.

## Använda

1. Öppna **http://127.0.0.1:8611** i Safari eller Chrome. Spara gärna sidan som bokmärke.
2. Välj hur många som pratar. Skriv gärna in namn och facktermer som förekommer, så stavas de rätt.
3. Tryck **Spela in**. När mötet är slut trycker du **Stoppa och transkribera**.
   Du kan också trycka **Ladda upp ljudfil…** och välja en fil, t.ex. från Röstmemon.
   Filnamnet används aldrig som rubrik, eftersom Röstmemon döper inspelningar efter platsen
   (en gatuadress). Utan rubrik heter inspelningen "Möte" och datum. Rubriken går att byta
   efteråt med **Byt rubrik**.
4. Vänta medan texten tas fram. Förloppet syns i listan. Det tar en stund för långa möten
   (se "Hur lång tid tar det?").
5. Skriv in vad talarna heter och tryck **Spara namn**. Kopiera texten eller ladda ner den som
   `.md` eller `.txt`. Klicka på en tid för att lyssna på just det stället.

### Digitala möten (Google Meet, Slack)

Välj **Digitalt i Chrome (t.ex. Google Meet eller Slack)** under "Var är mötet?". När du trycker
**Spela in** frågar Chrome vilken flik som ska delas: välj fliken med mötet och kryssa i
**Dela även flikljud**. Det fungerar med hörlurar, och med alla möten som körs i en Chrome-flik:
Google Meet, en Slack-huddle i Slack i Chrome (`app.slack.com`), Teams eller Zoom i webbläsaren.

- Din mikrofon och mötet spelas in i varsin kanal. Det du säger blir därför alltid **Du** (Talare 1),
  och bara de andra behöver delas upp efter röst.
- Räkna med dig själv i "Hur många pratar?". Tre betyder du och två till.
- Det fungerar bara i Chrome (och andra Chromium-webbläsare). Safari och Firefox kan inte dela
  ljudet från en flik.
- Alla i mötet ser inte att du spelar in, som de gör när Meet själv spelar in. Säg till.
- Kör du mötet med högtalare tar Chromes ekosläckning bort mötesljudet från din mikrofonkanal.
- Möten i **apparna** (Slack-appen, Teams, Zoom) har ingen flik att dela och stöds inte än. Öppna
  mötet i Chrome, eller kör med högtalare och välj "I samma rum". En Mac-hjälpare som hämtar ljudet
  direkt från apparna finns som förslag:
  [#1](https://github.com/jamesmcstrid/Akasha-Meet/issues/1).

**Tips:**

- Be alltid om lov innan du spelar in någon.
- Ställ datorn mellan er. Mikrofonen behöver höra alla ungefär lika bra.
- Låt fliken vara öppen och datorn vaken. Om locket stängs slutar inspelningen.
- Om fliken stängs eller datorn startas om ligger inspelningen kvar i listan som "Spelar in".
  Tryck **Avsluta och transkribera**, så transkriberas det som hann sparas.
- Kontrollera texten mot ljudet innan du använder den. Taligenkänning gör fel, särskilt på namn,
  siffror och när flera pratar samtidigt.

### Hur lång tid tar det?

Uppmätt på en MacBook Air med Apple Silicon, med testljudet `tva-talare.m4a` (57 sekunder, två talare):

| Motor | Totalt | varav talaruppdelning |
|---|---|---|
| whisper.cpp med Metal (standard på Apple Silicon) | **7,2 s** | 1,8 s |
| faster-whisper på processorn | 18,3 s | 1,9 s |

Räknat på samma sätt tar ett möte på en timme runt 8–10 minuter med Metal. DTW-justeringen, som
används när talare delas upp, kostar cirka 20 % (se "Vad som är testat"). Det är en uppskattning
utifrån korta klipp; ett riktigt långt möte är inte uppmätt.

## Installera

Kräver: en Mac (helst Apple Silicon), [Homebrew](https://brew.sh) och cirka 4 GB ledigt utrymme.
Öppna Terminal och kör:

```bash
brew install python@3.12 git
git clone git@github.com:jamesmcstrid/Akasha-Meet.git ~/akasha-meet
cd ~/akasha-meet
bash mac/installera.sh
```

Installationen skapar en Python-miljö och laddar ner modellerna (cirka 1,6 GB, bara första gången).
På Apple Silicon installerar den också `whisper-cpp` via Homebrew, så att grafikprocessorn används.
Den lägger in tjänsten så att den startar när du loggar in, och öppnar webbsidan. Första gången
du spelar in frågar webbläsaren om lov att använda mikrofonen.

Repot är privat. Du behöver läsrätt till det och en SSH-nyckel kopplad till ditt GitHub-konto.

Kontrollera att allt fungerar (tar några minuter):

```bash
bash halsokoll/prov.sh
```

Alla rader ska börja med `OK` och sista raden ska vara `PROV: OK`. Provet transkriberar
testljuden i `testljud/` och raderar sin provinspelning efteråt.

**Uppdatera:** `cd ~/akasha-meet && git pull && bash mac/installera.sh`

**Avinstallera:** `bash mac/avinstallera.sh`. Tjänsten stoppas, men inspelningar och modeller ligger
kvar tills du tar bort dem själv.

## Var hamnar inspelningarna?

I mappen `~/AkashaMeet` i din hemkatalog. Bara ditt konto kommer åt mappen. För varje inspelning
finns ljudet, en `.md` med texten och en `.json` med uppgifterna. **Radera** i listan tar bort alla
tre.

Mappen ligger medvetet inte i Dokument eller på Skrivbordet, eftersom de ofta synkas till iCloud.
Vill du ha den någon annanstans anger du `DATAKATALOG` i `.env`.

## Integritet och säkerhet

- Tjänsten lyssnar bara på `127.0.0.1`. Ingen annan dator i nätverket kommer åt den.
- Efter installationen kopplar den inte upp sig mot internet. Modellerna hämtas en gång från
  Hugging Face, med låsta versioner och kontrollerade kontrollsummor (sha256).
- Andra webbsidor du har öppna kan inte styra tjänsten. Den svarar bara på `localhost`, och allt som
  ändrar något kräver en särskild header som en främmande sida inte får skicka.
- Ingen språkmodell skriver om eller sammanfattar texten. Det whisper hör är det som står.

## Motorerna

Det finns två motorer för taligenkänningen, med samma modell (KB-Whisper medium):

- **whisper.cpp med Metal:** använder grafikprocessorn. Väljs automatiskt på Mac med Apple Silicon
  (`MOTOR=auto`, standard). Ungefär tre gånger snabbare än processorn på en MacBook Air.
- **faster-whisper:** körs på processorn och fungerar överallt, även på Intel-Mac. Används om
  whisper.cpp inte finns.

Vilken motor som används syns uppe till höger på webbsidan. Vill du tvinga fram en av dem sätter du
`MOTOR=faster` eller `MOTOR=whispercpp` i `.env` och kör `bash mac/installera.sh` igen. Talaruppdelningen
körs alltid på processorn.

## Inställningar

Allt har standardvärden. Vill du ändra något gör du det i `.env`, som skapas vid installationen.
Starta sedan om tjänsten med `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`.

| Inställning | Standard | Vad |
|---|---|---|
| `MOTOR` | `auto` | `auto` (Metal på Apple Silicon, annars processorn), `whispercpp` eller `faster` |
| `ORDLISTA` | tom | Ord som alltid ska stavas rätt, t.ex. företagets namn |
| `DATAKATALOG` | `~/AkashaMeet` | Var inspelningar och texter sparas |
| `PORT` | `8611` | Webbsidans port |
| `TALARE_TROSKEL` | `0.6` | Två röster som liknar varandra mer än så räknas som samma person (0–1) |
| `MAX_MB` | `1024` | Största fil som går att ladda upp |

## Felsökning

| Problem | Gör så här |
|---|---|
| `Bootstrap failed: 5` vid installation | Uppdatera (`git pull`) och kör `bash mac/installera.sh` igen. Hjälper inte det: Systeminställningar → Allmänt → Inloggningsobjekt, tillåt `bash` i bakgrunden |
| Sidan öppnas inte | `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`. Läs loggen `~/AkashaMeet/akasha-meet.log` |
| "Inte redo" uppe till höger | Håll muspekaren över texten för att se orsaken. Oftast saknas modellerna: `bash mac/hamta-modeller.sh` |
| "Fick inte tillgång till mikrofonen" | Tillåt mikrofonen för sidan i webbläsarens inställningar, och för webbläsaren i Systeminställningar → Integritet och säkerhet → Mikrofon |
| Fel antal talare, eller "bara 1 röst gick att skilja åt" | Tryck **Gör om** i listan med rätt antal. Rösterna skiljs lättare åt om ni sitter på ungefär samma avstånd från datorn |
| Inspelningen fastnade på "Spelar in" | Tryck **Avsluta och transkribera** i listan |

## Hur det fungerar

```
Webbläsaren (http://127.0.0.1:8611)
  ├─ spelar in med MediaRecorder och skickar ljudet i delar om 5 s ──┐
  └─ eller laddar upp en fil ─────────────────────────────────────────┤
                                                                      ▼
app/app.py (Flask, bara 127.0.0.1) ── sparar i ~/AkashaMeet ── köar ett jobb
  └─ bakgrundstråd, ett jobb åt gången:
       1. avkodar ljudet (PyAV)
       2. KB-Whisper medium: text med tidsstämpel per ord        app/motor.py
       3. vem pratar när:                                        app/talare.py
          röstavtryck (NeMo TitaNet small via sherpa-onnx) i fönster om 1,5 s
          längs talet, uppdelade i lika många grupper som antalet talare
       4. varje ord får gruppen som fönstren runt ordet liknar mest → repliker
       5. sparar .json och .md                                   app/lagring.py, app/export.py
```

| Mapp | Innehåll |
|---|---|
| `app/` | Tjänsten (`app.py`), motorerna, talaruppdelning, lagring, export, webbsidan i `static/` |
| `mac/` | `installera.sh`, `hamta-modeller.sh`, `kor.sh`, `avinstallera.sh`, launchd-mallen |
| `halsokoll/` | `prov.sh`: provet efter installation |
| `tester/` | Enhetstester. De behöver inga modeller |
| `testljud/` | Två testljud ur FLEURS, se `testljud/KALLOR.md` |

Köra enhetstesterna: `venv/bin/python -m unittest discover -s tester`

## Talaruppdelningen

Första versionen använde pyannote för att hitta talarbyten. I det första riktiga samtalet, två
personer inspelade med en MacBook Airs mikrofon, hittade den inga byten alls, och nästan allt hamnade
hos Talare 1. Nu används en annan metod som klarar samma inspelning:

1. whisper ger varje ord en tidsstämpel. Med whisper.cpp används DTW-justering för detta, eftersom
   de vanliga ordtiderna kunde hamna 0,6 s fel. DTW kräver att flash attention är av, så det slås
   bara på när talare ska delas upp.
2. Röstavtryck (NeMo TitaNet small) tas i glidande fönster om 1,5 sekunder där det pratas. Nästan
   tysta fönster hoppas över.
3. Avtrycken delas upp i lika många grupper som antalet talare. Är två grupper nästan lika
   (`TALARE_TROSKEL`) är det samma person. Då slås de ihop, och sidan säger till att färre röster
   gick att skilja åt i stället för att hitta på en talare. "Vet inte – gissa" provar 2, 3, 4 …
   grupper och stannar innan två grupper blir för lika, eller innan någon talare får mindre än
   1,5 s eget tal.
4. Varje ord får den grupp som fönstren närmast ordet liknar mest.

Utvärderat på ordnivå, med båda motorerna:

- **Tre konstgjorda dialoger med facit:** 100 % rätt talare, både med angivet antal och med "Vet inte".
- **Två inspelningar med bara en röst:** delades inte upp, med 2 angivet blev det en varning.
- **Konstgjort digitalt möte** (`testljud/digitalt-mote.webm`: du i vänster kanal, en kvinna och en
  annan man i höger): du blev alltid Talare 1, och de två andra blev två olika talare, med båda
  motorerna, både med angivet antal och med "Vet inte".
- **Det riktiga samtalet:** fick 2 talare med båda sätten. Bytena hamnade mellan rätt ord
  ("…det visste jag inte" | "kan du säga…"), och det korta "vad sa du?" blev en egen replik.
  Ett "mhm" mitt i en lång replik hamnade hos fel person.

Korta inpass på under en sekund är svårast. Underlaget är fortfarande litet.

## Vad som är testat

Provat 2026-11-17 i en Linux-miljö utan grafikprocessor, med samma Python- och biblioteksversioner:

- **Enhetstester:** 51 st, gröna. De täcker talaruppdelning, lagring av inspelningar i delar,
  export, skydd mot andra webbsidor och alla API-flöden.
- **`installera.sh` från början:** med en ersättare för launchd. Modellnedladdningen med
  sha256-kontroll gick igenom.
- **`halsokoll/prov.sh`:** grön med båda motorerna. Två talare blev rätt både med känt antal och
  med "Vet inte".
- **Digitalt möte i Chromium:** inspelning med mikrofonen i vänster kanal och en delad ljudström i
  höger. Mannen i mikrofonen blev **Du** och kvinnan i "mötet" Talare 2. Chromes testläge kan inte
  dela en riktig flik med ljud, så själva flikdelningen ersattes av en ljudström via samma
  `getDisplayMedia`.
- **Webbsidan i Chromium**, med en ljudfil som låtsasmikrofon:
  - inspelning, stopp, talaruppdelning, namn, kopiera, nedladdning, uppladdning och radering;
  - en inspelning där fliken stängdes mitt i, som sedan avslutades och transkriberades från listan.

**På en MacBook Air med Apple Silicon:**

- `installera.sh` och `halsokoll/prov.sh` gick gröna med båda motorerna, och `whisper-cli` använde
  Metal (tiderna ovan).
- Ett riktigt samtal mellan två personer spelades in via webbsidan i Chrome. Det avslöjade att
  pyannote inte hittade talarbytena, och det ledde till metoden ovan. Med den nya metoden blev
  bytena rätt även på Macen.
- DTW (utan flash attention) kostade lite: för samtalet på 48 s gick transkriberingen från 5,9 till
  7,1 s, och totalt tog det 8,3 s med talaruppdelningen.

**Inte provat än:**

- ett riktigt Google Meet-möte, där Chromes flikväljare och "Dela även flikljud" används på riktigt;
- automatiskt motorval (`MOTOR=auto`) på Mac: på MacBook Air var whisper.cpp vald uttryckligen;
- inspelning via webbsidan i **Safari** (Safari spelar in i ett annat format än Chrome);
- riktiga möten med personer som avbryter varandra.

Om inspelningen krånglar i Safari: använd Chrome.

## Källor och licenser

| Del | Licens |
|---|---|
| [KB-Whisper medium](https://huggingface.co/KBLab/kb-whisper-medium) (KBLab, Kungliga biblioteket) | Apache-2.0 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | MIT |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 |
| NeMo TitaNet small (NVIDIA), via sherpa-onnx | CC-BY-4.0 |
| Testljud: [Google FLEURS](https://huggingface.co/datasets/google/fleurs) | CC-BY-4.0 |
