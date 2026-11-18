# Changelog

Alle nennenswerten Änderungen an dieser Integration. Englische Fassung:
[CHANGELOG.en.md](CHANGELOG.en.md).

## 0.1.4

### Neu

- Zusatzakku: Restenergie und Vollenergie in Wh. Der Akku meldet seine Kapazität nur in Ah
  bei 51,2 V Packspannung; 40 Ah entsprechen dort 2048 Wh. Die Ah-Sensoren bleiben.

### Geändert

- Bibliothekscode entfernt, den seit der Beschränkung auf die DELTA 3 Max Plus kein Gerät
  mehr nutzt. Kein geändertes Verhalten.

## 0.1.3

### Behoben

- Die Leistung je AC-Gruppe („AC (1) Leistung", „AC (2) Leistung") wird positiv angezeigt,
  wie die AC-Ausgangsleistung insgesamt. Bisher stand dort der Rohwert des Geräts mit
  negativem Vorzeichen. Wer die Werte in Automationen oder Statistiken nutzt, muss das
  Vorzeichen anpassen.

## 0.1.2

### Geändert

- Die Zelltemperatur des Hauptakkus ist standardmäßig aktiv, wie die des Zusatzakkus.
  Bestehende Installationen behalten ihre Einstellung.
- Eine gewollte Trennung der Bluetooth-Verbindung, etwa beim Neuladen der Integration,
  steht nicht mehr als Warnung im Log. Eine unerwartete Trennung weiterhin.

## 0.1.1

### Behoben

- Zusatzakku wird beim ersten Anlegen zuverlässig mit seiner Station verknüpft. Die Station
  wird jetzt im eigenen Konfigurationseintrag gesucht, auch bevor die Entität registriert
  ist.
- Fehlt die Station in der Geräte-Registry, steht das als Warnung im Log, statt dass die
  Verknüpfung still wegfällt.
- Die Erkennung, wie Home Assistant ein Gerät mit seinem Elterngerät verknüpft, hängt nicht
  mehr an Typannotationen.

## 0.1.0

Erste Version. Harter Fork von `rabits/ha-ef-ble` v1.3.1, reduziert auf die EcoFlow
DELTA 3 Max Plus und ihren Zusatzakku.

### Geändert gegenüber ha-ef-ble

- Neue Domain `ecoflow_d3mp`. Einträge aus `ha-ef-ble` werden nicht übernommen; das Gerät
  wird neu eingerichtet.
- Unterstützt wird nur noch die DELTA 3 Max Plus. Alle anderen Geräte, die
  Wave-Klimaplattform und die Sammelfunktion für nicht unterstützte Geräte sind entfernt.
- Entitätsschlüssel sind bereinigt, Unique IDs lauten `d3mp_{seriennummer}_{schlüssel}`.
- Übersetzungen: Englisch und Deutsch.

### Neu

- Zusatzakku als eigenes Gerät: Ladestand, Kapazität (Nenn, Voll, Rest), Zellspannungen,
  Temperaturen, Ladezustand, Typ und Strom. Den Strom meldet das Gerät nicht; er wird aus
  der Änderung der Restkapazität über eine Minute gemessen (Laden positiv). Ein zweiter Port
  wird gelesen, ist aber ungeprüft und standardmäßig deaktiviert.
- Schalter für die zweite AC-Gruppe, X-Boost, Signalton und „Ausgänge nach Stromausfall
  wiederherstellen". Auswahl des AC-Lademodus.
- Regler für Standby-Zeiten, Display-Abschaltzeit und Display-Helligkeit.
- Lesewerte: Schnellladen, Betriebszustand, Ausfallreserve je Ausgang, Fehlercodes je
  Baugruppe, Ladezustand von System und Hauptakku, WLAN-Signalstärke.
- Die Backup-Reserve liest ihren Zustand aus dem Feld, das das Gerät tatsächlich setzt, und
  sendet beim Scharfschalten immer auch den Pegel mit.

### Grenzen

- Regler bleiben im Bereich, den EcoFlow für dieses Modell anbietet: Ladegrenze 50–100 %,
  Entladegrenze 0–30 %, Reserve bis 50 % und fünf Punkte über der Entladegrenze,
  AC-Ladeleistung 200–2400 W, DC-Eingangsstrom 4–8 A.
- Ausschalten, „Netz-Durchleitung sperren" und der DC-Eingangsstrom sind standardmäßig
  deaktiviert. Ausschalten warnt im Log, wenn Leistung fließt, weil das Gerät den Befehl
  dann ignoriert.

### Entfernt

- Schalter für die Energie-Strategien und für die USB-Ausgänge sowie die Sensoren für
  Lüfter und Akku-Leistung: Das Gerät meldet die zugehörigen Werte nicht oder reagiert
  nicht auf den Befehl.
