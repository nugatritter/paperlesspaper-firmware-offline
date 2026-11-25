# USB-Diagnose und Konfiguration

Eine grafische Oberfläche für diese Funktionen einschließlich Build und Flashen
bietet [Panel Studio](desktop/README.md). Unter Windows `desktop/start.cmd` starten.

Die Offline-Firmware bietet eine abfragbare Konsole über die USB-UART-Brücke:
**115200 Baud, 8 Datenbits, keine Parität, 1 Stoppbit, keine Flusssteuerung**.
Ein Terminal mit Zeilenversand verwenden. Auf diesem Rechner ist der bekannte Port `COM10`.

## Verbindung und Ablauf

1. USB anschließen, den seriellen Monitor öffnen und einmal Reset drücken.
2. Auf `[USB] Ready: ...` warten und innerhalb von 30 Sekunden `HELP` oder `DIAG` senden.
3. Pro Befehl eine Zeile senden; LF, CR und CRLF werden akzeptiert. Befehle sind großgeschrieben.
4. `RUN` beendet die Sitzung, startet den normalen Bildablauf und lässt das Gerät anschließend schlafen.

Bei USB-Versorgung öffnet die Firmware den Setup-Modus auch nach Software-Neustart
und Timer-Aufwachen. Zweimaliges schnelles Drücken von Reset überspringt ihn weiterhin.
Ohne Eingabe bleibt das bisherige Setup-Zeitfenster von 30 Sekunden bestehen.
Eine USB-Sitzung bleibt bis zu 10 Minuten nach dem letzten vollständigen Befehl offen.
Nach dieser Frist oder erkanntem Abziehen von USB geht es mit dem normalen Bildablauf weiter.
USB wird im Setup etwa alle 10 Sekunden geprüft.

Eine bestehende BLE-Verbindung muss zuerst getrennt werden. Während der USB-Sitzung
pausiert BLE-Advertising; BLE-Schreibzugriffe werden nicht angenommen.
Beim Download, Rendern und im Deep Sleep werden keine Konsolenbefehle verarbeitet.
Ein schlafendes Gerät mit Reset aufwecken. Serieller Empfang allein weckt es nicht.

Antworten haben das Format `[USB] {"protocol":1,"command":"DIAG","ok":true,...}`.
Jede JSON-Antwort steht in einer einzelnen Zeile. Bestehende Firmware-Logs und
lesbare USB-Statusmeldungen erscheinen weiterhin dazwischen. Automatisierte Clients
werten nur Zeilen mit dem Präfix `[USB] {` aus und warten vor dem nächsten Befehl auf
die Antwort. Eine fehlgeschlagene Anfrage enthält `ok:false` und `error`.
Es gibt kein Eingabe-Echo der Firmware. Lokales Terminal-Echo lässt sich separat abschalten.

## Befehle

| Befehl | Wirkung |
| --- | --- |
| `HELP` | Befehle, schreibbare Schlüssel, Zeilenlimit und Sitzungsfrist abfragen |
| `DIAG` | Umfangreiche Diagnose als JSON abfragen |
| `CONFIG GET` | Aktuelle Konfiguration abfragen; Passwortfelder nur als `...PasswordSet` |
| `CONFIG SET {…}` | Einstellungen vollständig prüfen und gemeinsam dauerhaft speichern |
| `WIFI CONNECT` | Verbindungsversuch mit den gespeicherten WLAN-Daten anfordern; sofortige Antwort `pending:true`, anschließend Ergebnis über Logs und `DIAG` |
| `RUN` | Setup verlassen, normalen Bildabruf/Renderablauf ausführen und schlafen |
| `FORCE REFRESH IMAGE` | Aktiven lokalen Bildslot vollständig neu zeichnen, ohne Bildserver oder Remote-Einstellungen abzurufen; anschließend schlafen |
| `REBOOT` | Nach Bestätigung über USB neu starten |
| `B` oder `b` | Bestehender Bootloader-Befehl; am Zeilenanfang sofort, auch ohne Enter |

`B`/`b` ist am Zeilenanfang für USB-Flasher reserviert. Innerhalb einer
Konfigurationszeile löst der Buchstabe keinen Neustart aus. Bei einer begonnenen
Zeile zuerst Enter senden, bevor der Bootloader-Befehl verwendet wird.
Zeilen dürfen höchstens 2048 Bytes ohne Zeilenende enthalten. Überlange Zeilen
und Zeilen mit ungültigen Steuerzeichen werden bis zum Zeilenende verworfen.
Backspace und Delete entfernen das letzte eingegebene Byte.

## Diagnoseumfang und Messgrenzen

| JSON-Bereich | Informationen |
| --- | --- |
| `firmware` | Version, Variante, Build-Zeit, SDK, Gerätekennung, aktiver App-Slot, Adresse, Slotkapazität und Programmgröße |
| `system` | Laufzeit seit Boot, ESP-Reset- und Aufwachcodes, klassifizierter Aufwachgrund, Chip/Revision, CPU-Takt, Chiptemperatur, Heap gesamt/frei/Minimum/größter Block, interner Flash, Batteriespannung, USB/Ladestatus, Schlafprognose und Fehlerfolge |
| `network` | WLAN-Status, MAC, bei Verbindung SSID/IP/Gateway/Netzmaske/DNS/RSSI/Kanal, anstehender Verbindungsversuch und BLE-Transferdaten |
| `display` | Physische Maße und Bildraster separat, Text-/Bildrotation, Quick-Refresh-Status, Versorgung, BUSY-Pegel, gespeicherter Präsentationszustand, aktiver Bildslot und HTTP-Validatoren |
| `storageAtBoot` | Initialisierungsergebnisse, SPIFFS-Belegung, SerialFlash-ID/Kapazität/Löschblock sowie Adressen und reservierte Größen der drei Bild-/Downloadslots |
| `nvs` | Aktuelle belegte, freie und gesamte NVS-Einträge, falls verfügbar |
| `lastCompletedUpdate` | Letzter vollständig durchlaufener Bildzyklus: Download-/Renderergebnis, HTTP-Code, empfangene Bytes und Dauer beider Phasen |
| `render` | Dauerhafter Renderstatus, letzter Versuch und Zustand beim Boot, erforderliche Wiederherstellung, Speicherfehler sowie vor dem Rendern und während der Wartephasen gemessene Batteriespannung |
| `config` | Aktuelle Einstellungen wie bei `CONFIG GET` |

Die Chiptemperatur ist keine Messung der Panel- oder Raumtemperatur. Batteriespannung,
USB- und Ladestatus stammen aus den vorhandenen Messungen beim Start beziehungsweise
der periodischen Setup-Aktualisierung. `sleepPredictionSeconds` wird vor dem
normalen Bildablauf neu berechnet; direkt nach einer Konfigurationsänderung kann
dieser Wert noch die vorherige Prognose sein.

Die Speicherübersicht wird beim Boot bei freigegebenem SPI-Bus aufgenommen. Sie liest
bei `DIAG` keinen Flash parallel zu Display- oder BLE-Transfers. `imageMarkerValid`
ist die bestehende Slot-Markerprüfung, keine vollständige CRC-Prüfung. Dateigrößen
sind reservierte Slotgrößen, nicht zwingend die zuletzt empfangene Nutzdatenmenge.

`lastCompletedUpdate.valid:false` bedeutet, dass kein erhaltener Messsatz vorliegt.
Der Messsatz liegt im RTC-RAM und überlebt Deep Sleep; nach Stromverlust und
anderen Reset-Arten ist seine Erhaltung nicht zugesichert. Abgebrochene Zyklen
ersetzen keinen abgeschlossenen Messsatz. Der HTTP-Code `0` bedeutet, dass in
diesem Zyklus kein Bild-GET ausgeführt wurde. Negative HTTP-Werte sind
HTTPClient-Transportfehler. Download-Ergebnisse verwenden die vorhandenen
`DL_*`-Codes (`0` erfolgreich, `1` unverändert, negative Werte Fehler).
Die Renderdauer umfasst auch Wartezeiten; sie misst nicht ausschließlich die Panelwellenform.

Für epd13 bleiben physische Landschaftsmaße **1600 × 1200** und Bildraster
**1200 × 1600** getrennt. BUSY und gespeicherter Präsentationszustand sind
Software-/GPIO-Informationen; die sichtbaren Pixel werden nicht zurückgelesen.

`system.resetReasonName` erklärt den SDK-Resetcode, etwa `BROWNOUT`, `POWERON`,
`TASK_WATCHDOG` oder `SOFTWARE`. `POWERON` unterscheidet einen Tastendruck am
Reset-Pin nicht zuverlässig von einer Unterbrechung der Versorgung. Daher lautet
die entsprechende Aufwachklassifikation jetzt `power-on-or-reset-pin`, nicht `button`.
Der ESP32-C6 hat einen Kern; der Bootlog gibt nur dessen ROM-Resetgrund aus.

Der Renderstatus wird in einem 28-Byte-Datensatz ab EEPROM-Adresse 1340 gespeichert.
Er überlebt auch einen Verlust des RTC-RAMs. `preparing`, `streaming` und `refreshing`
sind unvollständige Phasen. Erst nach erfolgreicher BUSY-Prüfung werden `complete`
und die abgeschlossene Präsentation gemeinsam gespeichert. `failed` bleibt
wiederholbar. Beim nächsten regulären Bildablauf erzwingt ein unvollständiger
Datensatz auch nach HTTP 304 einen vollständigen Neuaufbau. Eine bloße Reparatur
des Overlay-Fensters reicht nach einem abgebrochenen Vollbild-Refresh nicht aus.
Bei unerreichbarem Server wird vor einem Fehleroverlay zunächst das gespeicherte
Vollbild wiederhergestellt, sofern dessen letzter Render unvollständig war.

`render.atBoot` ist der beim Start vorgefundene Datensatz; `render.lastAttempt`
zeigt den aktuellen beziehungsweise letzten Versuch. `interruptedAtBoot` bedeutet,
dass beim Start ein begonnener Versuch ohne Abschluss vorlag. Es benennt nicht
die Resetursache. `elapsedMsAtCheckpoint` ist die Zeit bis zum gespeicherten
Zwischenstand und nicht die genaue Zeit bis zu einem späteren Stromverlust.

Während der BUSY-Wartephasen wird etwa jede Sekunde die Batteriespannung gemessen.
`[EPD] Render waiting` erscheint bei einem BUSY-Pegelwechsel, einer Spannungsänderung
von mindestens 500 mV gegenüber der letzten Meldung oder nach zehn Sekunden ohne
Meldung. Sie enthält Phase, Laufzeit, BUSY-Pegel, Batteriespannung und Messminimum.
Die Messungen erfassen die Batterie über den vorhandenen ADC, nicht die interne
3,3-V-Versorgung. Kurze Einbrüche zwischen den Stichproben bleiben unentdeckt.
Einzelne Messwerte werden nicht laufend ins EEPROM geschrieben; nach einem Reset
enthält der Datensatz nur die Werte des letzten gespeicherten Zwischenstands.

Im Setup erscheint `[BAT]` beim ersten Messwert und danach erst ab einer Änderung
von 500 mV gegenüber dem zuletzt gemeldeten Wert. Lade- und LED-Status werden nur
bei Änderungen ausgegeben. Die Messungen und die Fehlerausgaben bleiben aktiv;
manuelles `DIAG` liefert weiterhin den vollständigen aktuellen Datensatz.

Während des Bildaufbaus pausiert das Laden und die Status-LED ist aus. Nach dem
Versuch wird die gespeicherte Ladeeinstellung wieder angewendet. Der Failsafe
erhält vor jedem Render ein neues Zeitbudget, damit vorherige Download-Retries
keinen laufenden Refresh wegen Zeitablaufs abschalten.

## Konfigurierbare Werte

Nicht angegebene Werte bleiben erhalten. Unbekannte Schlüssel, falsche Typen,
überlange Strings, Steuerzeichen und Daten hinter dem JSON-Objekt führen zur
Ablehnung der gesamten Anfrage. Strings werden nach UTF-8-Bytes begrenzt.

| Schlüssel | Werte |
| --- | --- |
| `wifiSsid` | String, höchstens 32 Bytes; leer löscht den Netzwerknamen |
| `wifiPassword` | String, höchstens 64 Bytes; leer für offenes WLAN |
| `downloadUrl`, `settingsUrl` | String, höchstens 128 Bytes; `http://` oder `https://` mit Host, oder leer |
| `httpAuthUser`, `httpAuthPassword` | String, höchstens 128 Bytes; leer löscht den Wert |
| `timeout` | Ganze Sekunden von 60 bis 2592000 |
| `imageMode` | `0`: gespeichertes BLE-Bild; `1`: URL-Abruf |
| `autoRotation` | `true` / `false` |
| `manualOrientation` | `0`: bisherige Standardlage; `1`: gegenüberliegende Landschaftslage (180°), wirksam bei `autoRotation:false` |
| `motionWakeup` | `true` / `false` |
| `showBatteryWarning`, `showWifiWarning` | `true` / `false` |
| `requireImageDigest` | `true` / `false`; vorhandene Download-Integritätsprüfung |
| `chargerMode` | `true` / `false`; Aktivierung erfordert zusätzlich `confirmRechargeable:true` in derselben Anfrage |
| `confirmRechargeable` | Explizite Bestätigung eingelegter wiederaufladbarer Akkus; wird nicht gespeichert |

Eine nichtleere `downloadUrl` wählt URL-Modus, sofern dieselbe Anfrage nicht
ausdrücklich `imageMode` setzt. URL-/HTTP-Zugangsdatenänderungen verwerfen die
zugehörigen HTTP-Validatoren. Orientierungsänderungen verwerfen den Bildvalidator
und erzwingen beim nächsten Bildablauf eine Aktualisierung.

`CONFIG SET` speichert WLAN-Daten und Einstellungen mit einem gemeinsamen
EEPROM-Commit. Bei gemeldetem Speicherfehler werden die RAM-Werte zurückgesetzt.
WLAN-Zugangsdaten werden auch ohne erfolgreiche Verbindung gespeichert.
Bei Änderung wird eine bestehende WLAN-Verbindung getrennt; `WIFI CONNECT` prüft
die neuen Daten. `RUN` verwendet sie ebenfalls beim nächsten Abruf.
Eine konfigurierte Remote-Settings-URL kann beim nächsten Abruf Einstellungen
wieder überschreiben. Ein leerer `settingsUrl` beendet diese Fernkonfiguration.

Lademodusänderungen wirken unmittelbar. Anzeigeänderungen werden durch `RUN`
angewendet. Die manuelle Orientierung nutzt die bestehenden Rotationsfunktionen;
Paneltyp, Rastergeometrie und Refresh-Wellenformen sind nicht frei konfigurierbar.
Die zusätzliche Orientierung wird ab EEPROM-Adresse 1328 gespeichert; ältere
Speicherstände erhalten die Standardlage, sofern dort nicht genau `1` steht.

WLAN- und HTTP-Passwörter werden nicht in Konsolenantworten ausgegeben.
SSID, HTTP-Benutzername und URLs werden vollständig zurückgegeben; URLs können
selbst Zugangstoken enthalten. Diagnoseausgaben entsprechend behandeln.

## Beispiele

```text
DIAG
CONFIG GET
CONFIG SET {"wifiSsid":"MyNetwork","wifiPassword":"MyPassword","downloadUrl":"http://192.168.1.20/panel.bmp","timeout":900}
WIFI CONNECT
DIAG
CONFIG SET {"autoRotation":false,"manualOrientation":1}
RUN
```

Die zweite `DIAG`-Abfrage erst nach Abschluss des WLAN-Versuchs senden
(maximal etwa 10 Sekunden, siehe WLAN-Log).

```text
CONFIG SET {"settingsUrl":"","motionWakeup":false,"requireImageDigest":true}
CONFIG SET {"chargerMode":true,"confirmRechargeable":true}
```

Den letzten Befehl ausschließlich mit dafür geeigneten wiederaufladbaren Akkus verwenden.

## Entwicklerprüfung

Parser und Konfigurationsvalidierung lassen sich ohne angeschlossenes Gerät prüfen:

```text
pio run -e epd13
python tests/run_serial_console_host.py
```

Unter Windows ersetzt `.\build.ps1` den ersten Befehl. Der Hosttest läuft unter Windows,
Linux und macOS. Er benötigt einen C++17-Compiler (`g++` oder `clang++`, alternativ über
`CXX` gesetzt) und die vom epd13-Build installierte ArduinoJson-Bibliothek.
Am Gerät sind anschließend USB-Einstieg/Timeout, Speichern über Neustarts,
WLAN-Verbindung, beide manuellen Landschaftslagen mit Overlays und die bestehende
USB-Bootloader-Umschaltung zu prüfen. Die Overlay-Prüfpunkte in
[IMAGE_UPDATE_BASELINE.md](IMAGE_UPDATE_BASELINE.md) gelten weiterhin.


## UTC-Zeit im verwalteten Build

`CLOCK SET <Unix-Sekunden>` übernimmt die Uhrzeit des vertrauenswürdigen Werkstattrechners bei anliegender USB-Spannung. Panel Studio führt den Abgleich bei der Einrichtung eines Gerätekontos automatisch aus, wenn die Diagnose `firmware.clockTrusted=false` meldet. Für ein bereits eingerichtetes Gerät gibt es im Werkstattfenster die Aktion **Werkstattzeit über USB übertragen**. Nach dem Abgleich enthält die Diagnose den bestätigten Zustand und `firmware.utcEpoch`.

Die Zeitbestätigung liegt im RTC-Speicher und übersteht den regulären Tiefschlaf. Nach Verlust der Bestätigung wartet der verwaltete HTTPS-Client auf einen neuen Zeitabgleich, bevor er Anmeldedaten überträgt. Eine rückwärts gerichtete Uhrkorrektur wird abgelehnt. Bis zu drei Sekunden Übertragungslatenz werden quittiert, ohne die Uhr zurückzustellen. Der Werkstattrechner muss die richtige UTC-Zeit haben.
