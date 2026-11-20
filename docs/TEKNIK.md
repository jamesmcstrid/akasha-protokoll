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
       4. varje ord får gruppen som fönstren runt ordet liknar mest
       5. talaren byter inte mitt i en mening (korta avvikelser rättas) → repliker
       6. sparar .json och .md                                   app/lagring.py, app/export.py
```

| Mapp | Innehåll |
|---|---|
| `app/` | Tjänsten (`app.py`), motorerna (`motor.py`), modellerna och hämtningen (`modeller.py`), talaruppdelningen (`talare.py`), det som skiljer mellan operativsystemen (`plattform.py`), starten som är gemensam för alla system (`start.py`), Dock-ikonen och menyn på Mac (`mac_app.py`), avkodning med PyAV (`ljud.py`), lagring, export och webbsidan i `static/` |
| `paketering/` | PyInstaller-spec, kontrollskript och byggskript för programmet. `prova-linux.sh` bygger samma Python-delar på Linux och kör kontrollen. |
| `mac/` | `installera.sh`, `hamta-modeller.sh`, `kor.sh`, `avinstallera.sh` och launchd-mallen. Skripten som hämtar modeller anropar `app/modeller.py` |
| `halsokoll/` | `prov.sh`: provet efter installation. `sammanfatta.sh` och `talardiagnos.sh`: hur en transkribering gick, utan att visa texten (se nedan) |
| `tester/` | Enhetstester. De behöver inga modeller. Här finns också `falsk_hf.py` (en låtsaskälla som spelar Hugging Face), `forsta_start.py` (startar sidan som vid första start, med låtsaskällan) och `test_riktig_hamtning.py` (hämtar röstmodellen på riktigt, bara för hand) |
| `.github/workflows/` | Testerna i GitHub Actions |
| `testljud/` | Tre testljud ur FLEURS, se [KALLOR.md](../testljud/KALLOR.md) |
| `docs/` | Den här filen och bilderna till README |

Köra enhetstesterna:

```bash
venv/bin/python -m unittest discover -s tester
```

## Webbsidan och API:t

Webbsidan är en enda sida utan ramverk: `app/static/index.html`, `app.js` och `stil.css`. Den
pratar med tjänsten via JSON. Allt som ändrar något är `POST` och kräver headern `X-Akasha-Meet: 1`.

| Anrop | Vad |
|---|---|
| `POST /api/inspelningar` | Ny inspelning: filändelse, rubrik, antal talare, ord och källa. Svarar med id |
| `POST /api/inspelningar/<id>/del?nr=N` | En del av ljudet, var femte sekund under inspelningen |
| `POST /api/inspelningar/<id>/klar` | Inspelningen är slut. Tar emot `talare`, `ord` och `titel`, som läses vid stopp så att de kan ändras under mötet. En tom `titel` behåller rubriken från starten. Utan `talare` gäller inställningarna från starten ("Avsluta och transkribera") |
| `POST /api/inspelningar/fil` | Uppladdad fil (multipart) |
| `POST /api/inspelningar/<id>/transkribera` | "Transkribera igen" (och "Försök igen"): `talare` och `ord` från dialogen. Källan behålls alltid, eftersom kanalerna i filen inte ändras |
| `GET /api/inspelningar`, `GET /api/inspelningar/<id>` | Listan, och en inspelning med text |
| `GET /api/modeller` | Vilka modeller som saknas (med storlek, källa och licens), hur mycket som redan är hämtat, ledigt utrymme, och hur hämtningen går. `hinder` är satt när något saknas som en hämtning inte kan rätta |
| `POST /api/modeller/hamta` | Startar hämtningen av det som saknas, i en bakgrundstråd. Kroppen läses inte. En hämtning som redan pågår startas inte om. `POST /api/modeller/avbryt` stoppar den; det som hämtats ligger kvar |
| `POST …/titel`, `…/namn`, `…/talare`, `…/talare/angra`, `…/radera` | Byt rubrik, spara talarnamn, rätta talare, ångra alla rättningar, radera |
| `GET …/text.md`, `…/text.txt`, `…/ljud` | Nedladdningar. `?ladda_ner=1` på ljudet ger en fil att spara |

När tjänsten inte svarar visar sidan "Akasha Meet svarar inte…" där felet hör hemma, etiketten blir "Tjänsten svarar inte", och sidan frågar var femte sekund tills tjänsten svarar igen.

Medan ett jobb pågår har inspelningen fältet `framsteg`: `fas` (`koar`, `transkriberar` eller
`talare`), `andel` (0–1) och `sekunder`, hur länge den här fasen har pågått. Sidan räknar ut
ungefär hur lång tid som är kvar av transkriberingen ur `andel` och `sekunder`, och visar
ingenting förrän minst 5 % är klart och 15 s har gått. Framsteget finns bara i minnet.

Sidan i korthet:

- **Ny transkribering:** antal talare, svårstavade ord och rubrik läses när man trycker Stoppa.
  Källan (mikrofon eller digitalt) gäller bara inspelning, och "Digitalt" är avstängt i
  webbläsare som inte kan dela flikljud (allt utom Chrome och andra Chromium-webbläsare). Under inspelningen visar en
  nivåmätare ljudet, och en varning visas om nivån har legat under −80 dBFS i tio sekunder.
  Flikens titel visar ● och tiden.
- **Ljud som väntar:** Under inspelningen behåller sidan alla delar i minnet (cirka 27 MB per timme med mikrofonen och 40 MB digitalt, uppmätt med låtsasmikrofon) och skickar dem i ordning. Svarar inte tjänsten försöker sidan igen utan slut, och efter Stoppa startar transkriberingen när allt har kommit fram. Vid ett serverfel slutar sidan skicka och erbjuder "Spara ljudet som fil". Inspelningen släpps först när allt är sparat eller filen är sparad.
- **Listan:** byggs om varannan sekund medan något pågår. "Transkribera igen" öppnar en dialog
  som fylls i från inspelningens egna inställningar, inte från formuläret högst upp.
- **Visningen** i tre steg: 1 Vem är vem? (namnen sparas när fältet lämnas eller med Enter;
  "Lyssna" spelar upp till 10 s av talarens längsta säkra replik), 2 Kontrollera mot ljudet
  (förklaring av markeringarna, en rad med ljudspelaren som följer med vid bläddring, och texten)
  och 3 Använd texten. Ett klick på ett osäkert ord spelar från 2 s före ordets uppskattade tid.
- **Kvitton och fel** från listan och visningen visas i en ruta nederst i fönstret. Kvitton
  försvinner efter 6 s, fel ligger kvar tills man stänger dem.

## Modellerna och hämtningen

Modellerna är för stora för att följa med i repot (1,6 GB med standardvalet), så de hämtas från
Hugging Face första gången. Det är den enda användningen av internet. Allt om dem står i
`app/modeller.py`, och bara där: repo, revision, filnamn, katalog, storlek och sha256 för varje
fil. Skripten i `mac/` har ingen egen kopia utan anropar `python app/modeller.py`, och webbsidan
använder samma modul genom API:t ovan.

- **"Finns" betyder rätt storlek.** Det kostar inget och kontrolleras vid varje anrop till
  `/health` och `/api/modeller`. sha256 räknas när en fil har hämtats, inte vid varje start
  (1,5 GB tar flera sekunder).
- **Halva filer** heter `<namn>.delvis` bredvid målet och har aldrig målets namn. När sha256
  stämmer döps filen om med `os.replace`, som är atomiskt på alla tre systemen. Stämmer den inte
  tas `.delvis` bort. En avbruten hämtning fortsätter med `Range: bytes=N-`. Svarar servern 200 i
  stället för 206 börjar filen om från början.
- **Omdirigeringar följs för hand**, högst fem, och bara till `huggingface.co`, `*.huggingface.co`
  och `*.hf.co`, över https. Varje adress kontrolleras innan den begärs. Startadressen byggs alltid
  av manifestet, och varje försök börjar om därifrån, eftersom adresserna till CDN:et är signerade
  och går ut.
- **Egna omförsök:** avbrott, tidsgräns och nätfel ger två nya försök (efter 2 och 5 s) innan
  felet visas. Ett försök som har hunnit hämta minst 1 MiB räknas inte, men en fil får högst
  20 försök.
- **Proxy och certifikat:** `requests` följer `HTTPS_PROXY`, `NO_PROXY`, `REQUESTS_CA_BUNDLE` och
  `CURL_CA_BUNDLE`. Det läser inte `SSL_CERT_FILE`, så `ny_session()` använder den om ingen av de
  andra är satt. Är ingen av de tre satt använder `ny_session()` operativsystemets egna certifikat
  via `truststore` (`truststore.SSLContext`), så ett företagsnät med egen rot-CA i nyckelringen
  fungerar utan inställningar. Saknas `truststore` blir det som förut. `.env` läses av `mac/kor.sh`,
  så proxyn kan stå där, och i programmet står den i `installningar.env` (se nedan).
- **`HF_HUB_OFFLINE=1`** sätts överst i `motor.py`, så att faster-whisper aldrig hämtar något
  själv.
- **Motorn väljs om efter hämtningen.** `motor.mal_motor()` säger vilken motor modellerna ska
  hämtas för: på en Mac med `whisper-cli` är det whisper.cpp även när GGML-filen saknas.
  `motor.uppdatera()` räknar om den aktiva motorn efter en lyckad hämtning och vid anrop till
  `/health` och `/api/modeller`. Den väntar aldrig på transkriberingslåset, så tjänsten blir redo
  utan omstart, även om modellerna hämtades med skriptet i en terminal.
- **Vad som erbjuds:** taligenkänningen bara om den aktiva motorn inte är redo, och röstmodellen om
  den saknas. Den som redan kör faster-whisper på en Mac får alltså ingen uppmaning att hämta
  GGML-modellen. Sådant som en hämtning inte kan rätta, till exempel `whisper-cli` som saknas med
  `MOTOR=whispercpp` eller en okänd `MODELL`, visas som "Inte redo".
- **Testkällan:** `tester/falsk_hf.py` är en transport för `requests` som spelar Hugging Face:
  omdirigering till en CDN-värd, `Range`, avbrott mitt i en fil, fel innehåll, serverfel och
  nätfel. Testerna och `forsta_start.py` byter bara ut sessionen (`modeller.ny_session`), så all
  riktig kod körs oförändrad: adresserna, omdirigeringarna, kravet på https och sha256. Det finns
  ingen flagga, miljövariabel eller undantag för http i `app/`. Transporten stoppar alla andra
  värdar än de falska, så inget test når nätet.

## Programmet (Mac)

Programmet är ett vanligt Mac-program, `Akasha Meet.app`, för Apple Silicon (macOS 14 eller senare).
Det ersätter inte terminalinstallationen: båda finns kvar och använder samma kod i `app/`. Den här
delen beskriver hur programmet är tänkt att fungera. Det är ännu inte byggt eller provat på en Mac
(se "Inte provat än" längst ned).

- **Hur det byggs.** PyInstaller 6.22.3 i katalogläge samlar Python, beroendena och deras inbyggda
  bibliotek till ett `.app`-paket. En spec-fil, `paketering/akasha-meet.spec`, bygger både Mac-programmet
  och provbygget på Linux (en vanlig katalog). `whisper-cli` ska byggas från källkod i GitHub Actions
  från en fast tagg av whisper.cpp, statiskt och med Metal, och läggas in i paketet så att den
  signeras med resten. Artefakten är en zip-fil som packas med `ditto`, för att behålla
  behörigheter och signatur. Bygget är ad hoc-signerat, inte signerat med ett Apple Developer ID. Flödet i
  Actions (`.github/workflows/mac-app.yml`, körs bara för hand) finns inte i repot än.
- **Vad som följer med.** Flask, waitress, requests, sherpa-onnx, numpy, PyAV (`av`), `truststore`
  och `whisper-cli`, samt PyObjC för Dock-ikonen och menyn. faster-whisper, ctranslate2,
  tokenizers, huggingface_hub och onnxruntime följer inte med, eftersom programmet använder
  whisper.cpp. Därför avkodas ljudet med `app/ljud.py` (PyAV) i stället för med faster-whisper.
  Sätts `MOTOR=faster` i programmet visar sidan "Inte redo" med en förklaring.
- **Start och avslut.** `mac_app.py` är det tunna Mac-skalet: ikon i Dock, programmenyn och
  Dock-menyn. Allt annat ligger i `start.py`, som går att köra och testa på Linux: loggning, kontroll
  av inställningsfilen, om porten är ledig, tjänsten i en bakgrundstråd, att öppna webbläsaren och att
  stänga ned. Vid start frågar `start.lage()` om porten är ledig, upptagen av en annan Akasha Meet
  eller upptagen av något annat. En annan Akasha Meet gör att programmet bara öppnar sidan och
  avslutas, och något annat ger ett felmeddelande. Dubbelklick på ett program som redan är igång
  hanteras av macOS, som skickar "öppna igen" till det som körs. Vid ⌘Q frågar programmet först om
  det pågår en inspelning, en transkribering eller en hämtning (`start.pagar()`), och stänger sedan
  servern och `whisper-cli`. En transkribering som avbryts på det sättet blir `avbruten` och kan
  göras om med "Försök igen".
- **Den gamla installationen.** Finns launchd-tjänsten `local.akasha-meet` frågar programmet om det
  ska ta över. Svarar man ja stängs tjänsten av med `launchctl disable` och `launchctl bootout`, så
  att den inte startar vid nästa inloggning, och programmet väntar tills porten är ledig. Två
  tjänster får aldrig dela datakatalog, eftersom `lagring.aterstall_avbrutna()` vid start annars
  skulle märka den andras pågående jobb som avbrutna. `mac/installera.sh` stannar åt andra hållet
  med en förklaring om programmet är igång på porten och launchd-tjänsten inte finns.
- **Var saker ligger.** Inspelningar: `~/AkashaMeet`, som i terminalinstallationen. Modeller:
  `~/Library/Application Support/Akasha Meet/modeller`. Inställningar:
  `~/Library/Application Support/Akasha Meet/installningar.env`, med samma `NAMN=värde` som `.env`.
  Den läses bara när programmet är paketerat, och en miljövariabel som redan är satt vinner.
  Programmet stannar aldrig på grund av filen: det som inte går att läsa ersätts med
  standardvärdet, och rutan vid start, loggen och (utan fönster) stderr säger till. Problemtexterna
  innehåller bara radnummer och inställningens namn, aldrig något ur filen. Loggen ligger i
  `~/Library/Logs/Akasha Meet/akasha-meet.log` (roterande, 2 MB, tre filer). Har någon modeller i
  repots `modeller/` från terminalinstallationen hårdlänkas de in i programmets katalog vid start,
  så att inget hämtas igen och terminalinstallationen fungerar som förut. Går länken inte (annan
  volym) erbjuder sidan hämtning som vid första start.
- **Det enda som skiljer.** Om koden körs som programmet avgörs av `sys.frozen`, PyInstallers eget
  märke, och bara i `app/plattform.py`. Det finns ingen testflagga eller testmiljövariabel i `app/`.
- **Kontrollen i Actions.** Det byggda programmet ska startas med en tom hemkatalog (`HOME`). En
  gles fil med GGML-modellens storlek läggs i `~/akasha-meet/modeller`, så att flytten av gamla
  modeller och motorvalet provas utan att 1,5 GB hämtas. Röstmodellen (40 MB) hämtas på riktigt
  genom programmets eget API. Ett testljud laddas upp, avkodningen ska lyckas och jobbet ska
  misslyckas med ett fel från den medföljande `whisper-cli` (den gles filen är ingen modell). Sist
  skickas SIGTERM och porten ska vara ledig. Dessutom ska den medföljande `whisper-cli`
  transkribera ett testljud med en liten riktig modell. Samma kontrollskript
  (`paketering/kontrollera.py`) körs mot provbygget på Linux. Kontrollen visar att programmet
  startar, att standardplatserna, flytten av modeller, motorvalet, sherpa-onnx, PyAV, requests och
  certifikaten fungerar i det frysta programmet, att hämtningen från Hugging Face fungerar, och att
  loggen och avslutet fungerar. Den visar inte att Metal används, att Gatekeeper släpper igenom
  programmet efter godkännandet i Systeminställningar, eller att en riktig KB-Whisper-modell
  transkriberar. Det kräver en riktig Mac.

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
5. Talaren byter sällan mitt i en mening. Inom en mening (som slutar vid punkt, frågetecken,
   utropstecken eller en paus på 0,4 s) får korta avvikande sjok, högst 4 ord i rad, samma talare
   som resten av meningen, om en talare har mer än hälften av meningens ord. Egna meningar som
   "Ja, ja." och längre avvikelser rörs inte. Det behövs eftersom ordtiderna är ungefärliga:
   whisper.cpp:s ordtider låg i ett riktigt möte i snitt 0,17 s före faster-whispers och ibland en
   sekund fel. Svagheten: om whisper inte sätter något skiljetecken vid ett talarbyte kan ett kort
   svar som "Nej, precis." hamna hos den andra.

**Rättningar för hand** (`app/rattning.py`): på webbsidan kan en hel replik, några markerade ord
eller alla repliker från en talare få en annan talare. Repliker i följd med samma talare slås ihop.
Ordtiderna sparas inte, så när en replik delas uppskattas tiden utifrån andelen text före
delningen. Maskinens version sparas som `segment_original` i inspelningens `.json` vid första
rättningen, så att allt kan ångras. "Transkribera igen" ersätter båda, så dialogen varnar först.

**Osäkra ställen** markeras på webbsidan, som en hjälp att veta var man ska börja kontrollera:

- **Osäker talare** (`osaker_talare` på en replik): minst hälften av replikens ord är osäkra. Ett
  ord är osäkert om rösten liknar två grupper nästan lika mycket (`MARGINAL`, skillnad under
  0,03), om meningsregeln flyttade ordet, eller i digitala möten om kanalen inte avgjorde. I
  AMI-mötena hade ord med marginal under 0,05 fel talare i 44 % av fallen, mot 16 % i snitt och
  2,6 % när marginalen var stor. På replikernivå är signalen svagare: 12 % av replikerna
  markerades, och 31 % av dem var fel, mot 24 % av alla repliker. I det konstgjorda digitala mötet
  med täta "mm" markerades ungefär hälften av de felaktiga replikerna. Fel kan alltså finnas även
  där det inte är markerat.
- **Osäkra ord** (`osakra_ord`, index i texten): whispers sannolikhet för ordet är låg. whisper.cpp
  ger den per token, och ordet får den lägsta. På 40 FLEURS-meningar med facit var whisper.cpp:s
  ord under 0,5 fel i 20 % av fallen, mot 4–5 % för övriga. Det är ungefär 7 % av orden, ofta namn
  och ovanliga ord. faster-whispers sannolikheter skilde sämre, så där gäller 0,4: knappt 1 % av
  orden, och en tredjedel av dem var fel.

När en talare bestäms för hand försvinner markeringen för osäker talare. Knappen "… stämmer" gör
detsamma utan att byta talare.

**Digitala möten:** mikrofonen och mötesfliken ligger i varsin kanal. Ett ord hör till den kanal
som är starkast under ordet, om den är minst fyra gånger så stark; annars får ordet samma som
närmaste säkra ord. Det du säger blir alltid Talare 1 ("Du"). Bara de andra (höger kanal) delas upp
efter röst, enligt stegen ovan.

Först räckte dubbelt så stark. I ett riktigt digitalt möte (18 minuter, tre personer) blev då
en tredjedel av replikerna bara 1–3 ord: när någon i mötet skrattade eller sa "mm" medan du
pratade hamnade enstaka ord mitt i dina meningar hos de andra. Med fyra gånger så stark blev det
65 repliker i stället för 99, och 6 korta i stället för 32. Av de 39 ord som bytte talare var
ungefär 35 tydligt rätt utifrån innehållet. Med konstgjorda "mm" och skratt i testljudet, där
facit finns, gick andelen ord med rätt talare från 80–91 % till 89–98 % (medel över åtta
slumpvisa varianter), och rent ljud gav fortfarande 100 %.

Meningsregeln (punkt 5 ovan) gjorde mest skillnad med whisper.cpp, som din Mac använder. I samma
möte med whisper.cpp:s ordtider: 141 repliker med 50 korta blev 70 med 6, med tre talare. I ett
urval av de ändrade orden var ungefär 22 av 24 rätt. Med konstgjorda "mm" och skratt blev 97–99,6 %
av orden rätt talare. I rummet gav regeln samma resultat för testdialogerna (100 %) och något
bättre för AMI-mötena (75,3 → 76,0 %, 83,6 → 85,1 % och 89,0 → 90,8 %).

Först fick bara sjok på högst 3 ord meningens talare. Omkört på Macen gav det 86 repliker i stället
för 144, men tre sjok på 4 ord låg kvar hos fel person ("Att man lägger upp", "Så därför tycker
jag", "Då vet jag inte"). Med högst 4 ord hamnade de rätt, och AMI-mötena, testdialogerna och
testljudet med konstgjorda ljud blev lika bra eller något bättre.

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
  Omkört med den nya sammanslagningen blev det fyra talare. Personen fick 20 % av taltiden, med
  samma tidsmönster som i diagnosen, och mötesledarens andel sjönk från 74 till 53 %. Den femte
  personen gick fortfarande inte att skilja ut.
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

## Medium eller large

`MODELL=large` ger KB-Whisper large, KBLab:s största modell. För whisper.cpp används KBLab:s
kvantiserade version (q5_0, 1,1 GB). Enligt KBLab gör large cirka 15–25 % färre fel än medium.
Provat i Linux-miljön, med whisper.cpp på processorn och samma inställningar som när talare delas
upp:

- **40 meningar ur FLEURS** (svenska, uppläst, 715 ord): 6,4 % fel ord med medium och 5,5 % med
  large. Large var bättre i 9 meningar och sämre i 8, så provet är för litet för att säga mer än
  att large verkar något bättre.
- **Testljudet med två talare:** båda gav rätt talare, och båda tappade ett par ord, på olika
  ställen.
- **Tid:** för en minut ljud tog large ungefär lika lång tid som medium. För 40 korta klipp tog
  large 2,4 gånger så lång tid, men då laddas modellen om för varje klipp. Med Metal på Mac är det
  inte uppmätt än.

Det som avgör är ett riktigt möte: transkribera samma ljud med båda och jämför med
`halsokoll/jamfor.sh` (nedan).

## Se hur det gick, utan att visa texten

Tre verktyg skriver bara ut siffror och tider, inga ord ur mötet och inga namn. Utskriften går
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

```bash
bash halsokoll/jamfor.sh <id A> <id B>
```

Jämför två transkriberingar av samma möte: samma ljud med olika modeller, eller samma möte
inspelat med två enheter (datorn och en telefon). Visar hur stor andel av orden som skiljer, totalt
och per tiominutersblock, om talarna stämmer överens och hur mycket inspelningarna är förskjutna i
tid. Skillnaderna med text sparas i `jamforelser/` i inspelningsmappen. Att två transkriberingar
stämmer överens betyder inte att de är rätt, eftersom samma modell gör samma fel på namn och
facktermer. Men där de skiljer sig har minst en av dem hört fel.

## Vad som är testat

**I en Linux-miljö utan grafikprocessor** (samma Python- och biblioteksversioner):

- **Enhetstester:** 143 st, gröna, och ett till som bara körs för hand (se nedan). De täcker
  talaruppdelning (även digitala möten), lagring av inspelningar i delar, export, skydd mot andra
  webbsidor, alla API-flöden och modellhämtningen mot låtsaskällan.
- **Första start i Chromium**, med låtsaskällan i stället för Hugging Face: kortet med modellerna,
  hämtning, stopp och fortsättning, en sida som laddas om mitt i hämtningen, och alla felfall
  (avbrott, fel kontrollsumma, inget nät och full disk) med "Försök igen". Både i ljust och mörkt
  läge, utan fel i konsolen.
- **Riktig hämtning av röstmodellen** (40 MB) från Hugging Face: avbruten efter några MB och
  fortsatt med `Range`, med omdirigering till en CDN-värd och rätt sha256. Körs för hand med
  `AKASHA_RIKTIG_HAMTNING=1 venv/bin/python -m unittest discover -s tester -p test_riktig_hamtning.py`.
  Taligenkänningen (1,5 GB) har aldrig hämtats på riktigt i provet.
- **GitHub Actions** (2026-11-19): enhetstesterna, 144 st (1 överhoppat: den riktiga hämtningen), gröna på ubuntu-latest (Ubuntu 26.04, Python 3.12.16) och windows-latest (Python 3.12.10) vid push till main, och på macos-latest (arm64, Python 3.12.10) körd för hand. Ubuntu-jobbet tog 17 s, Windows-jobbet 43 s och macOS-jobbet 20 s. faster-whisper installeras inte där (testerna behöver den inte).
- **Programmet:** provbygge på Linux med kontrollskriptet (start, standardplatser, flytt av gamla modeller, riktig hämtning av röstmodellen, avkodning, avslut).
- **`installera.sh` från början:** med en ersättare för launchd, även en ominstallation när
  tjänsten redan finns. Modellnedladdningen med sha256-kontroll gick igenom.
- **`halsokoll/prov.sh`:** grön med båda motorerna.
- **Webbsidan i Chromium**, med en ljudfil som låtsasmikrofon: inspelning, stopp, talaruppdelning,
  namn, rubrik, kopiera, nedladdning, uppladdning, radering och en inspelning där fliken stängdes
  mitt i, som sedan avslutades från listan.
- **Den omgjorda webbsidan i Chromium**, med påhittade inspelningar i alla lägen och en riktig
  transkribering: rubrik som skrivs under inspelningen, varningen om inget ljud (med en tyst
  ljudström), dialogen "Transkribera igen", förloppet med tid kvar, namn som sparas av sig själva,
  "Lyssna", klick på osäkra ord, rättning av talare med mus och tangentbord, kvittorutan och
  kontrasten i ljust och mörkt läge (uppmätt i webbläsaren). Inte provat: Safari, skärmläsare
  och tröskeln för varningen om inget ljud med en riktig mikrofon.
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

- programmet byggt för Mac (GitHub Actions) och på en riktig Mac: Gatekeeper, Dock, Metal och transkribering;
- faster-whisper och transkribering på Windows (CI installerar inte faster-whisper);
- första start på en riktig Mac och på Windows, och hämtning på ett företagsnät med proxy;
- ett riktigt Google Meet-möte eller en Slack-huddle, där Chromes flikväljare och
  "Dela även flikljud" används på riktigt;
- inspelning med avbrott och räddningsfil i Safari och Edge (provat i Chromium);
- inspelning via webbsidan i Safari (Safari spelar in i ett annat format än Chrome);
- fler långa möten på svenska, och möten där flera pratar i mun på varandra (bara provat i
  AMI-mötena, på engelska).
