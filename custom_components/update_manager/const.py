"""Constants for Update Manager."""

DOMAIN = "update_manager"
PLATFORMS = ["switch"]

# Storage keys for persisting hidden/ignored state across restarts
STORAGE_KEY_UPDATES = f"{DOMAIN}.hidden_update_entities"
STORAGE_KEY_REPAIRS = f"{DOMAIN}.ignored_repair_issues"
STORAGE_VERSION = 1
