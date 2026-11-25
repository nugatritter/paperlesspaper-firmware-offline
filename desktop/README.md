# eYellowBoard Panel Studio

Deutschsprachige Python-Desktop-GUI für die USB-Konsole der Offline-Firmware.
Die Oberfläche verwendet Qt/PySide6. Serielle Ein-/Ausgabe läuft in einem eigenen
Thread; Build und Flashen laufen in einem eigenen Python-Prozess direkt über
PlatformIO Core und esptool. Dafür wird keine PowerShell benötigt.

## Start unter Windows

**`desktop/start.cmd` doppelklicken.**

Beim ersten Start legt das Startskript eine Python-Umgebung unter `desktop/.venv`
an und installiert die Pakete aus `requirements.txt`. Es verwendet eine über den
Python-Launcher `py` verfügbare Python-Installation, ersatzweise die vorhandene
PlatformIO-Python-Installation. Erforderlich ist Python **3.10 oder neuer**.
Für die erstmalige Paketinstallation wird Internet benötigt.

Das Programm startet anschließend ohne zusätzliche Konsole. Für Fehlersuche:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\desktop\start.ps1 -Console
```

Alternativ manuell, aus dem Verzeichnis `desktop`:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

Bei einer vorhandenen Installation das Startskript erneut ausführen; es installiert
die zusätzlich benötigten Python-Pakete `platformio` und `esptool` in derselben Umgebung.

## Start unter Linux und macOS

Aus dem Repository-Verzeichnis:

```bash
bash desktop/start.sh
# Ohne Panel testen:
bash desktop/start.sh --demo
```

Das Startskript verwendet `python3`, legt `desktop/.venv` an und installiert die
Abhängigkeiten. Erforderlich sind Python **3.10 oder neuer**, dessen `venv`-Modul,
eine grafische Desktop-Sitzung und für den Firmware-Build Git im `PATH`.
Qt benötigt unter Linux die zur Distribution passenden grafischen Systembibliotheken.
Nur die Installation ausführen: `bash desktop/start.sh --install-only`.
Eine virtuelle Umgebung beim Wechsel des Betriebssystems neu anlegen.

Typische Ports sind `/dev/ttyUSB0` bzw. `/dev/ttyACM0` unter Linux und
`/dev/cu.usbserial-…` unter macOS. Unter Linux braucht der Benutzer Schreibrechte
auf das Gerät, häufig über die Gruppe `dialout` (distributionsabhängig; nach einer
Gruppenänderung neu anmelden). Die GUI nicht als root starten. Bei fehlendem
USB-Port die CP210x-Treiber und das Datenkabel prüfen.

Am vorhandenen Mac wurde das Panel als **CP2102N** mit USB-ID **`10C4:EA60`**
und Port **`/dev/cu.usbserial-10`** erkannt. Laut Geräteausgabe ist Apples integrierter
DriverKit-Treiber `AppleUSBSLCOM` (`com.apple.DriverKit-AppleUSBSLCOM`) aktiv.
Auf diesem Mac ist somit kein zusätzlicher Silicon-Labs-Treiber erforderlich.
In der GUI diesen Port auswählen; er wird anhand der USB-ID als Panelkandidat markiert.
Die Portnummer kann sich auch beim Wechsel vom USB-Hub zum direkten Mac-Anschluss
ändern. Bei „No such file or directory“ **Ports suchen**, den aktuell gefundenen
Panel-Port auswählen und **Verbinden** klicken. Beim Start und bei **Ports suchen**
wählt die GUI einen einzelnen erkannten Panelkandidaten vor, wenn der bisherige Port
nicht mehr vorhanden ist. Sind mehrere Kandidaten angeschlossen, bleibt die Auswahl
beim Benutzer. Diese Geräteerkennung bestätigt
noch keinen vollständigen Build-/Flash-Test unter macOS.

Die GUI ist für die Ausführung aus diesem Repository vorgesehen. Alle drei
Betriebssysteme verwenden denselben Python-Ablauf und `.pio/build/epd13/firmware.bin`.
Unter Windows wurden Prozessanbindung, Imageprüfung und Build geprüft.
Native Linux-/macOS-Läufe und eine reale Übertragung mit dem neuen Ablauf stehen
noch aus; simulierte Tests decken auch die dort verwendeten Portnamen ab.

## Mit einem Panel arbeiten

1. Andere Programme schließen, die den seriellen Port geöffnet haben, etwa den
   seriellen Monitor in VS Code oder einen Browser-Flasher.
2. USB-Datenkabel anschließen. In Panel Studio den Port wählen, hier üblicherweise
   **COM10**. CP210x-/ESP32-USB-Geräte werden als mögliche Panel-Ports markiert;
   diese Erkennung ersetzt nicht die Auswahl des richtigen Geräts.
3. **Verbinden** startet das passive Mithören. Ab der nächsten Panelmeldung zeigt
   die Konsole die empfangenen Zeilen. USB kann über mehrere Bildzyklen verbunden bleiben.
4. Für Messwerte im Überblick **Jetzt abfragen** wählen, für Einstellungen
   **Neu auslesen**. Ein schlafendes Panel beim nächsten Aufwachen abfragen
   oder bei Bedarf den großen Reset-Knopf drücken. Diese Befehle benötigen
   die [USB-Konsole](../USB_CONSOLE.md).

**Bildzyklen live verfolgen** sendet beim Verbinden, beim Aufwachen und während
der Wartezeit keine Befehle. Bei USB-Versorgung folgt auf das Timer-Aufwachen
das reguläre Setup-Fenster von etwa 30 Sekunden. Die Statuszeile folgt den Meldungen zum Aufwachen,
Bildabruf, Bildaufbau und Schlaf. Bis zur ersten Schlafmeldung zeigt Studio nach
dem ersten Empfang dessen Uhrzeit. Eine manuelle Diagnose öffnet die USB-Sitzung.
Mit **Bild aktualisieren und schlafen** lässt sich die Sitzung sofort beenden.
**Forced refresh image** rendert das lokal gespeicherte Bild vollständig neu, ohne
den Bildserver oder Remote-Einstellungen abzufragen. Dafür muss ein gültiges Bild
im Panel gespeichert sein.
Im Deep Sleep kann die GUI das Gerät nicht per UART aufwecken; dazu Reset drücken.
Eine bestehende BLE-Verbindung vor der USB-Nutzung trennen.

Es wird immer nur ein Konsolenbefehl gleichzeitig gesendet. Nach `WIFI CONNECT`
wartet die GUI 12 Sekunden auf den Verbindungsversuch und fragt dann die Diagnose
ab. `RUN` und `FORCE REFRESH IMAGE` starten den Bildablauf.
Panel Studio zeigt dabei „Bildaufbau läuft“; erst die Schlafmeldung meldet den Schlafzustand.
Ein Bootbanner während eines laufenden Bildablaufs wird als Neustart mit fehlender
Abschlussbestätigung gemeldet. Ein USB-Abbruch allein bedeutet, dass der Abschluss
unbekannt ist; das Panel kann noch arbeiten.
Bei einer fehlenden Speicherbestätigung wird `CONFIG SET` nicht automatisch
wiederholt: zuerst mit **Neu auslesen** prüfen, welche Werte gespeichert wurden.

Unter dem Verbindungsstatus zeigt **Nächster Bildzyklus** eine geschätzte Uhrzeit
mit Countdown. Grundlage ist die empfangene Meldung `Going to Sleep for … seconds`,
also die tatsächlich angekündigte Schlafdauer einschließlich Fehler- oder Servervorgaben.
Das konfigurierte Intervall allein startet keinen Countdown. Die Schätzung betrifft
das Timer-Aufwachen; WLAN, Download und Wiederholungen können den sichtbaren Refresh
verzögern, bei unverändertem Bild kann er entfallen. Bewegung und Reset können früher
aufwecken. Bei USB-Trennung bleibt die Schätzung als unbestätigt sichtbar. Nach Ablauf
wartet Studio auf eine Startmeldung, statt einen erfolgreichen Start zu behaupten.
Eine neue Verbindung oder ein beobachteter Neustart verwirft die alte Schätzung.
Ohne Timer oder bei Soft Sleep wird kein automatischer Start angekündigt. Die Anzeige
aktualisiert sich lokal ohne zusätzliche USB-Abfragen oder Konsolenmeldungen.

## Überblick

- Die Kachel **Versorgung** zeigt beim Mithören die zuletzt gemeldete Spannung mit
  Empfangszeit, den Ladezustand und bis zu drei Spannungsmessungen beim Aufwachen.
  Während des Bildaufbaus aktualisieren Messungen unter Last den aktuellen Wert.
  Der Aufwachverlauf bleibt separat. Im Schlaf bleiben die letzten Werte sichtbar.
  Eine neue Verbindung beginnt einen neuen Verlauf. Eine manuelle Diagnose ergänzt
  den USB-Status. Die Firmware meldet keine verbleibende Akkukapazität in Prozent.
- Geräte-, WLAN- und Heap-Anzeigen stammen aus der letzten Diagnose.
- Lesbarer Resetgrund und dauerhafter Renderstatus direkt im Überblick. `POWERON`
  wird als mehrdeutig erklärt; ein unterbrochener Refresh bleibt nach Neustart sichtbar.
- Vollständige Diagnose als durchsuchbarer Baum und als formatiertes JSON.
- JSON-Export einschließlich Firmware-, Netzwerk-, Speicher- und Displaydaten.
- Anzeige des letzten im RTC-RAM erhaltenen Bildzyklus, wenn verfügbar.

Angezeigte Daten gehören zur letzten erfolgreichen Abfrage. Beim Verbindungsabbruch
bleiben sie zum Nachlesen erhalten; der Verbindungsstatus zeigt den Abbruch an.
Eine neue Verbindung leert die bisherigen Gerätedaten. Die Messgrenzen sind in
[USB_CONSOLE.md](../USB_CONSOLE.md) beschrieben.

## Einstellungen

Das Formular unterstützt sämtliche schreibbaren Konsolenwerte:

- WLAN-Name und Passwort, Bild-URL, Remote-Settings-URL und HTTP-Zugangsdaten.
- Bildquelle, Aktualisierungsintervall, automatische oder manuelle Ausrichtung.
- Aufwachen durch Bewegung, Batterie-/Verbindungswarnungen, Digest-Pflicht und Lademodus.

**Änderungen speichern** zeigt vor dem Übertragen die betroffenen Werte und
prüft Datentypen, Wertebereiche und UTF-8-Längen. Die GUI sendet nur Änderungen.
Passwörter haben drei ausdrückliche Modi:

| Modus | Wirkung |
| --- | --- |
| Beibehalten | Passwort wird nicht mitgeschickt |
| Ersetzen | Eingegebenes Passwort wird gespeichert |
| Löschen | Leeres Passwort wird gespeichert |

Die Firmware gibt gespeicherte Passwörter nicht zurück. Beim Aktivieren des
Lademodus muss im Speicherdialog bestätigt werden, dass geeignete wiederaufladbare
Akkus eingelegt sind. Diese Bestätigung kann nicht aus einer Datei importiert werden.

Diagnoseabfragen überschreiben keine ungespeicherten Formularänderungen. Während
`CONFIG SET` auf seine Antwort wartet, ist das Formular vor weiteren Eingaben geschützt.
**Neu auslesen** erlaubt das ausdrückliche Verwerfen lokaler Änderungen.

Importierte JSON-Werte werden zunächst nur ins Formular übernommen. Als Eingabe
sind ein Konfigurationsobjekt und ein Diagnoseexport mit `config`-Objekt möglich.
Der Konfigurationsexport enthält keine WLAN-/HTTP-Passwörter. SSID, Benutzername
und URLs bleiben enthalten; URLs können selbst Zugangstoken enthalten.

Nach dem Speichern kann **WLAN verbinden** die Zugangsdaten prüfen.
**Bild aktualisieren und schlafen** startet den normalen Bildablauf mit den
gespeicherten Einstellungen. Bei unverändertem Serverbild wird der bestehende
Bild-Refresh übersprungen. **Forced refresh image** baut stattdessen das lokal
gespeicherte Bild neu auf und funktioniert auch ohne Serververbindung. Eine
Remote-Settings-URL kann beim normalen Bildablauf lokale Einstellungen wieder
überschreiben.

## Firmware bauen, prüfen und flashen

Der Firmwarebereich ist auf das **13,3-Zoll-Panel (`epd13`, ESP32-C6)** und die
Projekt-Firmware ausgelegt. Er zeigt Pfad, Änderungszeit, Größe, SHA-256 und
Partitionsbelegung des vorhandenen Images.

| Aktion | Direkter Ablauf |
| --- | --- |
| Firmware bauen | `python -m platformio run --project-dir … --environment epd13`, anschließend Imageprüfung |
| Image prüfen | Python-Prüfung aller Flashdateien plus `python -m esptool --chip esp32c6 image-info …` für App und Bootloader |
| Auf Panel flashen | Imageprüfung, Portprüfung, ROM-Bootloader-Abfrage, anschließend `python -m esptool … write-flash …` |

Das Flashen verwendet das bestehende Image **ohne erneuten Build**. Vor der
Bestätigung zeigt die GUI das Zielgerät, den Imagepfad und den SHA-256 an.
Der Python-Ablauf prüft anschließend Konfiguration, ESP32-C6-Header, Imagegrößen,
Segment-Prüfsummen, angehängte SHA-256-Hashes sowie das feste Partitionslayout und
dessen MD5-Prüfsumme. Die App muss dem in der GUI bestätigten SHA-256 entsprechen.
Für die Übertragung werden geprüfte Kopien aller vier Dateien erstellt und vor
dem Schreiben erneut auf Veränderungen geprüft.

Geschrieben werden ausschließlich Bootloader bei `0x0`, Partitionstabelle bei
`0x8000`, OTA-Daten bei `0xE000` und App bei `0x10000`. NVS, die zweite App-Partition,
SPIFFS mit den Gerätezertifikaten und Coredump werden nicht überschrieben.
Es wird kein vollständiger Flash-Erase durchgeführt. Vor dem Schreiben prüft
esptool den ESP32-C6; nach dem Schreiben müssen alle vier Hashprüfungen erfolgreich sein.
Details zur Hardware stehen in [BUILD.md](../BUILD.md).

PlatformIO lädt beim ersten Build die in `platformio.ini` festgelegten Compiler,
Frameworks und Bibliotheken. Die GUI verwendet die Tools aus `desktop/.venv`;
eine VS-Code-Installation ist nicht erforderlich. Vorhandene PlatformIO-Pakete
werden genutzt, auch bei einem über die PlatformIO-Konfiguration bzw.
`PLATFORMIO_CORE_DIR` angepassten Cache. Die Imageprüfung lädt keine Pakete nach.
Vollständige Ablaufprotokolle liegen unter `.pio/logs/panel-studio-*.log`.
Eine Projektsperre verhindert gleichzeitige GUI-/CLI-Läufe; unter Windows
berücksichtigt sie auch die Sperre des weiterhin verfügbaren `build.ps1`.
Die verbleibende Lockdatei ist normal und muss nicht gelöscht werden.

Der gleiche Ablauf ist ohne GUI nutzbar. Im Verzeichnis `desktop`, mit dem Python
aus dessen virtueller Umgebung (Windows: `.venv\Scripts\python.exe`, Unix: `.venv/bin/python`):

```bash
python -m panel_studio.firmware_cli build
python -m panel_studio.firmware_cli verify
python -m panel_studio.firmware_cli flash --port /dev/ttyUSB0 --baud 921600
```

`build` und `verify` öffnen keinen seriellen Port. `flash` programmiert das gewählte
Gerät; unter Windows beispielsweise `--port COM10` verwenden.
Optional: `--manual-bootloader`, `--bootloader-timeout 120`,
`--expected-sha256 <bestätigter App-Hash>`. Der CLI-Aufruf flasht direkt;
die Bestätigung des Zielgeräts erfolgt bei GUI-Nutzung im Dialog.

Die GUI schließt vor dem Flashen ihren seriellen Monitor, damit der Flasher
exklusiv auf den gewählten Port zugreifen kann. Fortschritt, Fehler und die
Aufforderung zum Reset erscheinen im Firmwarebereich und im gemeinsamen Log.
Wenn das Gerät schläft, bei Aufforderung den großen Reset-Knopf einmal drücken.
„Bereits im Bootloader“ ist für einen zuvor manuell aktivierten ROM-Bootloader gedacht.
Die Upload-Baudrate ist wählbar; Standard ist 921600, bis zu 2000000 ist einstellbar.

Nach erfolgreichem Flashen kann die GUI denselben Port automatisch wieder öffnen.
Falls der Frame danach nicht startet, einmal Reset drücken. Bei einem Fehler
wird nicht automatisch ein weiterer Flashversuch ausgeführt. Das Fenster lässt
sich während Build/Prüfung/Übertragung nicht schließen, damit kein laufender
Unterprozess zurückbleibt oder eine Übertragung versehentlich abgebrochen wird.

Das Programm flasht keine frei ausgewählten Fremd- oder Komplett-Images. Andere
Panelvarianten müssen einen passenden eigenen Build-/Flashablauf verwenden.
Ein per Diagnose erkanntes epd7 wird für den epd13-Upload gesperrt.

## Konsole und Protokoll

Alle Befehle sind erreichbar: `HELP`, `DIAG`, `CONFIG GET`, `CONFIG SET` über das
Formular, `WIFI CONNECT`, `RUN`, `REBOOT` und `B`.
`B` wird über die Konsole nur bei bereiter Firmware gesendet; der Firmwareflasher
übernimmt für schlafende oder ältere Geräte das Warten auf Reset und Bootloader.

Das Log kann nach Kategorie und Suchtext gefiltert und exportiert werden.
Es hält maximal 5000 Einträge. Gesendete `CONFIG SET`-Nutzdaten werden nicht
protokolliert. Empfangene Firmware-Logs und Diagnoseantworten werden unverändert
angezeigt und können SSIDs, URLs oder andere Informationen enthalten.
Panel Studio speichert den gewählten Port und die Upload-Baudrate als Anwendungseinstellungen.

## Vorschau und Entwicklung

Vorschau mit ausdrücklich als Demo gekennzeichneten Beispieldaten, ohne USB-Zugriff:

```powershell
.\.venv\Scripts\python.exe run.py --demo
```

PNG-Vorschauen aller vier Seiten ohne sichtbares Fenster:

```powershell
.\.venv\Scripts\python.exe run.py --preview test-output/preview
```

Tests ohne angeschlossenes Panel:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Die Tests prüfen Protokollparser, UTF-8-Grenzen, Konfigurationsvalidierung,
Passwortbehandlung, Formularzustand, simulierten seriellen Empfang, Timeouts,
Kabelverlust, WLAN-Wartephase und Freigabe des Ports vor dem Flashen. Die
Python-Prozessanbindung wird mit echten, temporären Testprozessen geprüft, die
keine Hardware ansprechen. Weitere Tests prüfen Imagebeschädigungen, Partitionslayout,
unveränderte Flashkopien, Bootloader-Portfreigabe und Fehler ohne erneuten Flashlauf.
Die Vorschauen dienen der Layoutkontrolle.
Eine tatsächliche Übertragung auf das Panel und dessen anschließendes Verhalten
müssen gesondert am Gerät geprüft werden.

| Datei | Aufgabe |
| --- | --- |
| `run.py` | Einstiegspunkt, Demo und PNG-Vorschau |
| `panel_studio/app.py` | Hauptfenster und Benutzerabläufe |
| `panel_studio/widgets.py` | Diagnose, Konfigurationsformular und Log |
| `panel_studio/protocol.py` | Parser und Konfigurationsregeln ohne GUI-Abhängigkeit |
| `panel_studio/transport.py` | Serieller Thread und Befehlszustände |
| `panel_studio/firmware.py` | Asynchroner Python-Prozess und GUI-Fortschritt |
| `panel_studio/firmware_cli.py` | PlatformIO, esptool, Bootloader und Ablaufprotokoll |
| `panel_studio/firmware_core.py` | Image-, Partitions- und Flashplanprüfung ohne Qt |

Verwendete APIs: [Qt for Python](https://doc.qt.io/qtforpython-6/),
[pySerial](https://pyserial.readthedocs.io/en/latest/pyserial_api.html),
[PlatformIO](https://docs.platformio.org/en/latest/core/userguide/cmd_run.html),
[esptool](https://docs.espressif.com/projects/esptool/en/latest/esp32c6/esptool/basic-commands.html).

## Werkstatt

Auf der Seite „Werkstatt“ die HTTPS-Basisadresse der Verwaltung und das Werkstattkonto eingeben. CSV-Dateien verwenden die Spalten `beamline,location,model`. JSON-Dateien enthalten dieselben Einträge im Array `orders`. Modelle sind `epd7` oder `epd13`. Die Vorschau zeigt je Beamline den Standort, das Modell, den Abgleichstatus und eine bestehende Belegung. „Vorschau übernehmen“ bestätigt den Import für diese Sitzung.

Das QR-Etikett liefert die öffentliche Panel-ID. „USB-Gerät inventarisieren“ und „Gerät reservieren“ lesen die aktuelle Gerätekennung und den Paneltyp mit einer neuen USB-Diagnose. Nach einem Kabelwechsel dieselbe Arbeitsliste öffnen, das Etikett erneut scannen und die Reservierung mit demselben Werkstattkonto wieder aufnehmen. Am Montageort die tatsächliche Standortangabe und den sechsstelligen Code vom Prüfschild eingeben. Bei einem Ersatzgerät wird mit der Aktivierung das vorherige Gerät gesperrt. Die Werkstattanmeldung bleibt nur im Arbeitsspeicher.

„Gerätekonto einrichten“ gleicht zunächst die Reservierung und den von der verwalteten Firmware gemeldeten HTTPS-Ursprung ab. Unmittelbar vor dem Schreiben liest Panel Studio die Gerätekennung nochmals über USB. Das einmalige Passwort geht mit Bild- und Einstellungs-URL direkt in den Konfigurationsbefehl. Bei einer vorhandenen Berechtigung kann ein Zweitschlüssel übertragen werden; die anschließende Bestätigung nach erfolgreichem Geräteabruf erfolgt über die Schlüsselverwaltung. Ein Verbindungsabbruch verwirft die ausstehende lokale Übergabe.


Verwaltete Panels können ihre UTC-Zeit über den physisch geschützten Werkstattport beziehen. Bei der Einrichtung oder Rotation eines Gerätekontos gleicht Panel Studio eine als unbestätigt gemeldete Uhr automatisch ab und liest den Zustand vor dem nächsten Schritt erneut aus. Für ein bereits eingerichtetes Gerät die Funktion **Werkstattzeit über USB übertragen** verwenden. Der Werkstattrechner benötigt die richtige Systemzeit.
