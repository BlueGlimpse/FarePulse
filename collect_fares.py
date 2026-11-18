import os
import time
import statistics
from datetime import datetime, timedelta, timezone
import requests
from supabase import create_client

SEARCHAPI_KEY = os.environ["SEARCHAPI_KEY"].strip()
SUPABASE_URL = os.environ["SUPABASE_URL"].strip()
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"].strip()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_utc_slot():
    """Rounds current UTC time down to the exact hour for clean slot deduplication."""
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def get_next_saturday(base_date, weeks_ahead):
    """Finds the upcoming Saturday at least `weeks_ahead` weeks from `base_date`."""
    days_until_saturday = (5 - base_date.weekday()) % 7
    upcoming_saturday = base_date + timedelta(days=days_until_saturday)
    return upcoming_saturday + timedelta(weeks=weeks_ahead)


def normalize_time(raw_time_str):
    """Converts SearchApi '10:05:00 AM' or ISO timestamps into 'HH:MM'."""
    if not raw_time_str:
        return ""
    raw_time_str = raw_time_str.strip()
    for fmt in ("%I:%M:%S %p", "%I:%M %p"):
        try:
            return datetime.strptime(raw_time_str, fmt).strftime("%H:%M")
        except ValueError:
            pass
    if " " in raw_time_str:
        return raw_time_str.split(" ")[-1][:5]
    return raw_time_str[:5]


def parse_safe_snapshot(payload, route_row, window_row, depart_str, return_str, slot_ts, elapsed_ms):
    """Extracts anonymized aggregate metrics and strips all carrier/trademark identifiers."""
    all_items = payload.get("best_flights", []) + payload.get("other_flights", [])
    unique_flights = {}

    for item in all_items:
        price = item.get("price")
        legs = item.get("flights", [])
        if not price or not legs:
            continue

        first_leg = legs
        last_leg = legs[-1]
        dep_time = normalize_time(first_leg.get("departure_airport", {}).get("time", ""))
        arr_time = normalize_time(last_leg.get("arrival_airport", {}).get("time", ""))
        total_duration = int(item.get("total_duration", 0))
        stops = len(legs) - 1

        # Physical schedule key (no airline or flight number)
        flight_key = f"{dep_time}_{arr_time}_{total_duration}_{stops}"

        # Combine itinerary and leg extensions into lowercase text for boolean feature detection
        raw_ext = " ".join(item.get("extensions", [])).lower()
        leg_ext = " ".join(ext for leg in legs for ext in leg.get("extensions", [])).lower()
        combined_notes = f"{raw_ext} {leg_ext}"

        has_overnight = bool(
            any(leg.get("overnight") for leg in legs)
            or any(lay.get("overnight") for lay in item.get("layovers", []))
        )
        often_delayed = bool(any(leg.get("often_delayed_by_over_30_min") for leg in legs))

        # Carry-on included unless explicitly marked as 'no carry-on' or 'carry-on bag for a fee'
        carryon_included = not (
            "no carry-on" in combined_notes or "carry-on bag for a fee" in combined_notes
        )
        wifi_available = "wi-fi" in combined_notes
        power_available = ("power" in combined_notes or "outlet" in combined_notes or "usb" in combined_notes)

        carbon_obj = item.get("carbon_emissions", {})
        this_carbon = carbon_obj.get("this_flight")
        typical_carbon = carbon_obj.get("typical_for_this_route")

        if flight_key not in unique_flights or float(price) < unique_flights[flight_key]["price"]:
            unique_flights[flight_key] = {
                "price": float(price),
                "is_nonstop": (stops == 0),
                "duration": total_duration,
                "has_overnight": has_overnight,
                "often_delayed": often_delayed,
                "carryon_included": carryon_included,
                "wifi_available": wifi_available,
                "power_available": power_available,
                "this_carbon": this_carbon,
                "typical_carbon": typical_carbon,
            }

    flights = list(unique_flights.values())
    if not flights:
        return None

    prices = sorted(f["price"] for f in flights)
    count = len(flights)
    nonstop_count = sum(1 for f in flights if f["is_nonstop"])
    durations = [f["duration"] for f in flights if f["duration"] > 0]
    carbons = [f["this_carbon"] for f in flights if isinstance(f["this_carbon"], (int, float))]
    typ_carbons = [f["typical_carbon"] for f in flights if isinstance(f["typical_carbon"], (int, float))]

    # Quartile calculations
    q_slices = statistics.quantiles(prices, n=4) if count >= 4 else [prices, statistics.median(prices), prices[-1]]

    # Top-level Google price insights (carrier-agnostic)
    insights = payload.get("price_insights", {})
    typ_range = insights.get("typical_price_range", [])
    typ_low = float(typ_range) if len(typ_range) >= 1 else None
    typ_high = float(typ_range[1]) if len(typ_range) >= 2 else None

    return {
        "slot_timestamp": slot_ts.isoformat(),
        "route": f"{route_row['origin']}-{route_row['destination']}",
        "market_category": route_row["market_category"],
        "slot_name": window_row["slot_name"],
        "horizon_weeks": window_row["horizon_weeks"],
        "depart_date": depart_str,
        "return_date": return_str,
        "unique_option_count": count,
        "nonstop_count": nonstop_count,
        "connecting_count": count - nonstop_count,
        "lowest_price": round(prices, 2),
        "p25_price": round(q_slices, 2),
        "median_price": round(statistics.median(prices), 2),
        "average_price": round(statistics.mean(prices), 2),
        "p75_price": round(q_slices[2], 2),
        "highest_price": round(prices[-1], 2),
        "google_price_level": insights.get("price_level"),
        "google_typical_low": typ_low,
        "google_typical_high": typ_high,
        "avg_duration_min": int(round(statistics.mean(durations))) if durations else None,
        "min_duration_min": min(durations) if durations else None,
        "overnight_flight_share": round((sum(1 for f in flights if f["has_overnight"]) / count) * 100, 2),
        "chronic_delay_share": round((sum(1 for f in flights if f["often_delayed"]) / count) * 100, 2),
        "carryon_included_share": round((sum(1 for f in flights if f["carryon_included"]) / count) * 100, 2),
        "wifi_available_share": round((sum(1 for f in flights if f["wifi_available"]) / count) * 100, 2),
        "power_outlet_share": round((sum(1 for f in flights if f["power_available"]) / count) * 100, 2),
        "avg_carbon_grams": int(round(statistics.mean(carbons))) if carbons else None,
        "typical_route_carbon_grams": int(round(statistics.mean(typ_carbons))) if typ_carbons else None,
        "response_time_ms": elapsed_ms,
    }


def run_collector():
    slot_ts = get_utc_slot()
    current_hour = slot_ts.hour
    today_utc = slot_ts.date()

    routes = supabase.table("routes").select("*").eq("is_active", True).execute().data
    windows = supabase.table("tracking_windows").select("*").eq("is_active", True).execute().data

    url = "https://searchapi.io" + "/api/v1/search"
    headers = {"Accept": "application/json"}

    for route in routes:
        # Respect per-route polling cadence (e.g., every 1 hour vs every 3 hours)
        if current_hour % route["poll_interval_hours"] != 0:
            continue

        for win in windows:
            depart_dt = get_next_saturday(today_utc, win["horizon_weeks"])
            return_dt = depart_dt + timedelta(days=win["trip_nights"])
            depart_str = depart_dt.isoformat()
            return_str = return_dt.isoformat()

            params = {
                "engine": "google_flights",
                "departure_id": route["origin"],
                "arrival_id": route["destination"],
                "outbound_date": depart_str,
                "return_date": return_str,
                "flight_type": "round_trip",
                "currency": "USD",
                "gl": "us",
                "hl": "en",
                "api_key": SEARCHAPI_KEY,
            }
            if route.get("nonstop_only"):
                params["stops"] = "nonstop"

            try:
                start_t = time.perf_counter()
                resp = requests.get(url, params=params, headers=headers, timeout=45)
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                resp.raise_for_status()

                snapshot = parse_safe_snapshot(
                    resp.json(), route, win, depart_str, return_str, slot_ts, elapsed_ms
                )
                if snapshot:
                    supabase.table("fare_snapshots").upsert(
                        snapshot, on_conflict="route,slot_name,depart_date,slot_timestamp"
                    ).execute()
                    print(f"[OK] {snapshot['route']} ({win['slot_name']}) -> Median ${snapshot['median_price']}")
                else:
                    print(f"[SKIP] {route['origin']}-{route['destination']} ({win['slot_name']}) -> No flights")
            except Exception as exc:
                clean_err = str(exc).split("api_key=")
                print(f"[ERR] {route['origin']}-{route['destination']} ({win['slot_name']}) -> {clean_err}")


if __name__ == "__main__":
    run_collector()
