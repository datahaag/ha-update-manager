# Update Manager voor Home Assistant

Een HACS-compatibele custom integratie waarmee je bepaalt of **updates** en **reparaties** zichtbaar zijn als badge/notificatie in het **Instellingen**-menu — onafhankelijk van elkaar instelbaar.

Updates blijven altijd zichtbaar op de **Updatepagina** (`/config/updates`).
Reparaties blijven altijd zichtbaar op de **Reparatiespagina** (`/config/repairs`).

---

## Twee schakelaars

### 🔄 Toon updates in Instellingen

| Stand | Instellingen-badge | Updatepagina (`/config/updates`) |
|---|---|---|
| **Aan** (standaard) | ✅ Zichtbaar | ✅ Altijd zichtbaar |
| **Uit** | ❌ Verborgen | ✅ Altijd zichtbaar |

### 🔧 Toon reparaties in Instellingen

| Stand | Instellingen-badge | Reparatiespagina (`/config/repairs`) |
|---|---|---|
| **Aan** (standaard) | ✅ Zichtbaar | ✅ Altijd zichtbaar |
| **Uit** | ❌ Verborgen | ✅ Altijd zichtbaar |

---

## Installatie via HACS

1. Open **HACS** in Home Assistant
2. Ga naar **Integraties → ⋮ → Aangepaste opslagplaatsen**
3. Voeg de URL van deze repository toe als type **Integratie**
4. Zoek naar **Update Manager** en klik op **Downloaden**
5. Herstart Home Assistant

## Installatie handmatig

1. Kopieer de map `custom_components/update_manager/` naar `config/custom_components/update_manager/` op je HA-installatie
2. Herstart Home Assistant

## Configuratie

1. Ga naar **Instellingen → Apparaten & diensten → Integraties toevoegen**
2. Zoek op **Update Manager**
3. Klik op **Toevoegen** en volg de wizard

Er verschijnen twee schakelaars in je entiteiten.
Alleen beheerders kunnen deze globale schakelaars handmatig bedienen; automatiseringen blijven werken.

---

## Slim gedrag

- **Veilig:** de integratie onthoudt precies welke items hij zelf heeft verborgen/genegeerd. Items die door een andere integratie al verborgen waren, worden nooit aangeraakt.
- **Persistent:** de toestand wordt opgeslagen en hersteld na een herstart van Home Assistant.
- **Automatisch:** nieuwe updates of reparaties die binnenkomen terwijl een schakelaar **uit** staat, worden automatisch ook verborgen.
- **Herstelbaar:** zodra je een schakelaar terug **aan** zet, worden exact de items die Update Manager heeft verborgen weer zichtbaar gemaakt.

---

## Automatisering (optioneel voorbeeld)

```yaml
# Verberg updates én reparaties automatisch 's nachts
automation:
  - alias: "Meldingen verbergen 's nachts"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id:
            - switch.toon_updates_in_instellingen
            - switch.toon_reparaties_in_instellingen

  - alias: "Meldingen tonen overdag"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: switch.turn_on
        target:
          entity_id:
            - switch.toon_updates_in_instellingen
            - switch.toon_reparaties_in_instellingen
```

---

## Vereisten

- Home Assistant 2023.1.0 of hoger
- HACS (voor automatische installatie via HACS)
