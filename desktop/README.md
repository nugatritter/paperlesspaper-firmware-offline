# eYellowBoard Panel Studio

Deutschsprachige Python-Desktop-GUI für die USB-Konsole der Offline-Firmware.
Die Oberfläche verwendet Qt/PySide6. Serielle Ein-/Ausgabe läuft in einem eigenen
Thread; Build und Flashen laufen als asynchroner PowerShell-Prozess.

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

Die GUI ist für die Ausführung aus diesem Repository vorgesehen. Der
Firmwarebereich verwendet dessen `build.ps1` und `.pio/build/epd13/firmware.bin`.
Build und Flashen sind unter Windows verfügbar. Die serielle GUI kann auch
unter Linux/macOS mit Python und denselben Paketen gestartet werden; diese
Plattformen wurden hier nicht geprüft.

## Mit einem Panel arbeiten

1. Andere Programme schließen, die den COM-Port geöffnet haben, etwa den
   seriellen Monitor in VS Code oder einen Browser-Flasher.
2. USB-Datenkabel anschließen. In Panel Studio den Port wählen, hier üblicherweise
   **COM10**. CP210x-/ESP32-USB-Geräte werden als mögliche Panel-Ports markiert;
   diese Erkennung ersetzt nicht die Auswahl des richtigen Geräts.
3. **Verbinden** und bei Bedarf einmal den großen Reset-Knopf drücken.
4. Die GUI fragt `DIAG` ab und erkennt die Meldung `[USB] Ready` nach dem Start.
   Voraussetzung für Diagnose und Einstellungen ist die Firmware mit der
   [USB-Konsole](../USB_CONSOLE.md). Eine ältere Firmware kann bereits über den
   Firmwarebereich aktualisiert werden, auch wenn die Diagnose noch nicht antwortet.

„Live-Diagnose · 15 s“ fragt das bereite Panel regelmäßig ab und hält dadurch die
Setup-Sitzung offen. Zum Batteriesparen **Bild aktualisieren und schlafen** wählen.
Im Deep Sleep kann die GUI das Gerät nicht per UART aufwecken; dazu Reset drücken.
Eine bestehende BLE-Verbindung vor der USB-Nutzung trennen.

Es wird immer nur ein Konsolenbefehl gleichzeitig gesendet. Nach `WIFI CONNECT`
wartet die GUI 12 Sekunden auf den Verbindungsversuch und fragt dann die Diagnose
ab. `RUN` beendet die automatische Abfrage, bis die Firmware erneut bereit ist.
Bei einer fehlenden Speicherbestätigung wird `CONFIG SET` nicht automatisch
wiederholt: zuerst mit **Neu auslesen** prüfen, welche Werte gespeichert wurden.

## Überblick

- Geräte-, Spannungs-, WLAN- und Heap-Anzeigen mit Zeit der letzten Abfrage.
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

Live-Diagnosen überschreiben keine ungespeicherten Formularänderungen. Während
`CONFIG SET` auf seine Antwort wartet, ist das Formular vor weiteren Eingaben geschützt.
**Neu auslesen** erlaubt das ausdrückliche Verwerfen lokaler Änderungen.

Importierte JSON-Werte werden zunächst nur ins Formular übernommen. Als Eingabe
sind ein Konfigurationsobjekt und ein Diagnoseexport mit `config`-Objekt möglich.
Der Konfigurationsexport enthält keine WLAN-/HTTP-Passwörter. SSID, Benutzername
und URLs bleiben enthalten; URLs können selbst Zugangstoken enthalten.

Nach dem Speichern kann **WLAN verbinden** die Zugangsdaten prüfen.
**Bild aktualisieren und schlafen** startet den normalen Bildablauf mit den
gespeicherten Einstellungen. Eine Remote-Settings-URL kann beim nächsten Abruf
lokale Einstellungen wieder überschreiben.

## Firmware bauen, prüfen und flashen

Der Firmwarebereich ist auf das **13,3-Zoll-Panel (`epd13`, ESP32-C6)** und die
Projekt-Firmware ausgelegt. Er zeigt Pfad, Änderungszeit, Größe, SHA-256 und
Partitionsbelegung des vorhandenen Images.

| Aktion | Aufruf des vorhandenen Build-Skripts |
| --- | --- |
| Firmware bauen | `build.ps1` |
| Image prüfen | `build.ps1 -VerifyOnly` |
| Auf Panel flashen | `build.ps1 -VerifyOnly -Upload -Port COM… -UploadBaud … -BootloaderTimeout 120` |

Das Flashen verwendet das bestehende Image **ohne erneuten Build**. Vor der
Bestätigung zeigt die GUI das Zielgerät, den Imagepfad und den SHA-256 an.
Das Build-Skript prüft anschließend Image, Zusatzdateien und Zielport selbst.
Es schreibt Bootloader, Partitionstabelle, OTA-Daten und App gemäß dem vorhandenen
Projektablauf. Es löscht nicht den gesamten Flash und beschreibt nicht SPIFFS mit
den Gerätezertifikaten. Details und Voraussetzungen stehen in [BUILD.md](../BUILD.md).

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
Panel Studio speichert als Anwendungseinstellungen nur Port, Live-Abfrage und
Upload-Baudrate; keine Passwörter.

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
PowerShell-Anbindung wird mit echten, temporären Testprozessen geprüft, die
keine Hardware ansprechen. Die Vorschauen dienen der Layoutkontrolle.
Eine tatsächliche Übertragung auf das Panel und dessen anschließendes Verhalten
müssen gesondert am Gerät geprüft werden.

| Datei | Aufgabe |
| --- | --- |
| `run.py` | Einstiegspunkt, Demo und PNG-Vorschau |
| `panel_studio/app.py` | Hauptfenster und Benutzerabläufe |
| `panel_studio/widgets.py` | Diagnose, Konfigurationsformular und Log |
| `panel_studio/protocol.py` | Parser und Konfigurationsregeln ohne GUI-Abhängigkeit |
| `panel_studio/transport.py` | Serieller Thread und Befehlszustände |
| `panel_studio/firmware.py` | Imageübersicht und PowerShell-Prozess |

Verwendete APIs: [Qt for Python](https://doc.qt.io/qtforpython-6/),
[pySerial](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).
