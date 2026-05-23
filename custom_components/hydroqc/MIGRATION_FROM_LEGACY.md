# Migrating from the old hydroqc add-on

This document is for users who are still running the old `hydroqc` Home
Assistant add-on alongside the new integration, and want to migrate their
historical state data to the new entity names.

If you switched to the new integration a while ago and no longer have the
old add-on installed, you can skip this entirely.

---

## Background

The old `hydroqc` add-on used entity IDs with the prefix
`sensor.hydroqc_maison_*`. The new integration uses
`sensor.hydro_quebec_maison_*` (derived from slugifying the device name
"Hydro-Québec - maison").

Because the entity IDs differ, the historical state data from the old add-on
is not visible in the new integration's history graphs. The migration script
copies that historical data into the new entity names so you get a continuous
history going back as far as the old add-on recorded.

---

## What the script does

- **Copies** historical state rows from old entity IDs to new entity IDs
- **Never deletes** old data — rollback is always possible
- Creates backup tables as an extra safety net
- Handles the case where the new entity already exists (copies only older rows)
- Renames `statistics_meta` entries where the new entry doesn't exist yet
- Deletes orphaned `_2`/`_3` duplicate statistics entries

---

## Prerequisites

- Old `hydroqc` add-on is **stopped** (Settings → Add-ons → Hydroqc → Stop)
- New integration is **running**
- Home Assistant container is **running** (needed for MariaDB hostname resolution)
- `pymysql` Python package installed in the homeassistant container

---

## Entity mapping

| Old entity (hydroqc add-on) | New entity (new integration) |
|-----------------------------|------------------------------|
| `sensor.hydroqc_maison_balance` | `sensor.hydro_quebec_maison_balance` |
| `sensor.hydroqc_maison_current_billing_period_duration` | `sensor.hydro_quebec_maison_billing_period_duration` |
| `sensor.hydroqc_maison_current_billing_period_current_day` | `sensor.hydro_quebec_maison_billing_period_day` |
| `sensor.hydroqc_maison_current_billing_period_total_to_date` | `sensor.hydro_quebec_maison_bill_total_to_date` |
| `sensor.hydroqc_maison_current_billing_period_total_consumption` | `sensor.hydro_quebec_maison_total_consumption` |
| `sensor.hydroqc_maison_current_billing_period_projected_bill` | `sensor.hydro_quebec_maison_projected_bill` |
| `sensor.hydroqc_maison_current_billing_period_projected_total_consumption` | `sensor.hydro_quebec_maison_projected_total_consumption` |
| `sensor.hydroqc_maison_current_billing_period_daily_bill_mean` | `sensor.hydro_quebec_maison_daily_bill_average` |
| `sensor.hydroqc_maison_current_billing_period_daily_consumption_mean` | `sensor.hydro_quebec_maison_daily_consumption_average` |
| `sensor.hydroqc_maison_current_billing_period_kwh_cost_mean` | `sensor.hydro_quebec_maison_average_kwh_cost` |
| `sensor.hydroqc_maison_current_billing_period_average_temperature` | `sensor.hydro_quebec_maison_average_temperature` |
| `sensor.hydroqc_maison_yesterday_evening_peak_saved_credit` | `sensor.hydro_quebec_maison_yesterday_evening_peak_saved_credit` |
| `sensor.hydroqc_maison_yesterday_morning_peak_saved_credit` | `sensor.hydro_quebec_maison_yesterday_morning_peak_saved_credit` |

Sensors not in this list (e.g. `hourly_consumption_cost`, `next_anchor_*`,
`wc_*`, `rate`, `rate_option`) have no equivalent in the new integration
and are left as-is.

---

## Running the migration

🐳 **Inside the homeassistant container** (`docker exec -it homeassistant bash`):

```bash
# Install pymysql if not already installed
pip install pymysql --break-system-packages

# Preview first — no changes made
python3 /config/scripts/migrate_hydroqc_to_hydro_quebec.py --dry-run

# Apply after reviewing dry-run output
python3 /config/scripts/migrate_hydroqc_to_hydro_quebec.py
```

---

## Rollback

Old data is never deleted. To roll back:

1. Disable the new `hydroqc` integration in HA
   (Settings → Devices & Services → Hydro-Québec → disable)
2. Re-enable the old `hydroqc` add-on
3. Your old data is still intact

---

## Cleanup (after verifying everything looks correct)

Drop the backup tables to free up space:

🖥️ **Host shell**:

```bash
docker exec -it $(docker ps | grep mariadb | awk '{print $1}') \
  mariadb -u homeassistant -p<your_password> homeassistant -e "
DROP TABLE IF EXISTS _backup_states;
DROP TABLE IF EXISTS _backup_states_meta;
DROP TABLE IF EXISTS _backup_statistics_meta;
"
```

---

## Note on billing period history

The old add-on's `sensor.hydroqc_maison_current_billing_period_duration`
recorder history is valuable for the Tarif D historical re-split (see
`TARIF_D_SPLIT.md`). Running this migration first means the re-split
service can use both old and new billing duration history for more accurate
period boundary detection going back further than 90 days.
