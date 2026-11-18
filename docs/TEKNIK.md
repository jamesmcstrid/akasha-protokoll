# Akasha Meet: teknik och tester

Hur Akasha Meet fungerar inuti, hur talaruppdelningen gick till och vad som är testat.
Användning och installation står i [README](../README.md).

## Hur det fungerar

```
Webbläsaren (http://127.0.0.1:8611)
  ├─ spelar in med MediaRecorder och skickar ljudet i delar om 5 s ──┐
  │    digitalt möte: mikrofonen i vänster kanal, mötesfliken i höger │
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
| `app/` | Tjänsten (`app.py`), motorerna (`motor.py`), talaruppdelningen (`talare.py`), lagring, export och webbsidan i `static/` |
| `mac/` | `installera.sh`, `hamta-modeller.sh`, `kor.sh`, `avinstallera.sh` och launchd-mallen |
| `halsokoll/` | `prov.sh`: provet efter installation. `sammanfatta.sh` och `talardiagnos.sh`: hur en transkribering gick, utan att visa texten (se nedan) |
| `tester/` | Enhetstester. De behöver inga modeller |
| `testljud/` | Tre testljud ur FLEURS, se [KALLOR.md](../testljud/KALLOR.md) |
| `docs/` | Den här filen och bilderna till README |

Köra enhetstesterna:

```bash
venv/bin/python -m unittest discover -s tester
```

## Talaruppdelningen

Första versionen använde pyannote för att hitta talarbyten. I det första riktiga samtalet, två
personer inspelade med en MacBook Airs mikrofon, hittade den inga byten alls, och nästan allt hamnade
hos Talare 1. Nu används en annan metod som klarar samma inspelning:

1. whisper ger varje ord en tidsstämpel. Med whisper.cpp används DTW-justering för detta, eftersom
   de vanliga ordtiderna kunde hamna 0,6 s fel. DTW kräver att flash attention är av, så det slås
   bara på när talare ska delas upp. Det kostar cirka 20 % i tid.
2. Röstavtryck (NeMo TitaNet small) tas i glidande fönster om 1,5 sekunder där det pratas. Nästan
   tysta fönster hoppas över.
3. Avtrycken delas upp i lika många grupper som antalet talare. Är två grupper nästan lika
   (`TALARE_TROSKEL`) är det samma person. Då slås de ihop, och sidan säger till att färre röster
   gick att skilja åt i stället för att hitta på en talare. "Vet inte – gissa" provar 2, 3, 4 …
   grupper och stannar innan två grupper blir för lika, eller innan någon talare får mindre än
   1,5 s eget tal.

   Hur lika två grupper är beror på hur stora de är. Har båda minst 30 s tal jämförs de
   ursprungliga grupperna med varandra, och likheten blir snittet. Annars jämförs gruppernas
   samlade röster. Skälet: en sammanslagen grupps samlade röst hamnar mellan delarna och blir
   mer lik en tredje grupp än någon av delarna är. I ett riktigt möte med fem personer slogs en
   person med 17 minuters tal därför ihop med mötesledaren, trots att den liknade båda delarna
   av mötesledarens röst mindre än gränsen. För en kort grupp är det tvärtom bra: dess egen röst
   är osäker, och det är oftast en kort avvikelse hos någon som redan finns.
4. Varje ord får den grupp som fönstren närmast ordet liknar mest.

**Digitala möten:** mikrofonen och mötesfliken ligger i varsin kanal. Ett ord hör till den kanal
som är starkast under ordet, om den är minst dubbelt så stark; annars får ordet samma som närmaste
säkra ord. Det du säger blir alltid Talare 1 ("Du"). Bara de andra (höger kanal) delas upp efter
röst, enligt stegen ovan.

Utvärderat på ordnivå, med båda motorerna:

- **Tre konstgjorda dialoger med facit:** 100 % rätt talare, både med angivet antal och med "Vet inte".
- **Två inspelningar med bara en röst:** delades inte upp, med 2 angivet blev det en varning.
- **Konstgjort digitalt möte** (`testljud/digitalt-mote.webm`: du i vänster kanal, en kvinna och en
  annan man i höger): du blev alltid Talare 1, och de två andra blev två olika talare, både med
  angivet antal och med "Vet inte".
- **Ett riktigt samtal:** fick 2 talare med båda sätten. Bytena hamnade mellan rätt ord
  ("…det visste jag inte" | "kan du säga…"), och det korta "vad sa du?" blev en egen replik.
  Ett "mhm" mitt i en lång replik hamnade hos fel person.

- **Ett riktigt möte med fem personer** (1 h 24 min, laptopens mikrofon): bara tre talare
  hittades. `halsokoll/talardiagnos.sh` visade att fyra röster gick att skilja åt, men att en
  person med 17 minuters tal hade slagits ihop med mötesledaren. Tidsmönstret bekräftade det: när
  den personen pratade mer pratade mötesledaren mindre. Därför ändrades sammanslagningen (punkt 3).
- **Tre möten ur AMI-korpusen** (engelska, riktiga möten med 3–4 personer, en mikrofon mitt i
  rummet, 30–48 min): med rätt antal angivet blev 75, 83 och 89 % av orden rätt talare. Med en
  talare för mycket angiven blev antalet ändå rätt. "Vet inte" gav rätt antal i två av tre möten.
  Den gamla och den nya sammanslagningen gav samma resultat.
- **Fem inspelningar med en person ur AMI** (4–6 min, samma mikrofon): med 2 angivna och med
  "Vet inte" blev det alltid en talare. Med 3–5 angivna blev det ofta 2–3 talare, med båda
  sätten att slå ihop (den nya gav en gång fler: 2 i stället för 1, med 4 angivna). Ange alltså
  inte fler talare än som pratar, och välj hellre "Vet inte" om du är osäker.

I AMI-proven kommer ordtiderna från korpusens utskrifter, inte från whisper. AMI Meeting Corpus
(CC-BY-4.0) användes bara för utvärderingen och finns inte i repot.

Korta inpass på under en sekund är svårast, och personer som sitter långt från mikrofonen låter
mer lika varandra.

## Se hur det gick, utan att visa texten

Två verktyg skriver bara ut siffror och tider, inga ord ur mötet och inga namn. Utskriften går
alltså att visa för någon annan.

```bash
bash halsokoll/sammanfatta.sh
```

Senaste färdiga inspelningen: tid per timme möte, antal repliker och andel tal per talare,
tystnader utan text (tappade stycken), ställen där whisper har fastnat i en slinga, och
fördelningen per talare i block om 5 eller 10 minuter. Ange ett id för en annan inspelning.

```bash
bash halsokoll/talardiagnos.sh
```

Räknar om röstavtrycken (runt en minut per timme möte) och visar grupperna innan något slås
ihop: hur lika de är, hur många talare det blir med olika `TALARE_TROSKEL`, och när varje grupp
pratar. Ändrar ingenting.

## Vad som är testat

**I en Linux-miljö utan grafikprocessor** (samma Python- och biblioteksversioner):

- **Enhetstester:** 54 st, gröna. De täcker talaruppdelning (även digitala möten), lagring av
  inspelningar i delar, export, skydd mot andra webbsidor och alla API-flöden.
- **`installera.sh` från början:** med en ersättare för launchd, även en ominstallation när
  tjänsten redan finns. Modellnedladdningen med sha256-kontroll gick igenom.
- **`halsokoll/prov.sh`:** grön med båda motorerna.
- **Webbsidan i Chromium**, med en ljudfil som låtsasmikrofon: inspelning, stopp, talaruppdelning,
  namn, rubrik, kopiera, nedladdning, uppladdning, radering och en inspelning där fliken stängdes
  mitt i, som sedan avslutades från listan.
- **Digitalt möte i Chromium:** mikrofonen i vänster kanal och en delad ljudström i höger. Mannen i
  mikrofonen blev **Du** och kvinnan i "mötet" Talare 2. Chromes testläge kan inte dela en riktig
  flik med ljud, så själva flikdelningen ersattes av en ljudström via samma `getDisplayMedia`.

**På en MacBook Air med Apple Silicon:**

- `installera.sh` och `halsokoll/prov.sh` gick gröna med båda motorerna, och senare även med provet
  för digitala möten.
- `whisper-cli` använde Metal. Testljudet på 57 s tog 7,2 s med Metal och 18,3 s på processorn.
- Ett riktigt möte på 1 h 24 min (uppladdat) tog 12 minuter, varav 1,5 minuter talaruppdelning.
  Whisper fastnade inte och tappade inga stycken.
- Ett riktigt samtal inspelat i Chrome och ett röstmemo uppladdat i Safari delades upp i två talare.
- DTW kostade lite: för ett samtal på 48 s gick transkriberingen från 5,9 till 7,1 s.

**Inte provat än:**

- ett riktigt Google Meet-möte eller en Slack-huddle, där Chromes flikväljare och
  "Dela även flikljud" används på riktigt;
- inspelning via webbsidan i Safari (Safari spelar in i ett annat format än Chrome);
- fler långa möten på svenska, och möten där flera pratar i mun på varandra (bara provat i
  AMI-mötena, på engelska).
