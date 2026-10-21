# Home Theater App — Piano di progetto

Oct 16, 2026 · @Ema

## Obiettivo e requisiti

Un'app home theater personale per la TV Hisense di casa (VIDAA OS), con cui sfogliare e guardare film e serie della propria libreria in almeno Full HD. Deve sembrare un'app vera, avviata da un'icona nella home della TV, e usabile da chi in casa non è tecnico.

**Requisiti**

- Riproduzione fluida almeno a 1080p, senza perdita di qualità rispetto al file originale
- Avvio da icona nella home VIDAA, a schermo intero, senza passare dal browser
- Uso completo con il solo telecomando: frecce, OK, Back, Play/Pausa
- Libreria con locandine, trame, stagioni ed episodi
- "Continua a guardare" e stato visto/non visto
- Frontend il più leggero possibile, adatto al browser datato della TV

**Fuori scopo per ora**: accesso da fuori casa, più utenti con profili separati, pubblicazione sullo store VIDAA.

## Architettura generale

In casa ci sono solo due pezzi: la TV, che mostra il frontend, e il laptop, dove gira tutto il resto in Docker. L'unico codice da scrivere è il frontend.

&#91;embedded content: architettura · TV, laptop e metadati online\]

La TV chiama un solo indirizzo, quello di Caddy, che serve i file del frontend e inoltra API e video a Jellyfin. Così non ci sono problemi di CORS e, quando il server passerà a un'altra macchina, cambierà solo l'IP.

## Backend: Jellyfin

Il backend è Jellyfin, media server open source: non scriviamo codice server, lo configuriamo e lo usiamo via API REST. Nella fase di prova gira in Docker sul laptop.

**Cosa ci dà già pronto**

- Scansione delle cartelle e riconoscimento di film, serie, stagioni ed episodi
- Metadati e immagini (locandine, trame, cast) da fonti come TMDB, salvati in locale
- Utenti, avanzamento della visione, "continua a guardare"
- Motore di streaming che sceglie tra direct play, remux e transcodifica in base al profilo del client

**API che userà il frontend**

| Scopo | Cosa chiamiamo |
| --- | --- |
| Autenticazione | Login utente o API key creata dal pannello admin |
| Liste di film e serie | Endpoint `Items`, filtrati per tipo e libreria |
| Locandine | Endpoint immagini, chiedendo la dimensione già ridotta per la TV |
| Avvio riproduzione | `PlaybackInfo` con il device profile della TV, restituisce l'URL di streaming |
| Avanzamento | Report di inizio, progresso e stop della riproduzione |

**Setup sul laptop**

- Container `jellyfin/jellyfin` con volumi per configurazione, cache e cartella media, più un container Caddy davanti che serve il frontend e fa da reverse proxy
- Interfaccia admin sulla porta 8096, da cui si crea la libreria
- Prenotazione DHCP sul router, così il laptop ha sempre lo stesso IP in LAN

**Naming dei file**, da rispettare perché la scansione funzioni:

- Film: `Titolo (Anno)/Titolo (Anno).mkv`
- Serie: `Serie/Season 01/Serie S01E01.mkv`

## Frontend: scelta del framework

Scelta proposta: **Preact + Vite**, con una libreria di navigazione spaziale e build transpilata per browser datati. È leggerissimo (Preact pesa circa 3 KB), usa il modello React che già conosco, e resta una web app pura riutilizzabile anche sul piano B.

**Vincoli della TV**

- CPU e memoria molto inferiori a un telefono: niente animazioni pesanti, poche immagini grandi alla volta
- Browser VIDAA datato: build transpilata (es. plugin legacy di Vite) e test reali sulla TV
- Solo telecomando: serve una navigazione spaziale (frecce che spostano il focus tra elementi vicini)

**Opzioni valutate**

| Opzione | Peso | Navigazione col telecomando | Pro | Contro |
| --- | --- | --- | --- | --- |
| Preact + Vite | Molto basso | Libreria [preact-spatial-navigation](https://app.unpkg.com/preact-spatial-navigation@1.3.1/files/README.md) o il core di [Norigin](https://github.com/noriginmedia/norigin-spatial-navigation) | Sintassi React, ecosistema ampio, DOM normale per il player | La navigazione va integrata a mano |
| SolidJS | Molto basso | [solidjs-spatial-navigation](https://github.com/LampaWebDev/solidjs-spatial-navigation), dichiarata testata su VIDAA | Reattività fine, ottime prestazioni | Ecosistema più piccolo, sintassi da imparare |
| Lightning 3 + Blits | Basso, ma render WebGL | Gestione del focus integrata | Il più veloce sulle TV economiche, [pensato per hardware limitato](https://lightningjs.io/blogs/roadToPerformance.html) | Sintassi propria, il supporto WebGL su VIDAA va verificato, curva di apprendimento alta |
| Vanilla TypeScript | Minimo | Da scrivere da zero | Zero dipendenze | Tutto (routing, stato, componenti) va riscritto |

**Struttura dell'app**: quattro schermate (Home, Libreria, Dettaglio, Player), un client API sottile verso Jellyfin, un router minimale e la gestione del tasto Back su ogni schermata.

Se i test sulla TV mostrano lag nello scorrimento delle griglie, il ripiego è SolidJS; Lightning solo se anche quello non basta.

## Riproduzione video e codec

Il Full HD si ottiene evitando la transcodifica video: la TV decodifica in hardware H.264 e HEVC, quindi il server deve al massimo cambiare contenitore o audio.

| Caso | Cosa fa Jellyfin | Costo sul server | Qualità |
| --- | --- | --- | --- |
| File già compatibile | Direct play, invia il file com'è | Nullo | Originale |
| Contenitore non supportato (tipico: MKV) | Remux in HLS senza ricodificare | Molto basso | Originale |
| Audio non supportato (DTS, TrueHD) | Transcodifica solo l'audio | Basso | Video originale |
| Codec video non supportato | Transcodifica completa con ffmpeg | Alto | Ridotta |

**Player nel frontend**: elemento `<video>` nativo con HLS se la TV lo supporta, altrimenti hls.js sopra le Media Source Extensions. Il device profile inviato a `PlaybackInfo` dichiara a Jellyfin cosa sa fare la TV.

**Rete**: un 1080p richiede circa 8–20 Mbps; Ethernet sulla TV dove possibile, altrimenti Wi-Fi a 5 GHz.

**Test di compatibilità (da fare prima del frontend)**

- [ ] Aprire dalla TV l'interfaccia web di Jellyfin e provare alcuni film
- [ ] Verificare video H.264 e HEVC, anche a 10 bit
- [ ] Verificare audio AAC, AC3, EAC3, DTS
- [ ] Verificare sottotitoli SRT e quelli incorporati
- [ ] Controllare dal pannello admin quali riproduzioni finiscono in transcodifica

## Distribuzione sulla TV

L'app arriva sulla TV come hosted app: sulla TV c'è solo un'icona che apre a schermo intero l'URL del nostro frontend. Il codice vive sul server, quindi ogni aggiornamento è visibile subito senza reinstallare.

**Piano A: icona VIDAA tramite tool della community**

- Tool open source che, con un redirect DNS temporaneo, aggiunge alla home VIDAA un'app che punta a un URL scelto da noi
- Installazione una tantum, puntando a `http://<ip-laptop>:<porta>`
- Non ufficiale: un aggiornamento firmware può romperlo, e il codice del tool va letto prima di usarlo
- La pubblicazione ufficiale (developer account, NDA, certificazione) non ha senso per un uso domestico

**Piano B: chiavetta HDMI Google TV o Fire TV (30–70 €)**

- Lo stesso frontend impacchettato in una WebView (es. Capacitor) e installato come APK
- Installazione ufficiale e stabile, compatibilità codec di solito migliore
- Con HDMI-CEC si usa comunque un solo telecomando

Il frontend resta una web app pura, senza API specifiche di VIDAA, così il passaggio dal piano A al B non richiede riscritture.

## Rischi e mitigazioni

| Rischio | Impatto | Mitigazione |
| --- | --- | --- |
| Il tool community smette di funzionare dopo un aggiornamento VIDAA | L'icona sparisce o non si apre | Disattivare gli aggiornamenti automatici se possibile; piano B con chiavetta HDMI |
| Il laptop è spento o cambia IP | L'app non si apre | Prenotazione DHCP; schermata "server non raggiungibile" curata; in seguito server sempre acceso |
| Codec o sottotitoli non supportati dal player della TV | Transcodifica pesante o video che non parte | Test di compatibilità prima di scrivere il frontend; remux e transcodifica solo audio |
| Browser VIDAA troppo datato per il JS moderno | Pagina bianca o errori | Build transpilata, test sulla TV fin dalla prima schermata |
| Prestazioni scarse nelle griglie di locandine | Navigazione a scatti | Immagini ridotte lato server, liste virtualizzate, ripiego su SolidJS |
| Rete Wi-Fi instabile | Buffering | Ethernet sulla TV, bitrate massimo configurato su Jellyfin |

## Fasi e milestone

Il progetto procede in cinque fasi, e il frontend si scrive solo dopo aver verificato che la TV riproduce i file senza transcodifica video.

&#91;embedded content: fasi del progetto · 5 fasi, 4 gate\]

Le fasi 1 e 2 non richiedono codice: servono a togliere i dubbi tecnici prima di investire tempo sull'interfaccia.

## Decisioni aperte

- [ ] Framework definitivo: Preact o SolidJS, da decidere dopo un prototipo di griglia sulla TV
- [ ] Hardware del server definitivo dopo la prova sul laptop (mini PC Intel N100/N150 se serve transcodifica, altrimenti anche un Raspberry Pi 5)
- [ ] Un solo utente Jellyfin per la casa o profili separati
- [ ] Lingua di default di audio e sottotitoli
- [ ] Se e quando aprire l'accesso da fuori casa (VPN tipo Tailscale o WireGuard)

## Fonti

- [VIDAA: partner e supporto HTML5](https://www.vidaa.com/?p=20)
- [VIDAA: guida tecnica alle web app](https://www.vidaa.com/wp-content/uploads/2020/12/WebApp_Development_Guide_for_VIDAA.pdf)
- [Lightning 3 e Blits: prestazioni su TV](https://lightningjs.io/blogs/roadToPerformance.html)
- [Norigin Spatial Navigation](https://github.com/noriginmedia/norigin-spatial-navigation)
- [preact-spatial-navigation](https://app.unpkg.com/preact-spatial-navigation@1.3.1/files/README.md)
- [solidjs-spatial-navigation](https://github.com/LampaWebDev/solidjs-spatial-navigation)

