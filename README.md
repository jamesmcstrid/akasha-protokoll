# <img src="app/static/elefant.svg" alt="" width="44" align="top"> Akasha Protokoll

Transkribera möten lokalt på din egen dator. Spela in direkt i webbläsaren, eller ladda upp en ljudfil.
Du får texten uppdelad per talare och kan byta "Talare 1" och "Talare 2" mot riktiga namn.

- **Allt stannar på datorn.** Tal till text och talaruppdelning görs lokalt. Inget skickas till
  någon molntjänst. Internet används bara en gång, för att hämta modellerna.
- **Svensk taligenkänning** med [KB-Whisper](https://huggingface.co/KBLab/kb-whisper-medium) från
  Kungliga biblioteket. På Mac med Apple Silicon används grafikprocessorn (Metal). Windows-programmet
  använder processorn.
- **Möten i rummet och digitalt.** Med datorns mikrofon, eller Google Meet och Slack i Chrome.
- **Inspelningen tappas inte.** Ljudet sparas på disken var femte sekund under mötet. Svarar inte Akasha Protokoll en stund sparas ljudet i webbläsarfliken under tiden.

Akasha Protokoll är ett program som du öppnar som vilket annat som helst. Själva sidan visas i webbläsaren.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/bilder/akasha-protokoll-mork.png">
  <img src="docs/bilder/akasha-protokoll-ljus.png" alt="Akasha Protokoll i webbläsaren. Överst ett grönt fält med rubriken Mötet blir text. Inget lämnar datorn. och en elefant. Till vänster knappen Ny transkribering och listan med inspelningar, där en transkriberas just nu. Till höger ett transkriberat möte i tre steg: 1 Vem är vem? med namnen Anna och Jonas, 2 Kontrollera mot ljudet med en förklaring av markeringarna, ljudspelaren och replikerna, där en replik är markerad som osäker talare och två ord är understrukna som osäkra, och 3 Använd texten med knappar för att kopiera och ladda ner." width="760">
</picture>

<sub>Exemplet är påhittat.</sub>

## Använda

1. Öppna **Akasha Protokoll** i Program. Webbläsaren öppnas på sidan av sig själv. Har du installerat från
   Terminal går du i stället till **http://127.0.0.1:8611** i Chrome (eller Safari). Spara gärna
   sidan som bokmärke. På Windows startar du **Akasha Protokoll** från Start-menyn (se
   [Som program (prov, Windows)](#som-program-prov-windows)). Webbläsaren öppnas på sidan när programmet
   har startat.
2. Välj **Hur spelas mötet in?** och **Hur många pratar?**. Skriv gärna namn och facktermer som
   sägs i mötet under **Svårstavade ord**, så stavas de rätt.
3. Tryck **Spela in**. När mötet är slut trycker du **Stoppa och transkribera**. Du kan också
   trycka **Ladda upp ljudfil…** och välja en fil, till exempel från Röstmemon.
4. Vänta medan texten tas fram. Sidan visar hur långt det har kommit och ungefär hur lång tid
   som är kvar.
5. **Vem är vem?** Skriv in vad talarna heter. Namnen sparas av sig själva. Tryck **Lyssna** för
   att höra ett prov på rösten, om du inte vet vem som är vem.
6. **Kontrollera mot ljudet.** Klicka på en tid för att lyssna på just det stället. Ljudspelaren,
   **Backa 5 s** och **Nästa osäkra talare** följer med när du bläddrar i texten.
7. Har en replik fått fel talare? Klicka på namnet i repliken och välj rätt person. Är bara en del
   fel, markera de orden och välj vem som sa dem. Där kan du också säga att alla repliker från en
   talare egentligen är någon annans. **Ångra alla rättningar** tar texten tillbaka till hur den
   var efter transkriberingen.
8. Börja kontrollen med de osäkra ställena. Ovanför texten står vad markeringarna betyder.
   Repliker där talaren är osäker har ett **?** och streckad kant, och **Nästa osäkra talare**
   hoppar mellan dem. Stämmer talaren, klicka på **?** eller namnet och välj **… stämmer**, så
   försvinner markeringen. Ord som programmet var osäkert på är understrukna, ofta namn och
   ovanliga ord. Klicka på ett sådant ord för att lyssna. Markeringarna är en hjälp att veta var
   du ska börja, inte en garanti: fel kan finnas även där det inte är markerat.
9. **Använd texten.** Tryck **Kopiera texten**, eller **Ladda ner som text (.txt)** eller
   **Ladda ner som Markdown (.md)**. **Ladda ner ljudet** sparar ljudet som en fil.

Inspelningen heter "Möte" och datum om du inte skriver en rubrik. Du kan skriva rubriken medan
mötet pågår: det som står i fältet när du trycker **Stoppa och transkribera** gäller. Rubriken går
att byta efteråt med **Byt rubrik**. Filnamnet på en uppladdad fil används aldrig, eftersom
Röstmemon döper inspelningar efter platsen (en gatuadress).

Vill du transkribera en inspelning en gång till, till exempel med ett annat antal talare? Tryck
**Transkribera igen** i listan, ändra det som behövs och tryck **Transkribera**. Har du rättat
talarna för hand försvinner de rättningarna, och sidan säger till först.

### Med mikrofonen

För möten i samma rum, eller digitala möten där du har högtalare på. Mikrofonen fångar alla som
hörs i rummet.

- Ställ datorn mellan er. Mikrofonen behöver höra alla ungefär lika bra.
- Är du med i ett digitalt möte via högtalare blir de andras röster något sämre än i det digitala
  läget nedan.

### Digitalt i Chrome (Google Meet, Slack)

När du trycker **Spela in** frågar Chrome vilken flik som ska delas: välj fliken med mötet och
kryssa i **Dela även flikljud**. Det fungerar med hörlurar, och med alla möten i en Chrome-flik:
Google Meet, en Slack-huddle i Slack i Chrome (`app.slack.com`), Teams eller Zoom i webbläsaren.

- Din mikrofon och mötet spelas in i varsin kanal. Det du säger blir därför alltid **Du**, och bara
  de andra behöver delas upp efter röst.
- Räkna med dig själv i "Hur många pratar?". Tre betyder du och två till.
- Det fungerar bara i Chrome och andra Chromium-webbläsare. Safari och Firefox kan inte dela
  ljudet från en flik, så där går valet inte att välja.
- Möten i **apparna** (Slack-appen, Teams, Zoom) har ingen flik att dela. Öppna mötet i Chrome,
  eller använd högtalare och **Med mikrofonen**. En Mac-hjälpare som hämtar ljudet direkt från
  apparna finns som förslag i [#1](https://github.com/jamesmcstrid/akasha-protokoll/issues/1).

### Bra att veta

- **Be alltid om lov innan du spelar in någon.** I ett digitalt möte ser de andra inte att du
  spelar in, som de gör när Meet själv spelar in. Säg till.
- Låt fliken vara öppen och datorn vaken. Om locket stängs slutar inspelningen.
- Under inspelningen visar **Ljudnivå** att ljud kommer in, och flikens namn visar att du spelar
  in. Hörs inget ljud på ungefär tio sekunder varnar sidan. Kontrollera då att rätt mikrofon är
  vald och att den inte är avstängd.
- Medan texten tas fram somnar datorn inte av sig själv. Stänger du locket pausas
  transkriberingen och fortsätter när du öppnar det igen.
- Svarar inte Akasha Protokoll under en inspelning fortsätter inspelningen, och ljudet sparas i fliken tills Akasha Protokoll är igång igen. Stäng inte fliken då. Trycker du Stoppa medan ljud väntar, startar transkriberingen när allt har kommit fram. Vill du inte vänta, tryck Spara ljudet som fil och sedan Klar, och ladda upp filen senare med Ladda upp ljudfil.
- Om fliken stängs eller datorn startas om ligger inspelningen kvar i listan som "Spelar in".
  Tryck **Avsluta och transkribera**, så transkriberas det som hann sparas.
- Kontrollera texten mot ljudet innan du använder den. Taligenkänning gör fel, särskilt på namn,
  siffror och när flera pratar samtidigt.

### Hur lång tid tar det?

På en MacBook Air med Apple Silicon tog ett möte på 1 timme och 24 minuter 12 minuter att
transkribera och dela upp per talare, alltså drygt 8 minuter per timme möte. Medan texten tas
fram visar sidan ungefär hur lång tid som är kvar.

På Windows används processorn, och det tar längre tid. På en Dell med Intel Core (12:e generationen)
tog transkriberingen ungefär 1,3–1,6 gånger så lång tid som ljudet: ett möte på en timme tar alltså
runt 80–95 minuter. Med laddaren i och energiläget **Bästa prestanda** går det fortare.

## Installera

### Som program (prov, Mac med Apple Silicon)

Programmet byggs i GitHub Actions och är ännu inte signerat av Apple. Det kräver en Mac med Apple
Silicon (M1 eller senare) och macOS 14 eller senare.

1. Öppna repot på GitHub (du måste vara inloggad), gå till **Actions → Mac-app**, välj den senaste gröna
   körningen och ladda ned **Akasha-Protokoll-mac-arm64.zip** under **Artifacts**. Filen sparas bara i sju
   dagar i Actions. Är den borta behövs en ny körning.
2. Öppna zip-filen i Hämtade filer om Safari inte redan har gjort det, och dra **Akasha Protokoll** till
   **Program**.
3. Dubbelklicka på Akasha Protokoll. Första gången säger macOS att "Akasha Protokoll" öppnades inte, eftersom
   Apple inte kunde verifiera att den är fri från sabotageprogram. Tryck **Klar**. (Den förvalda
   knappen är Flytta till papperskorgen; tryck inte på den.)
4. Välj Apple-menyn > Systeminställningar och klicka på **Integritet och säkerhet** i sidofältet (du
   kanske måste rulla nedåt). Under rubriken **Säkerhet** står "Akasha Protokoll" blockerades för att
   skydda din dator. Tryck **Öppna ändå** på den raden. (På en del versioner av macOS heter knappen
   där **Öppna**; tryck i så fall på den.) Knappen finns i omkring en timme efter att du försökte
   öppna appen. Saknas den, gör om steg 3.
5. En ruta frågar Vill du öppna "Akasha Protokoll"? Tryck **Öppna ändå**.
6. Bekräfta med Touch ID, eller tryck **Använd lösenord…** och ange ditt lösenord. Det behövs bara
   första gången; sedan öppnas Akasha Protokoll med dubbelklick som andra program. Apple beskriver stegen
   i
   [Öppna en Mac-app från en okänd utvecklare](https://support.apple.com/sv-se/guide/mac-help/mh40616/mac).
7. Sidan öppnas och erbjuder att hämta modellerna (cirka 1,6 GB, bara första gången). Har du
   installerat från Terminal tidigare används de modeller du redan har (se nedan).

Säger macOS i stället att programmet är skadat, eller syns ingen rad om Akasha Protokoll under Säkerhet
direkt efter ett försök att öppna det, kör en gång i Terminal:
`xattr -dr com.apple.quarantine "/Applications/Akasha Protokoll.app"` och öppna programmet igen.

**Igång och avsluta:** när Akasha Protokoll är igång har ikonen i Dock en prick under sig. Klicka på
ikonen för att öppna sidan igen. Avsluta med **⌘Q** eller genom att högerklicka på ikonen och välja
**Avsluta**. Det du redan spelat in ligger kvar.

**Har du installerat från Terminal tidigare** frågar programmet om det ska ta över. Då stängs den
gamla installationen av och startar inte längre när du loggar in. Inspelningarna
och modellerna du redan har används av programmet, så ingenting hämtas igen. Vill du ha tillbaka den
gamla kör du `bash mac/installera.sh` igen. Ligger den gamla mappen i Hämtade filer, Dokument eller
Skrivbord letar programmet inte efter modeller där (macOS skulle annars fråga om lov), utan erbjuder
att hämta dem. Flytta mappen till hemkatalogen först om du vill slippa hämta igen.

### Från Akasha Meet till Akasha Protokoll

Programmet hette tidigare Akasha Meet. Det här avsnittet gäller Mac. Har du det installerat:

1. Avsluta Akasha Meet med **⌘Q**.
2. Ladda ned Akasha Protokoll och öppna det enligt stegen ovan. Första gången behövs **Öppna ändå**
   igen, eftersom macOS ser det som ett nytt program.
3. Inspelningarna och modellerna flyttas av sig själva när Akasha Protokoll startar första gången:
   `~/AkashaMeet` blir `~/AkashaProtokoll`, och `~/Library/Application Support/Akasha Meet` (modeller
   och inställningar) blir `~/Library/Application Support/Akasha Protokoll`. Mapparna döps bara om:
   ingenting kopieras eller raderas. Finns den nya mappen redan rörs ingenting, och har du satt en
   egen `DATAKATALOG` flyttas inte inspelningarna. Är Akasha Meet inte avslutat öppnar Akasha
   Protokoll bara sidan i den, och flytten görs nästa gång.
4. När Akasha Protokoll fungerar flyttar du Akasha Meet till Papperskorgen. Öppnas den gamla igen
   hittar den varken inspelningar eller modeller och erbjuder en ny hämtning på cirka 1,6 GB.
5. Mappen `~/Library/Logs/Akasha Meet` med de gamla loggarna kan tas bort. Loggarna flyttas inte.

Har du installerat från Terminal flyttar `bash mac/installera.sh` mapparna på samma sätt när du kör
den igen.

### Som program (prov, Windows)

Windows-programmet är nytt och ännu inte signerat. Det är provat på en vanlig Windows 11-dator (Dell med
Intel Core, 12:e generationen): installation, uppdatering ovanpå en äldre version, hämtning av modellerna,
transkribering, ikonen vid klockan och avslut. Berätta vad du ser om något inte fungerar. Programmet är
byggt för 64-bitars Windows (x64). Andra versioner än Windows 11 är inte provade.

1. Öppna repot på GitHub (du måste vara inloggad), gå till **Actions → Windows-app**, välj den senaste
   gröna körningen och ladda ned **Akasha-Protokoll-installation.exe** under **Artifacts**. Filen sparas
   bara i sju dagar i Actions. Är den borta behövs en ny körning. Under Artifacts ligger också
   `SHA256SUMS.txt` (se Kontrollera nedladdningen nedan) och zip-filen, om du hellre vill slippa
   installera (se längre ned).
2. Dubbelklicka på filen. Första gången brukar Windows varna för program som det inte känner igen,
   särskilt filer som hämtats från internet. Den här varningen beror på att programmet inte är
   signerat. Rutan har en länk för mer information, och efter den en knapp för att köra ändå. Vad rutan
   och knapparna heter på svenska är inte sett än och skrivs hit när installationsfilen har provats på en
   riktig dator. Ser du ingen sådan knapp, se Felsökning nedan.
3. Installationsguiden är på svenska. Programmet installeras bara för ditt konto, utan administratörsrätt,
   i `%LOCALAPPDATA%\Programs\Akasha Protokoll`, och du får inte välja någon annan mapp. Du får läsa
   licensen ("Läs licensen nedan innan du fortsätter. Andra delar av programmet har egna licenser."). Du kan
   kryssa i **Skapa en genväg på skrivbordet** (den är inte ikryssad från början). Genvägen
   **Akasha Protokoll** läggs alltid i Start-menyn. Sist kan du låta kryssrutan **Starta Akasha Protokoll**
   vara ikryssad, så startar programmet när guiden är klar.
4. Ikonen kommer upp vid klockan och sidan öppnas av sig själv, så snart programmet har startat.
   Sidan erbjuder att hämta modellerna (cirka 1,6 GB, bara första gången).

Guiden är provad på en vanlig Windows-dator. Byggmaskinen provar dessutom en tyst installation vid varje
bygge (se docs/TEKNIK.md).

**Uppdatera:** kör den nya installationsfilen. Är Akasha Protokoll igång säger guiden till: "Installationsprogrammet
har upptäckt att Akasha Protokoll är igång. Avsluta det angivna programmet nu. Klicka sedan på OK för att gå vidare
eller på Avbryt för att avsluta." Avsluta programmet (högerklicka på ikonen vid klockan och välj
**Avsluta Akasha Protokoll**) och klicka på OK. Guiden stänger inte programmet själv, eftersom en inspelning kan
pågå. Att uppdatera ovanpå en äldre installation är provat och fungerade.

**Avinstallera:** Inställningar → Appar → Akasha Protokoll (inte provat). Bara programmet och genvägarna tas bort.
Slutrutan säger: "Dina inspelningar ligger kvar i mappen AkashaProtokoll i din hemkatalog, och modellerna i
%LOCALAPPDATA%\Akasha Protokoll. Ta bort dem själv om du inte vill ha dem." Inställningarna ligger i samma mapp
som modellerna och tas inte heller bort.

**Utan installation (zip-filen):** ladda ned **Akasha-Protokoll-windows-x64.zip** i stället. Högerklicka på den och
välj **Extrahera alla…**. Följ rutan som öppnas. Mappen **Akasha Protokoll** som då skapas är programmet: lägg den
där den får ligga kvar, och starta inte programmet inifrån zip-filen. Det behöver filerna i mappen bredvid sig.
Öppna mappen och dubbelklicka på **Akasha Protokoll.exe**. Windows varnar på samma sätt som ovan.

**Kontrollera nedladdningen:** varje körning lägger också en fil, `SHA256SUMS.txt`, bland artefakterna. Den har
en kontrollsumma (SHA-256) för zip-filen och för installationsfilen. Är du osäker på att filen är orörd, jämför
summan. Öppna PowerShell och skriv, om filen ligger i Hämtade filer:

```powershell
Get-FileHash "$HOME\Downloads\Akasha-Protokoll-installation.exe" -Algorithm SHA256
```

Summan som visas ska vara densamma som på raden för filen i `SHA256SUMS.txt`. Stora och små bokstäver spelar
ingen roll. Kontrollsumman visar att filen inte har ändrats på vägen eller blivit skadad, men inte vem som har
byggt den: den kommer från samma körning, så den ersätter ingen signering. Mac-programmet har ingen sådan fil.

**Igång och avsluta på Windows:** när Akasha Protokoll är igång finns en ikon vid klockan, längst ned i
aktivitetsfältet. Syns den inte, klicka på pilen **^** vid klockan: Windows lägger ofta nya ikoner där.
Håll muspekaren över ikonen för att se om programmet startar ("Akasha Protokoll startar…") eller är
igång ("Akasha Protokoll är igång"). Första gången visas också en notis: "Akasha Protokoll är igång. Du hittar
det bland ikonerna vid klockan." Vänsterklicka på ikonen för att öppna sidan igen, eller högerklicka och välj
**Öppna Akasha Protokoll i webbläsaren**. Avsluta genom att högerklicka på ikonen och välja
**Avsluta Akasha Protokoll**. Pågår en inspelning, en transkribering eller en hämtning frågar programmet
först om du vill avsluta ändå. Knapparna i rutan (*Ja*, *Nej*) följer Windows språk, och *Nej* är förvald.
Svarar du *Ja* avbryts en transkribering (du kan göra om den med **Försök igen**), en hämtning fortsätter
där den slutade nästa gång, och en inspelning fortsätter i webbläsaren och sparas i fliken tills du öppnar
Akasha Protokoll igen, så stäng inte fliken. Det du redan spelat in ligger kvar. Dubbelklickar du på
**Akasha Protokoll.exe** igen medan programmet är igång öppnas sidan i det som redan körs, och det startar
ingen annan kopia. Loggar du ut eller stänger av datorn är det avsett att programmet avslutas utan att
fråga, med samma följder som om du svarade *Ja*. Ikonen och **Avsluta Akasha Protokoll** är provade på en
vanlig Windows-dator. Frågan före avslut och vad som händer vid utloggning är inte provade än.

Ingen har haft det gamla namnet Akasha Meet på Windows, så avsnittet nedan om att byta namn gäller bara Mac.

### Från Terminal

Det här avsnittet gäller Mac. För Windows finns än så länge bara programmet ovan.

Kräver: en Mac (helst Apple Silicon), [Homebrew](https://brew.sh) och cirka 4 GB ledigt utrymme.
Öppna Terminal och kör:

```bash
brew install python@3.12 git
git clone https://github.com/jamesmcstrid/akasha-protokoll.git ~/akasha-meet
cd ~/akasha-meet
bash mac/installera.sh
```

Mappen heter `akasha-meet` efter programmets gamla namn, och installationen räknar med det namnet.
Den ska ligga direkt i din hemkatalog, som `~/akasha-meet` ovan, och inte i Hämtade filer,
Dokument, Skrivbord eller iCloud Drive. Där låter macOS inte bakgrundstjänster läsa, och
installationen säger ifrån. Har du laddat ned repot som zip-fil, flytta den uppackade mappen till
hemkatalogen innan du kör installationen.

Installationen skapar en Python-miljö och laddar ner modellerna (cirka 1,6 GB, bara första gången).
På Apple Silicon installerar den också `whisper-cpp` via Homebrew, så att grafikprocessorn används.
Den lägger in tjänsten så att den startar när du loggar in, och öppnar webbsidan. Första gången
du spelar in frågar webbläsaren om lov att använda mikrofonen.

Saknas en modell när tjänsten startar, till exempel efter att du har valt `MODELL=large`, visar
sidan vad som behöver hämtas, hur stort det är och varifrån det kommer. Tryck **Hämta nu**, så
hämtas och kontrolleras det utan att du behöver starta om något. En avbruten hämtning fortsätter
där den slutade nästa gång.

Kontrollera att allt fungerar (tar några minuter):

```bash
bash halsokoll/prov.sh
```

Alla rader ska börja med `OK` och sista raden ska vara `PROV: OK`. Provet transkriberar
testljuden i `testljud/` och raderar sina provinspelningar efteråt.

**Uppdatera:** `cd ~/akasha-meet && git pull && bash mac/installera.sh`

**Avinstallera:** `bash mac/avinstallera.sh`. Tjänsten stoppas, men inspelningar och modeller ligger
kvar tills du tar bort dem själv.

## Var hamnar inspelningarna?

I mappen `~/AkashaProtokoll` i din hemkatalog. På Windows är det `C:\Users\<namn>\AkashaProtokoll`. På
Mac kommer bara ditt konto åt mappen. På Windows ärver mappen rättigheterna från din användarmapp, och
programmet ändrar dem inte. För varje inspelning finns ljudet, en `.md` med texten och en `.json` med
uppgifterna. **Radera** i listan tar bort alla tre. Det gäller både programmet och installationen från
Terminal.

Mappen ligger medvetet inte i Dokument eller på Skrivbordet, eftersom de ofta synkas till iCloud.
Vill du ha den någon annanstans anger du `DATAKATALOG` i inställningarna (se nedan).

## Integritet och säkerhet

- Tjänsten lyssnar bara på `127.0.0.1`. Ingen annan dator i nätverket kommer åt den.
- Akasha Protokoll använder internet bara för att hämta modellerna, en gång: när du trycker **Hämta nu**
  på sidan eller kör installationen. Filerna kommer från Hugging Face (huggingface.co), med låsta
  versioner, och varje fil kontrolleras med sha256 innan den används. Programmet följer bara
  vidarekopplingar till Hugging Faces egna adresser, över https. Inga inspelningar, texter eller
  uppgifter om dig skickas, varken då eller senare.
- Andra webbsidor du har öppna kan inte styra tjänsten. Den svarar bara på `localhost`, och allt som
  ändrar något kräver en särskild header som en främmande sida inte får skicka.
- Ingen språkmodell skriver om eller sammanfattar texten. Det whisper hör är det som står.
- Programmet är ännu inte signerat och kontrollerat av Apple. Därför varnar macOS första gången du öppnar det.
- Windows-programmet är inte heller signerat. Windows kan därför varna första gången du startar det, och en
  del datorer, till exempel jobbdatorer, kan stoppa det helt (se Felsökning).

## Inställningar

Allt har standardvärden. I programmet ligger inställningarna i filen `installningar.env` i mappen
`~/Library/Application Support/Akasha Protokoll`. Filen finns inte från början. Skapa den med TextEdit
(Format → Gör till ren text), en inställning per rad, till exempel `MODELL=large`, och avsluta och
öppna Akasha Protokoll igen. Mappen hittar du i Finder med Gå → Gå till mapp…

**På Windows** ligger filen i `%LOCALAPPDATA%\Akasha Protokoll`, vanligen
`C:\Users\<namn>\AppData\Local\Akasha Protokoll`. Skriv `%LOCALAPPDATA%\Akasha Protokoll` i Utforskarens
adressfält och tryck Enter, så öppnas mappen. Filen `installningar.env` finns inte från början. Skapa den
med Anteckningar, en inställning per rad, till exempel `MODELL=large`. Välj Arkiv → Spara som, skriv
`installningar.env` som filnamn, välj kodningen **UTF-8**, och välj **Alla filer** som filtyp så att Windows
inte lägger till `.txt` efter namnet (namnen i rutan kan skilja mellan Windows-versioner, och det är inte
provat). Högerklicka på ikonen vid klockan, välj **Avsluta Akasha Protokoll** och starta programmet igen.
Modellerna ligger i mappen `modeller` bredvid filen.

Har filen ett fel, till exempel en rad som inte går att förstå eller fel sorts text, säger
programmet till när det startar och använder standardvärdet för just det. På Windows kommer rutan
**Inställningsfilen har fel**, och den frågar om du vill öppna mappen med inställningsfilen.

Har du installerat från Terminal gör du det i `.env`, som skapas vid installationen.
Starta sedan om tjänsten med `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`.

| Inställning | Standard | Vad |
|---|---|---|
| `MOTOR` | `auto` | `auto` väljer whisper.cpp med Metal på Apple Silicon, och whisper.cpp på processorn i Windows-programmet, som har en egen `whisper-cli.exe` med sig. I övrigt väljs faster-whisper på processorn. Går att tvinga med `whispercpp` eller `faster` (starta om Akasha Protokoll; sidan erbjuder att hämta det som saknas). `faster` går inte i programmet, varken på Mac eller Windows: faster-whisper följer inte med |
| `MODELL` | `medium` | `large` gör färre fel men tar längre tid och behöver 1,1 GB till (3,1 GB utan Apple Silicon). Starta om Akasha Protokoll efter att du ändrat. Sidan erbjuder då att hämta modellen |
| `ORDLISTA` | tom | Ord som alltid ska stavas rätt, till exempel företagets namn |
| `DATAKATALOG` | `~/AkashaProtokoll` (på Windows `C:\Users\<namn>\AkashaProtokoll`) | Var inspelningar och texter sparas |
| `PORT` | `8611` | Webbsidans port |
| `GRAFIK` | `av` | Bara Windows-programmet. `pa` provar grafikkretsen (Vulkan) i stället för processorn. På en Dell med Intels inbyggda grafik blev det långsammare (71 s mot 54 s för 34 s ljud), så processorn är standard. Mät själv, se Felsökning |
| `TALARE_TROSKEL` | `0.6` | Två röster som liknar varandra mer än så räknas som samma person (0–1) |
| `MAX_MB` | `1024` | Största fil som går att ladda upp |

## Felsökning

| Problem | Gör så här |
|---|---|
| Sidan öppnas inte | Mac-programmet: avsluta och öppna Akasha Protokoll igen. Loggen finns i `~/Library/Logs/Akasha Protokoll/akasha-protokoll.log` (öppnas med appen Konsol). Från Terminal: `launchctl kickstart -k gui/$(id -u)/local.akasha-meet`, och loggen `~/AkashaProtokoll/akasha-protokoll.log` |
| "Operation not permitted" i loggen, eller installationen säger att mappen ligger fel | Mappen med Akasha Protokoll ligger där macOS inte låter bakgrundstjänster läsa (Hämtade filer, Dokument, Skrivbord, iCloud Drive). Flytta den till hemkatalogen, ta bort mappen `venv` i den, och kör `bash mac/installera.sh` igen. Modellerna och .env följer med. |
| "Akasha Protokoll svarar inte" | Programmet har avslutats eller stannat. Öppna Akasha Protokoll igen. Från Terminal: tjänsten startar av sig själv när du loggar in, så logga ut och in igen, eller kör `launchctl kickstart -k gui/$(id -u)/local.akasha-meet` i Terminal. Det du redan spelat in ligger kvar. Sidan märker själv när Akasha Protokoll är igång igen. |
| Windows: sidan öppnas inte, eller sidan säger att Akasha Protokoll inte svarar | Titta efter ikonen vid klockan, kanske bakom pilen **^**. Finns den inte har programmet avslutats: starta **Akasha Protokoll.exe** igen. Det du redan spelat in ligger kvar. Finns ikonen, högerklicka och välj **Öppna Akasha Protokoll i webbläsaren**. Håller programmet på att starta och du startar det en gång till väntar den andra kopian högst 30 sekunder och öppnar sedan sidan. Svarar programmet inte alls visas rutan **Akasha Protokoll startar redan**: vänta en stund och försök igen, och hjälper det inte, starta om datorn. Loggen ligger i `%LOCALAPPDATA%\Akasha Protokoll\logg\akasha-protokoll.log` (öppnas i Anteckningar) |
| Windows: guiden säger att Akasha Protokoll är igång | Installationsfilen ser att programmet kör (ikonen vid klockan, kanske bakom pilen **^**). Högerklicka på ikonen, välj **Avsluta Akasha Protokoll** och klicka sedan på OK i guiden. Guiden stänger inte programmet själv, eftersom en inspelning kan pågå |
| Windows: programmet startar inte, eller Windows säger att en fil saknas (zip-filen) | Kontrollera att du har packat upp hela zip-filen med **Extrahera alla…** och att du startar **Akasha Protokoll.exe** i den uppackade mappen, inte inifrån zip-filen. Flytta inte bara `.exe`-filen: mappen `_internal` måste ligga bredvid den |
| Windows varnar när du startar programmet | Programmet är inte signerat, så Windows (SmartScreen) brukar varna första gången. Rutan har en länk för mer information och därefter en knapp för att köra ändå. Namnen på dem är inte sedda än och skrivs hit när programmet har provats på en riktig Windows-dator |
| Windows blockerar programmet och det finns ingen knapp för att köra ändå | Det kan bero på Smart App Control (i Windows 11) eller på regler på en jobbdator. Inget av det är provat här. Skriv ned vad rutan säger och säg till. Försök inte ta dig runt reglerna på en jobbdator: fråga IT om de kan godkänna programmet. Det lyssnar bara på `127.0.0.1` och använder internet bara för att hämta modellerna |
| Windows-säkerhet (Defender) säger att filen är ett hot, eller tar bort den | Program som byggs med samma verktyg som det här flaggas ibland av virusskydd, oftast felaktigt (uppgift ur forum, inte från Microsoft; det har inte hänt här än). Skriv ned vad Windows-säkerhet säger (hotets namn och filen), återställ filen under Skyddshistorik bara om du har hämtat den från repots egen sida, och säg till |
| "Akasha Protokoll" öppnades inte, eller "är skadat" | Se steg 3–6 under Som program: Klar, sedan Öppna ändå under Integritet och säkerhet → Säkerhet. Säger macOS att programmet är skadat, kör `xattr -dr com.apple.quarantine "/Applications/Akasha Protokoll.app"` i Terminal. |
| "Akasha Protokoll kan inte starta" (port 8611) | Ett annat program använder porten. Avsluta det, eller ange en annan port med `PORT=` i inställningarna. På Windows kan porten också vara reserverad av systemet, till exempel när Hyper-V, WSL eller Docker används (inte provat här). `netsh interface ipv4 show excludedportrange protocol=tcp` i Kommandotolken visar reserverade intervall. Välj då en annan port, till exempel `PORT=8612` i `installningar.env`. |
| "Akasha Protokoll startade inte" | Tryck **Visa loggen** och läs de sista raderna, eller skicka dem till den som hjälper dig. På Windows frågar rutan om du vill öppna mappen med loggen: svara *Ja* och öppna `akasha-protokoll.log`. Loggen innehåller inga inspelningar eller texter. |
| "Inte redo" uppe till höger | Håll muspekaren över texten för att se orsaken. Det är något som en hämtning inte kan rätta, till exempel en inställning i `.env` eller `installningar.env`. |
| "Modellerna behöver hämtas" uppe till höger | Tryck **Hämta nu** i rutan överst på sidan. Det görs bara en gång. |
| Hämtningen säger "Kunde inte nå Hugging Face" | Kontrollera att datorn är ansluten till internet och tryck **Försök igen**. Det som redan hämtats ligger kvar. |
| Hämtningen fungerar inte på ett företagsnät (certifikatfel eller inget svar) | Lägg in nätets proxy i inställningarna, till exempel `HTTPS_PROXY=http://proxy.foretaget.se:8080`, och vid behov företagets certifikat med `REQUESTS_CA_BUNDLE=/sökväg/till/certifikat.pem`. Avsluta och öppna Akasha Protokoll igen (från Terminal: starta om tjänsten), och tryck **Försök igen**. Programmet använder datorns egna certifikat (på Mac nyckelringen), så företagets certifikat behövs oftast inte. |
| "Det får inte plats på disken" | Frigör utrymme och tryck **Försök igen**. Sidan visar hur mycket som behövs. |
| "Kontrollsumman stämmer inte" | Filen har tagits bort. Tryck **Försök igen**. Händer det igen kan filen ha ändrats hos Hugging Face. |
| `Bootstrap failed: 5` vid installation | Uppdatera (`git pull`) och kör `bash mac/installera.sh` igen. Hjälper inte det: Systeminställningar → Allmänt → Inloggningsobjekt, tillåt `bash` i bakgrunden |
| "Fick inte tillgång till mikrofonen" | Tillåt mikrofonen för sidan i webbläsarens inställningar, och för webbläsaren i Systeminställningar → Integritet och säkerhet → Mikrofon. På Windows: kontrollera också att Windows släpper fram mikrofonen till webbläsaren, under Inställningar → Integritet och säkerhet → Mikrofon (namnen kan skilja mellan Windows-versioner, och mikrofonen i webbläsaren är inte provad på Windows) |
| Texten är inte uppdelad per talare | Tryck **Transkribera igen** i listan och välj fler än 1 under "Hur många pratar?" |
| Fel antal talare, eller "bara 1 röst gick att skilja åt" | Tryck **Transkribera igen** i listan och välj rätt antal. Ange inte fler än som pratar; är du osäker, välj **Vet inte – gissa**. Rösterna skiljs lättare åt om ni sitter på ungefär samma avstånd från datorn. Är ni många i rummet hjälper en konferensmikrofon mitt på bordet |
| Du vill visa någon hur det gick, utan att dela texten | `bash halsokoll/sammanfatta.sh` skriver ut tider, talare och tecken på fel, men inga ord ur mötet. `bash halsokoll/talardiagnos.sh` visar varför det blev så många talare, och `bash halsokoll/jamfor.sh <id A> <id B>` jämför två transkriberingar av samma möte. Se [docs/TEKNIK.md](docs/TEKNIK.md) |
| "Ljudet kan inte sparas på datorn" | Tryck Spara ljudet som fil och sedan Klar. Ladda upp filen med Ladda upp ljudfil och radera den ofullständiga inspelningen i listan. |
| "Inget ljud hörs" under inspelningen | Kontrollera att rätt mikrofon är vald och inte avstängd: i webbläsarens inställningar och i Systeminställningar → Ljud → Ingång. På Windows: Inställningar → System → Ljud, under Indata |
| Windows: du vill prova grafikkretsen | Skriv `GRAFIK=pa` i `installningar.env` och starta om programmet. Det är ett prov: whisper.cpp använder då den inbyggda grafikkretsen (Vulkan) i stället för processorn, och det är inte säkert att det går fortare eller blir lika bra, så mät själv. Går något fel, eller blir det ingen text ur ett ljud längre än 5 sekunder, går programmet tillbaka till processorn av sig självt, kör om transkriberingen och skriver filen `grafik-fungerade-inte` i programmappen (`%LOCALAPPDATA%\Akasha Protokoll`) med datum och sista felraden. Så länge filen finns används processorn. Ta bort filen för att försöka igen. Utan `GRAFIK=pa` används alltid processorn |
| Transkriberingen misslyckades | Öppna inspelningen och tryck **Försök igen** |
| Mötesljudet saknas i ett digitalt möte | Kryssade du i **Dela även flikljud**? Det går bara i Chrome. Gör en ny inspelning |
| Inspelningen fastnade på "Spelar in" | Tryck **Avsluta och transkribera** i listan |

## Teknik och utveckling

Hur det fungerar inuti, hur talaruppdelningen utvärderades och vad som är testat står i
[docs/TEKNIK.md](docs/TEKNIK.md). Enhetstesterna körs med
`venv/bin/python -m unittest discover -s tester`. `venv/bin/python tester/forsta_start.py` startar
sidan som vid första start, med en låtsaskälla i stället för Hugging Face.

Programmen för Mac och Windows byggs med `paketering/` och GitHub Actions (se [docs/TEKNIK.md](docs/TEKNIK.md)).
`python app/start.py` startar tjänsten och webbläsaren utan programmet.

## Källor och licenser

| Del | Licens |
|---|---|
| Akasha Protokoll (det här programmet), © 2026 Dennis Fredin | Apache-2.0, se [LICENSE](LICENSE) och [NOTICE](NOTICE) |
| [KB-Whisper medium](https://huggingface.co/KBLab/kb-whisper-medium) (KBLab, Kungliga biblioteket) | Apache-2.0 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [whisper.cpp](https://github.com/ggml-org/whisper.cpp) (whisper.cpp följer med programmen för Mac och Windows) | MIT |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 |
| [pystray](https://github.com/moses-palmer/pystray) (ikonen vid klockan; följer med Windows-programmet) | LGPL-3.0. Dess kod ligger som vanliga `.py`-filer i programmet, så att den går att byta ut |
| [Pillow](https://github.com/python-pillow/Pillow) (bilden till ikonen; följer med Windows-programmet) | MIT-CMU |
| Microsofts Visual C++-runtime (`MSVCP140.dll`, `VCOMP140.DLL`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll`; följer med Windows-programmet) | Microsofts licensvillkor för Visual Studio. Filerna är tagna ur Visual Studios Redist-katalog |
| [PyAV](https://github.com/PyAV-Org/PyAV) med FFmpeg, Python, Flask, numpy, PyObjC och de andra delarna i programmet | Var och en sin licens. En förteckning läggs till innan programmet släpps |
| NeMo TitaNet small (NVIDIA), via sherpa-onnx | CC-BY-4.0 |
| Typsnitten [Anton](https://github.com/googlefonts/AntonFont) och [Instrument Sans](https://github.com/Instrument/instrument-sans) (följer med programmet) | SIL Open Font License 1.1, se app/static/typsnitt/ |
| Testljud: [Google FLEURS](https://huggingface.co/datasets/google/fleurs) | CC-BY-4.0 |
