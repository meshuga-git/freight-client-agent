"""Conservative, logged-by-caller normalization; preserve unknown values."""

from decimal import Decimal
import json
import re
from datetime import datetime

COUNTRIES = {
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "china": "CN",
    "germany": "DE",
    "canada": "CA",
    "mexico": "MX",
    "france": "FR",
    "india": "IN",
}


def normalize(name, value):
    if not isinstance(value, str):
        return value
    value = value.strip()
    if name in {"lines", "quantities"}:
        try:
            return json.loads(value, parse_float=str)
        except (ValueError, TypeError):
            return value
    if name in {"package_count"}:
        return int(value) if re.fullmatch(r"\d+", value) else value
    if name in {"total", "freight_charge", "insurance_charge", "gross_weight_kg", "volume_m3"}:
        match = re.fullmatch(
            r"((?:0|[1-9]\d*|[1-9]\d{0,2}(?:,\d{3})+)(?:\.\d+)?)\s*(kg|kgs|lb|lbs|m3|m³)?",
            value,
            re.I,
        )
        if match:
            unit = (match[2] or "").lower()
            allowed = {
                "gross_weight_kg": {"", "kg", "kgs", "lb", "lbs"},
                "volume_m3": {"", "m3", "m³"},
            }.get(name, {""})
            if unit not in allowed:
                return value
            result = Decimal(match[1].replace(",", ""))
            if name == "gross_weight_kg" and (match[2] or "").lower() in {"lb", "lbs"}:
                result *= Decimal("0.45359237")
            return format(result.normalize(), "f")
    if name in {"invoice_date", "on_board_date", "eta"}:
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
    if name == "country_of_origin":
        return COUNTRIES.get(value.lower(), value.upper() if len(value) == 2 else value)
    if name in {"currency", "incoterm", "container_number", "port_of_loading", "port_of_discharge"}:
        return value.upper().replace(" ", "")
    return value
