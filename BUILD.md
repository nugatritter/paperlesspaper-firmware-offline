# Build- und Flash-Anleitung: 13,3-Zoll-Display

## Zweck und verbindliche Vorgaben für Build-Agenten

Dieses Dokument beschreibt den Firmware-Build für das paperlesspaper-Display mit 13,3 Zoll (Spectra 6, EL133UF3) und ESP32-C6.

- Als Arbeitsverzeichnis das Verzeichnis `paperlesspaper-firmware-offline` verwenden.
- Den Build über `build.ps1` ausführen. Das Skript gibt die Umgebung `epd13` immer ausdrücklich an, prüft Konfiguration und Image und schreibt ein Log.
- Bei direktem PlatformIO-Aufruf immer `-e epd13` angeben. Nicht auf `default_envs` verlassen: Der Standard ist `epd7`.
- Den Exitcode von `build.ps1` auswerten. Nur Exitcode `0` bedeutet ein geprüftes, verwendbares Image.
- Der bekannte serielle Port dieses Rechners ist `COM10`.
- Ein Build allein programmiert kein Gerät. Hardware nur flashen, wenn der Auftrag dies ausdrücklich verlangt und das Zielgerät eindeutig bestimmt ist.
- Vor einem Firmware-Wechsel von der Cloud-Firmware die gerätespezifischen Zertifikate sichern.
- Niemals den gesamten Flash löschen und keine Dateisystem-Images flashen.

## Zielhardware

| Eigenschaft | Wert |
| --- | --- |
| Display | Spectra 6, 13,3 Zoll, EL133UF3 |
| Mikrocontroller | ESP32-C6 |
| PlatformIO-Board-ID | `esp32-c6-devkitm-1` |
| PlatformIO-Umgebung | `epd13` |
| Build-Flag | `-DEPD_TYPE_13INCH` |
| Partitionstabelle | `part.csv` |

Die Firmware wählt Displaytyp und zugehörige Abmessungen über das Build-Flag der Umgebung aus. Ein Build mit `epd7` ist für dieses Display nicht geeignet.

## Voraussetzungen

### Erforderlich für den Firmware-Build

- Für `build.ps1`: Windows mit Windows PowerShell 5.1 oder PowerShell 7. Beide Versionen sind getestet. Auf macOS oder Linux PlatformIO direkt aufrufen (siehe [Direkter PlatformIO-Aufruf](#direkter-platformio-aufruf)).
- Internetzugang und etwa 2 GB freier Speicher beim ersten Build.
- Auf diesem Rechner ist die VS-Code-Erweiterung `platformio.platformio-ide` bereits installiert. `build.ps1` findet PlatformIO im `PATH` oder unter `%USERPROFILE%\.platformio\penv\Scripts`. Alternativ kann eine separat installierte PlatformIO-Core-CLI (`pio`) genutzt werden.
- Git im `PATH`. GxEPD2 und SerialFlash werden per Git geladen.
- PlatformIO lädt die ESP32-Plattform, den Arduino-Framework-Unterbau, Compiler, Upload-Werkzeuge und die Bibliotheken aus der Projektkonfiguration automatisch herunter.

Das Repository pinnt keine Version der PlatformIO-Core-CLI. Die pioarduino-Plattform erwartet PlatformIO Core 6.1 oder neuer; `build.ps1` warnt bei älteren Versionen. Die Arduino-Framework-Version und die Toolchain kommen aus der konfigurierten PlatformIO-Plattform.

Blockiert die PowerShell-Ausführungsrichtlinie das Skript, einmalig so starten:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

### Zusätzlich für USB-Flashen

- USB-Datenkabel und ein freier serieller Anschluss.
- Bei Windows gegebenenfalls der Silicon Labs CP210x USB-to-UART-Treiber. Fehlt der Treiber, kann das Gerät im Geräte-Manager als `CP2102N USB to UART Bridge Controller` unter „Andere Geräte“ erscheinen. `build.ps1 -Upload` erkennt diesen Zustand und meldet ihn.
- Das Gerät muss im ROM-Bootloader sein. Der ESP32-C6-Boardaufbau setzt den Bootloader nicht zuverlässig automatisch zurück.

## Firmware-Abhängigkeiten

Die maßgebliche Konfiguration ist [`platformio.ini`](./platformio.ini).

| Abhängigkeit | Deklaration in `platformio.ini` |
| --- | --- |
| ESP32-Plattform | `https://github.com/pioarduino/platform-espressif32/releases/download/55.03.37/platform-espressif32.zip` |
| Framework | `arduino` (von der Plattform bereitgestellt) |
| Board | `esp32-c6-devkitm-1` |
| GxEPD2 | `https://github.com/smarthomeagentur/GxEPD2.git` |
| SerialFlash | `https://github.com/smarthomeagentur/SerialFlash.git` |
| Adafruit GFX Library | `adafruit/Adafruit GFX Library@^1.11.11` |
| ArduinoJson | `bblanchon/ArduinoJson@^7.3.0` |
| U8g2 for Adafruit GFX | `olikraus/U8g2_for_Adafruit_GFX@^1.8.0` |
| KXTJ3-1057 | `ldab/KXTJ3-1057@^0.1.1` |
| NimBLE-Arduino | `h2zero/NimBLE-Arduino@^2.3.4` |
| QRCode | `ricmoo/QRCode@^0.0.1` |
| JPEGDEC | `bitbank2/JPEGDEC@^1.8.4` |
| SdFat | `greiman/SdFat@^2.2.2` |

Die C/C++-Standardbibliothek sowie ESP32-/Arduino-Komponenten wie Wi-Fi, SPI, Wire, Preferences, Update und SPIFFS werden über Toolchain und Framework bereitgestellt; sie sind keine zusätzlichen `lib_deps`.

Die beiden Git-Abhängigkeiten GxEPD2 und SerialFlash sind in der Projektdatei nicht auf einen Tag oder Commit festgelegt. Die übrigen Bibliotheken verwenden die oben angegebenen Versionsbereiche. `build.ps1` protokolliert deshalb bei jedem Build die tatsächlich aufgelösten Plattform- und Bibliotheksversionen im Log und zeigt die Commits der Git-Bibliotheken in der Zusammenfassung.

Beim geprüften Build am 17.11.2026 wurden diese Versionen aufgelöst:

| Paket | Aufgelöste Version |
| --- | --- |
| Plattform espressif32 | 55.3.37 |
| framework-arduinoespressif32 | 3.3.7 |
| toolchain-riscv32-esp | 14.2.0+20251107 |
| tool-esptoolpy | 5.1.2 |
| GxEPD2 | 1.6.7+sha.ffb2031 |
| SerialFlash | 0.6.0+sha.13f477b |

Zwei Builds desselben Quellstands sind nicht bitidentisch, weil die Kompilierzeit ins Image eingeht. Die SHA-256-Summe identifiziert also ein einzelnes Build-Ergebnis, nicht einen Quellstand.

### Optionale Konfiguration

`set_env.py` wird als PlatformIO-Pre-Script ausgeführt. Eine `.env`-Datei ist optional. Fehlt sie, gibt das Script `Warning: .env file not found.` aus und der Build läuft weiter. Vorhandene `KEY=value`-Einträge werden als C/C++-Definitionen ergänzt. `build.ps1` meldet nur, ob eine `.env` vorhanden ist, und schreibt ihren Inhalt nie ins Log. Keine Geheimnisse in Git einchecken.

## Firmware bauen

Im Firmware-Projektverzeichnis in PowerShell oder im VS-Code-Terminal ausführen:

```powershell
cd F:\eYellowBoard\paperlesspaper-firmware-offline
.\build.ps1
```

Das Skript baut ausschließlich `epd13` und flasht ohne `-Upload` nichts. Das App-Image liegt danach hier:

```text
.pio\build\epd13\firmware.bin
```

### Ablauf

| Schritt | Was geprüft oder getan wird | Abbruch mit Exitcode |
| --- | --- | --- |
| 1. Umgebung prüfen | PowerShell-Version, Projektdateien, PlatformIO und dessen Version, Git, Git-Revision und lokale Änderungen, freier Speicher, `.env` | 2 |
| 2. Projektkonfiguration prüfen | `[env:epd13]` vorhanden, Build-Flag `-DEPD_TYPE_13INCH` gesetzt und `-DEPD_TYPE_7INCH` nicht, Board `esp32-c6-devkitm-1`, Partitionstabelle `part.csv`, Größe von `app0` und `app1` | 2 |
| 3. Firmware bauen | `pio run -e epd13`, optional vorher Bereinigung. Bei erkannten Netzwerkfehlern folgt nach 15 Sekunden automatisch ein zweiter Versuch. | 3 |
| 4. App-Image prüfen | Magic Byte `0xE9`, Segmentanzahl, Chip-ID 13 (ESP32-C6), App-Beschreibung (kein Bootloader- oder Komplett-Image), angehängter SHA-256-Hash, Größe gegen die App-Partition, Aktualität gegenüber den Quellen, Gegenprüfung mit `esptool image-info` | 4 |
| 5. Paketversionen protokollieren | `pio pkg list -e epd13` ins Log, Commits der Git-Bibliotheken in die Zusammenfassung | nur Warnung |
| 6. Upload (nur mit `-Upload`) | Port vorhanden, Gerät ist eine CP210x-Brücke oder ein Espressif-USB-Gerät, Treiber in Ordnung. Bootloader, Partitionstabelle und otadata vorhanden und plausibel. Danach Wechsel in den ROM-Bootloader per `B` und Upload genau der geprüften Dateien direkt mit esptool, mit Hash-Verifikation. Mit `-WhatIf` endet der Schritt nach Port- und Imageprüfung. | 4, 5, 6 oder 7 |

Die Image-Prüfungen entsprechen denen der Web-Oberfläche in [`web/src/DeviceBleInterface.js`](./web/src/DeviceBleInterface.js). Ein Image, das `build.ps1` akzeptiert, akzeptiert also auch die Web-Oberfläche.

Eine Sperrdatei unter `.pio` verhindert zwei gleichzeitige Läufe. Das Skript setzt für PlatformIO und esptool UTF-8-Ausgabe und stellt Umgebungsvariablen und Konsolenkodierung danach wieder her.

### Parameter

| Parameter | Wirkung |
| --- | --- |
| ohne Parameter | Bauen und prüfen, kein Upload |
| `-Clean` | Vorher die Build-Ausgabe von `epd13` löschen. Heruntergeladene Bibliotheken bleiben erhalten. |
| `-VerifyOnly` | Nicht bauen, nur das vorhandene Image prüfen. Mit `-Upload` wird es ohne Neubau geflasht. Nicht mit `-Clean` kombinierbar. |
| `-Upload` | Nach Build und Prüfung das Gerät in den ROM-Bootloader schalten und per USB flashen |
| `-WhatIf` | Mit `-Upload`: alles bis zur Portprüfung ausführen und den Upload nur anzeigen. Das Gerät wird nicht angesprochen. |
| `-NoAutoBootloader` | Kein `B` senden. Das Gerät muss bereits von Hand im ROM-Bootloader sein. |
| `-BootloaderTimeout n` | Wartezeit in Sekunden bis zum ROM-Bootloader, Standard 60 |
| `-Port COMx` | Port für den Upload, Standard `COM10` |
| `-UploadBaud n` | Baudrate für den Upload, Standard `2000000`. Bei Abbrüchen, etwa mit anderer USB-Brücke, langem Kabel oder USB-Hub, `921600` verwenden. |
| `-Monitor` | Mit `-Upload`: nach erfolgreichem Upload den seriellen Monitor mit Exception-Decoder öffnen. Danach Reset drücken. Beenden mit Strg+C. |
| `-Verbose` | Ausführliche PlatformIO-Ausgabe (`pio -v`) und Ausgabe aller Hilfsbefehle |
| `-KeepLogs n` | Anzahl der aufbewahrten Logdateien, Standard 20 |

`Get-Help .\build.ps1 -Detailed` zeigt dieselben Informationen im Terminal.

### Exitcodes

| Code | Bedeutung |
| --- | --- |
| 0 | Erfolg. Das Image ist geprüft; mit `-Upload` ist es auch geschrieben und verifiziert. |
| 1 | Unerwarteter Fehler im Skript. Position und Stacktrace stehen im Log. |
| 2 | Voraussetzungen oder Projektkonfiguration fehlerhaft, ungültige Parameterkombination oder paralleler Lauf |
| 3 | Build fehlgeschlagen |
| 4 | App-Image ungültig |
| 5 | Serieller Port fehlt, ist belegt oder gehört nicht zum Zielgerät. Es wurde nichts geschrieben. |
| 6 | Upload fehlgeschlagen |
| 7 | Gerät nicht in den ROM-Bootloader gekommen. Es wurde nichts geschrieben. |

### Ausgabe und Log

Jede Zeile auf der Konsole trägt eine Kennung: `[OK]`, `[WARNUNG]`, `[FEHLER]` oder `[HINWEIS]`. Ausgeführte Befehle beginnen mit `>`. Am Ende folgt immer eine Zusammenfassung mit Dauer und Status jeder Phase, PlatformIO-Version, Git-Revision, Speicherauslastung, Image-Pfad, Größe, SHA-256, Git-Bibliotheken, Upload-Status und allen Warnungen.

Im Fehlerfall wiederholt die Zusammenfassung die relevanten Fehlerzeilen, nennt die Ursache und gibt konkrete Hinweise für bekannte Fehlerbilder. Die letzte Zeile lautet immer `ERGEBNIS: Erfolg.` oder `ERGEBNIS: fehlgeschlagen (Exitcode n).`

Das vollständige Protokoll liegt unter `.pio\logs\build-epd13-<Datum>-<Uhrzeit>.log`. Es enthält mit Zeitstempel jede Ausgabezeile, jeden Befehl mit Exitcode, den Git-Status und die vollständige Paketliste. Die 20 neuesten Logs bleiben erhalten.

### Erfolgskriterien

Ein Build ist erfolgreich, wenn der Exitcode `0` ist und die letzte Zeile `[OK] ERGEBNIS: Erfolg.` lautet. Beim geprüften Stand ergaben sich diese Werte:

| Kennzahl | Wert |
| --- | --- |
| Größe von `firmware.bin` | 1.794.320 Bytes |
| Belegung der App-Partition | 94,4 %, 103,7 KB frei |
| Flash laut PlatformIO | 91,4 % |
| RAM laut PlatformIO | 62,8 % |
| Dauer mit `-Clean` | etwa 4 Minuten |
| Dauer ohne Änderungen | etwa 30 Sekunden |

PlatformIO zählt nur die Programmabschnitte. Die Belegung der App-Partition bezieht sich auf die Datei mit Headern, Ausrichtung und Hash und ist deshalb höher. Sinkt der freie Platz unter 5 %, gibt `build.ps1` eine Warnung aus.

### Direkter PlatformIO-Aufruf

Ohne `build.ps1`, etwa auf macOS oder Linux, entfallen alle Prüfungen und das Log. Die Befehle lauten dann:

```powershell
pio run -e epd13              # bauen
pio run -e epd13 -t clean     # Build-Ausgabe löschen
pio run -e epd13 -v           # ausführliche Ausgabe
pio pkg list -e epd13         # aufgelöste Versionen anzeigen
```

Wird die Ausgabe von `pio` unter Windows umgeleitet, bricht `pio pkg list` mit `UnicodeEncodeError` ab. Vorher `$env:PYTHONUTF8 = '1'` setzen.

## Firmware auf das Gerät übertragen

### Variante A: Skript mit explizitem USB-Upload

1. Das Gerät per USB anschließen. Serial Monitor und Web-Oberfläche schließen, damit der Port frei ist.
2. Optional den Ablauf zuerst simulieren. Das Skript baut, prüft Image und Port und zeigt, was geschrieben würde, ohne das Gerät anzusprechen:

   ```powershell
   .\build.ps1 -Upload -WhatIf
   ```

3. Den Upload starten:

   ```powershell
   .\build.ps1 -Upload
   ```

   Bei anderem Port:

   ```powershell
   .\build.ps1 -Upload -Port COM11
   ```

4. Erscheint `[HINWEIS] Keine Reaktion. Jetzt den großen Reset-Knopf einmal kurz drücken`, den Reset-Knopf einmal drücken. Das Skript wartet bis zu 60 Sekunden.
5. Nach `[OK] Upload auf COM10 erfolgreich.` den großen Reset-Knopf drücken. Das Board hat keinen automatischen Reset; ohne diesen Schritt startet die neue Firmware nicht.
6. Optional die serielle Ausgabe prüfen. Beim Start erscheint `[MAIN] test mode check...`. Am bequemsten öffnet das Skript den Monitor gleich nach dem Upload; dann erst Reset drücken, damit die Startausgabe vollständig erscheint:

   ```powershell
   .\build.ps1 -Upload -Monitor
   ```

   Ohne Skript:

   ```powershell
   pio device monitor -p COM10 -b 115200
   ```

   Den Monitor vor dem nächsten Upload schließen, sonst ist der Port belegt.

Mehrere Geräte nacheinander mit demselben Image flashen, ohne jedes Mal zu bauen:

```powershell
.\build.ps1 -VerifyOnly -Upload -Port COM10
```

Vor dem Upload listet das Skript alle seriellen Ports auf. Es bricht mit Exitcode 5 ab, ohne etwas zu schreiben, wenn der Port fehlt, keine CP210x-Brücke und kein Espressif-USB-Gerät ist, ein Treiberproblem meldet oder belegt ist. Sind mehrere mögliche Zielgeräte angeschlossen, warnt es. Die Upload-Geschwindigkeit ist standardmäßig `2000000` Baud, am 17.11.2026 mit der CP2102N-Brücke des Geräts stabil getestet. Mit `-UploadBaud 921600` lässt sie sich bei Übertragungsfehlern senken. Der direkte PlatformIO-Upload nutzt weiterhin `upload_speed = 921600` aus `platformio.ini`.

Danach bringt das Skript das Gerät ohne Boot-Knopf in den ROM-Bootloader, wie die Web-Oberfläche:

1. esptool fragt nur lesend und ohne Reset, ob der ROM-Bootloader bereits antwortet. Das ist der Fall, wenn das Gerät von Hand in den Bootloader gebracht wurde.
2. Sonst sendet das Skript alle 100 ms das Zeichen `B` mit 115200 Baud. Die Firmware startet daraufhin in den ROM-Bootloader neu, wenn sie gerade startet oder im Setup-Modus ist und USB-Versorgung erkennt. Ein Gerät im Setup-Modus wechselt sofort.
3. Kommt nach 4 Sekunden keine Reaktion, bittet das Skript um einen Druck auf Reset. Das schlafende Gerät startet dann und reagiert auf `B`.
4. Startet eine Firmware, die `B` nicht kennt, nennt das Skript nach 8 Sekunden die Schritte mit dem Boot-Knopf und wartet weiter.
5. Das Gerät gilt als bereit, sobald die ROM-Ausgabe `waiting for download` erscheint. Bleibt sie innerhalb der Wartezeit aus, endet das Skript mit Exitcode 7, ohne etwas zu schreiben.

Mit `-NoAutoBootloader` entfällt dieser Schritt. Das Gerät muss dann bereits von Hand im Bootloader sein. Die Wartezeit lässt sich mit `-BootloaderTimeout` ändern.

Der Upload schreibt diese Bereiche:

| Adresse | Inhalt |
| --- | --- |
| `0x0` | Bootloader (`bootloader.bin`) |
| `0x8000` | Partitionstabelle (`partitions.bin`) |
| `0xE000` | otadata (`boot_app0.bin`), damit der Bootloader `app0` startet |
| `0x10000` | App-Image (`firmware.bin`) |

Die Partition `spiffs` bei `0x3B0000` mit den Zertifikaten wird nicht beschrieben. esptool verifiziert jeden geschriebenen Bereich per Hash; das Skript zählt diese Bestätigungen.

`build.ps1` ruft für den Upload esptool direkt auf, nicht `pio run -t upload`. Gründe:

- Es werden genau die geprüften Dateien geschrieben. `pio run -t upload` baut vorher inkrementell und kann ein anderes als das geprüfte Image flashen. Das Ziel `-t nobuild` ist mit dieser Plattform nicht nutzbar, weil esptool dann keine Flash-Adressen erhält.
- Der zweite PlatformIO-Lauf mit Abhängigkeitsanalyse entfällt.
- Mit `--flash-mode keep --flash-freq keep --flash-size keep` übernimmt esptool die Werte aus den Image-Headern (DIO, 80 MHz, 4 MB). Die Bytes bleiben unverändert, die Adressen entsprechen dem PlatformIO-Upload.

Die SHA-256-Summen aller vier Dateien stehen im Log. Unmittelbar vor dem Schreiben prüft das Skript sie erneut und bricht ab, falls ein paralleler Build eine Datei verändert hat.

Ein automatischer Start der neuen Firmware nach dem Upload ist nicht eingebaut. Das Board verdrahtet RTS nicht mit Reset, und esptool unterstützt den Watchdog-Reset für den ESP32-C6 bewusst nicht. Zudem setzt die Firmware beim Wechsel per `B` das Flag `LP_AON_FORCE_DOWNLOAD_BOOT`, das einen Watchdog-Reset möglicherweise überdauert. Eine solche Lösung müsste erst am Gerät geprüft werden.

Alternativ kann der Upload direkt über PlatformIO gestartet werden. Dabei entfallen Portprüfung und Image-Prüfung:

```powershell
pio run -e epd13 -t upload --upload-port COM10
```

Wenn das Gerät nicht in den Bootloader wechselt, etwa mit einer älteren Firmware ohne `B`-Kommando oder einer Firmware, die nicht mehr startet:

1. Den kleinen Knopf unter der Holzabdeckung gedrückt halten.
2. Kurz den großen Reset-Knopf drücken.
3. Den kleinen Knopf loslassen.
4. Den Upload sofort erneut starten, am besten mit `.\build.ps1 -Upload -NoAutoBootloader`.

### Variante B: Eigene Firmware über die Web-Oberfläche

Die Upstream-Web-Oberfläche unterstützt USB-Flashen und Firmware-Updates über Bluetooth:

1. Mit `.\build.ps1` bauen. Für ein bereits vorhandenes Image genügt `.\build.ps1 -VerifyOnly`.
2. Die Web-Oberfläche in Chrome, Edge oder Opera öffnen.
3. Im Bereich **Firmware** die Option für eigene Firmware auswählen.
4. `.pio\build\epd13\firmware.bin` auswählen.
5. USB oder Bluetooth als Übertragungsweg wählen und den Anweisungen folgen. Bei USB im Portdialog `COM10` auswählen.

Für Bluetooth das Gerät zuvor mit Reset in den Setup-Modus bringen und verbinden. Für USB werden Web Serial und ein erreichbarer serieller Port benötigt; ein offener Serial Monitor blockiert ihn. Die Web-Oberfläche akzeptiert das PlatformIO-App-Image `firmware.bin`, nicht ein Bootloader-, kombiniertes Flash- oder Dateisystem-Image.

Soll die Web-Oberfläche lokal aus diesem Checkout gestartet werden, ist das optional und nicht Teil des Firmware-Builds:

```powershell
cd F:\eYellowBoard\paperlesspaper-firmware-offline\web
npm install
npm run dev
```

Node.js und npm sowie die in [`web/package.json`](./web/package.json) aufgeführten Pakete werden dafür benötigt.

## Flash-Sicherheit

- Die Partition `spiffs` beginnt laut [`part.csv`](./part.csv) bei `0x3B0000` und ist `0x40000` Bytes groß. Die Cloud-Firmware speichert dort gerätespezifische Zertifikate.
- Vor dem Wechsel von der Cloud-Firmware Zertifikate über die Web-Oberfläche sichern.
- Kein `erase_flash`, keinen vollständigen Flash-Reset und kein SPIFFS-/Dateisystem-Image verwenden.
- `build.ps1` schreibt nur die vier Bereiche aus der Tabelle oben und nie `spiffs`. Ohne `-Upload` oder mit `-WhatIf` öffnet es den seriellen Port nicht.
- Vor dem Flashen prüfen, dass das Image mit `epd13` erstellt wurde und tatsächlich `.pio\build\epd13\firmware.bin` ausgewählt ist. `build.ps1` prüft beides.

Weitere Gerätehinweise und die Beschreibung des Bootloaders stehen in [`README.md`](./README.md) unter „Build from source“, „Buttons“, „Certificates“ und „USB flashing“.

## Fehlerbehebung

Zuerst die Zusammenfassung am Ende der Ausgabe lesen. Sie nennt Ursache und Hinweise. Für Details das Log unter `.pio\logs` öffnen oder mit `-Verbose` wiederholen.

| Meldung oder Symptom | Ursache | Abhilfe |
| --- | --- | --- |
| „Die Ausführung von Skripts ist auf diesem System deaktiviert“ | PowerShell-Ausführungsrichtlinie | `powershell -ExecutionPolicy Bypass -File .\build.ps1` oder einmalig `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. Heruntergeladene Datei mit `Unblock-File .\build.ps1` freigeben. |
| Exit 2: „PlatformIO CLI nicht gefunden“ | PlatformIO Core nicht installiert oder nicht initialisiert | VS Code mit der PlatformIO-Erweiterung öffnen und die Installation abwarten |
| Exit 2: „Git nicht gefunden“ | Git fehlt im `PATH` | Git installieren, Terminal neu starten |
| Exit 2: „Ein anderer Lauf von build.ps1 … ist noch aktiv“ | Paralleler Lauf | Abwarten. Ohne laufenden Build `.pio\build-epd13.lock` löschen. |
| Exit 2: Build-Flag, Board oder Partitionstabelle falsch | `platformio.ini` verändert | `[env:epd13]` gegen die Tabelle „Zielhardware“ prüfen |
| Exit 3 mit `HTTPClientError`, `ConnectionError` o. ä. | Netzwerk beim Paket-Download | Das Skript versucht es bereits einmal erneut. Internetzugang, Proxy und Firewall prüfen. |
| Exit 3 mit `fatal error: …: No such file or directory` | Bibliothek unvollständig geladen | `.\build.ps1 -Clean`. Hilft das nicht, `.pio\libdeps\epd13` löschen und neu bauen. |
| Exit 3 mit `will not fit in region` | Firmware zu groß für `app0`/`app1` | Code verkleinern. Die Partitionstabelle nicht ändern, weil `spiffs` mit den Zertifikaten fest liegt. |
| Exit 3 mit `WinError 32` oder `Permission denied` | Datei durch anderen Prozess gesperrt | Parallele Builds, PlatformIO-IntelliSense oder Virenscanner prüfen |
| `*** WARNING: Windows Long Path Support is disabled ***` | Hinweis der Plattform, kein Fehler | Der Build läuft weiter. Optional als Administrator lange Pfade aktivieren. |
| Exit 4 | Image beschädigt, falscher Typ oder zu groß | `.\build.ps1 -Clean` |
| Warnung „Das Image ist älter als …“ bei `-VerifyOnly` | Quellen nach dem letzten Build geändert | Ohne `-VerifyOnly` bauen |
| Exit 5: „Port … nicht gefunden“ | Kabel, Treiber oder falscher Port | Datenkabel prüfen, CP210x-Treiber installieren, Port mit `-Port` angeben |
| Exit 5: „… gehört nicht zum Zielgerät“ | Port gehört zu einem anderen Gerät | Den in der Portliste angezeigten CP210x-Port angeben |
| Exit 5: „… ist von einem anderen Programm belegt“ | Port belegt | Serial Monitor, Web-Oberfläche und Terminalprogramme schließen |
| Exit 7 ohne serielle Ausgabe vom Gerät | Gerät schläft und Reset wurde nicht gedrückt, oder Kabel ohne Datenleitungen | Erneut starten und Reset drücken, sobald der Hinweis erscheint. Datenkabel prüfen. |
| Exit 7 nach Warnung „reagiert aber nicht auf 'B'“ | Firmware kennt das Kommando nicht oder erkennt keine USB-Versorgung | Boot-Knopf-Schritte oben ausführen, dann `.\build.ps1 -Upload -NoAutoBootloader` |
| Exit 6 mit `Failed to connect` oder `No serial data received` | Gerät hat den Bootloader vor dem Upload wieder verlassen | Erneut starten. Bei `-NoAutoBootloader` die Bootloader-Schritte oben wiederholen. |
| Exit 6 mit `PermissionError` oder „Zugriff verweigert“ | Port belegt | Serial Monitor, Web-Oberfläche und Terminalprogramme schließen |
| Upload erfolgreich, Display unverändert | Kein Reset nach dem Upload | Großen Reset-Knopf drücken und die serielle Ausgabe prüfen |

## Nicht erforderliche Abhängigkeiten

Die folgenden Abhängigkeiten sind nicht für `pio run -e epd13` erforderlich:

- Web-UI: Node.js/npm und Pakete aus `web/package.json`.
- HIL-Tests: Python-Pakete aus [`hil/requirements.txt`](./hil/requirements.txt), reale Testhardware und Testbench.
- Web-UI-Tests: Python-Pakete aus [`webtest/requirements.txt`](./webtest/requirements.txt) sowie Playwright/Chromium.

## Quellen

### Projektquellen

- [`platformio.ini`](./platformio.ini): PlatformIO-Plattform, Board, Framework, Bibliotheken, Build-Flags und Upload-Geschwindigkeit.
- [`build.ps1`](./build.ps1): empfohlener Build-, Prüf- und optionaler USB-Upload-Ablauf.
- [`part.csv`](./part.csv): Flash- und Partitionslayout.
- [`set_env.py`](./set_env.py): optionales Einlesen von `.env`-Definitionen.
- [`README.md`](./README.md): Hardwareanforderungen, Build-Befehle, Bootloader, Zertifikate und Web-Flasher.
- [`copilot-instructions.md`](./copilot-instructions.md): Projektbeschreibung und Hardwarekontext.
- [`src/main.cpp`](./src/main.cpp) und [`src/epaper_display.h`](./src/epaper_display.h): Displaytyp-Auswahl über `EPD_TYPE_13INCH`.
- [`web/src/DeviceBleInterface.js`](./web/src/DeviceBleInterface.js) und [`web/src/serialBoot.js`](./web/src/serialBoot.js): App-Image-Prüfung und USB-Bootloader-Ablauf in der Web-Oberfläche.
- [`web/package.json`](./web/package.json): optionale Web-UI-Abhängigkeiten.
- [`hil/requirements.txt`](./hil/requirements.txt) und [`webtest/requirements.txt`](./webtest/requirements.txt): optionale Testabhängigkeiten.
- Checkout-Revision beim Erstellen und Prüfen dieses Dokuments: `9bc585dd468f418c0253801af26ec03ed2993ec7`.

### Externe Quellen

- [paperlesspaper Offline Firmware – Upstream-Repository](https://github.com/paperlesspaper/paperlesspaper-firmware-offline)
- [Upstream-Buildanleitung](https://github.com/paperlesspaper/paperlesspaper-firmware-offline#build-from-source)
- [Upstream-README: Buttons](https://github.com/paperlesspaper/paperlesspaper-firmware-offline#buttons)
- [Upstream-README: Certificates](https://github.com/paperlesspaper/paperlesspaper-firmware-offline#certificates)
- [PlatformIO: Projektkonfiguration](https://docs.platformio.org/page/projectconf/index.html)
- [PlatformIO: Umgebungsvariablen](https://docs.platformio.org/page/envvars.html)
- [pioarduino ESP32-Plattform, Release 55.03.37](https://github.com/pioarduino/platform-espressif32/releases/tag/55.03.37)
- [esptool-Dokumentation](https://docs.espressif.com/projects/esptool/)
- [PlatformIO Registry: Adafruit GFX Library](https://registry.platformio.org/libraries/adafruit/Adafruit%20GFX%20Library)
- [PlatformIO Registry: ArduinoJson](https://registry.platformio.org/libraries/bblanchon/ArduinoJson)
- [PlatformIO Registry: U8g2 for Adafruit GFX](https://registry.platformio.org/libraries/olikraus/U8g2_for_Adafruit_GFX)
- [PlatformIO Registry: KXTJ3-1057](https://registry.platformio.org/libraries/ldab/KXTJ3-1057)
- [PlatformIO Registry: NimBLE-Arduino](https://registry.platformio.org/libraries/h2zero/NimBLE-Arduino)
- [PlatformIO Registry: QRCode](https://registry.platformio.org/libraries/ricmoo/QRCode)
- [PlatformIO Registry: JPEGDEC](https://registry.platformio.org/libraries/bitbank2/JPEGDEC)
- [PlatformIO Registry: SdFat](https://registry.platformio.org/libraries/greiman/SdFat)
- [GxEPD2 Git-Repository](https://github.com/smarthomeagentur/GxEPD2)
- [SerialFlash Git-Repository](https://github.com/smarthomeagentur/SerialFlash)
