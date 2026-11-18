import os
import time
import statistics
from datetime import datetime, timezone
import requests
from supabase import create_client

# Load credentials from environment variables
SERPAPI_KEY = os.environ["SERPAPI_KEY"].strip()
SEARCHAPI_KEY = os.environ["SEARCHAPI_KEY"].strip()
SUPABASE_URL = os.environ["SUPABASE_URL"].strip()
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"].strip()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Test route and 2027 dates
ORIGIN = "ATL"
DESTINATION = "MCO"
DEPART_DATE = "2027-03-13"
RETURN_DATE = "2027-03-20"


def normalize_time(raw_time_str):
    """Normalizes SerpApi ('2027-03-13 11:05') and SearchApi ('10:05:00 AM') to 'HH:MM'."""
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


def extract_all_safe_metrics(raw_json):
    """Extracts all safe carrier-agnostic fields and strips airline/trademark identifiers."""
    all_itineraries = raw_json.get("best_flights", []) + raw_json.get("other_flights", [])
    unique_flights = {}

    for item in all_itineraries:
        price = item.get("price")
        legs = item.get("flights", [])
        if not price or not legs:
            continue

        # Build physical flight key (ignores airline, logo, flight_number, airplane model)
        first_leg = legs[0]
        last_leg = legs[-1]
        dep_time = normalize_time(first_leg.get("departure_airport", {}).get("time", ""))
        arr_time = normalize_time(last_leg.get("arrival_airport", {}).get("time", ""))
        total_duration = int(item.get("total_duration", 0))
        stops = len(legs) - 1

        flight_key = f"{dep_time}_{arr_time}_{total_duration}_{stops}"

        # Convert raw text extensions into safe booleans (discards raw trademarked strings)
        raw_ext = " ".join(item.get("extensions", [])).lower()
        leg_ext = " ".join(ext for leg in legs for ext in leg.get("extensions", [])).lower()
        combined_notes = f"{raw_ext} {leg_ext}"

        has_overnight = bool(
            any(leg.get("overnight") for leg in legs)
            or any(lay.get("overnight") for lay in item.get("layovers", []))
        )
        often_delayed = bool(any(leg.get("often_delayed_by_over_30_min") for leg in legs))

        carryon_included = not (
            "no carry-on" in combined_notes or "carry-on bag for a fee" in combined_notes
        )
        wifi_available = "wi-fi" in combined_notes
        power_available = ("power" in combined_notes or "outlet" in combined_notes or "usb" in combined_notes)
        video_available = ("video" in combined_notes or "entertainment" in combined_notes)

        carbon_obj = item.get("carbon_emissions", {})
        this_carbon = carbon_obj.get("this_flight")
        typical_carbon = carbon_obj.get("typical_for_this_route")
        diff_carbon = carbon_obj.get("difference_percent")

        # Deduplicate codeshares by keeping lowest fare per physical schedule
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
                "video_available": video_available,
                "this_carbon": this_carbon,
                "typical_carbon": typical_carbon,
                "diff_carbon": diff_carbon,
            }

    flights = list(unique_flights.values())
    if not flights:
        return None

    prices = sorted(f["price"] for f in flights)
    count = len(flights)
    nonstop_total = sum(1 for f in flights if f["is_nonstop"])
    durations = [f["duration"] for f in flights if f["duration"] > 0]

    carbons = [f["this_carbon"] for f in flights if isinstance(f["this_carbon"], (int, float))]
    typ_carbons = [f["typical_carbon"] for f in flights if isinstance(f["typical_carbon"], (int, float))]
    diff_carbons = [f["diff_carbon"] for f in flights if isinstance(f["diff_carbon"], (int, float))]

    # Quartile distribution
    q_slices = statistics.quantiles(prices, n=4) if count >= 4 else [prices[0], statistics.median(prices), prices[-1]]

    # Top-level Google price insights (carrier-agnostic)
    insights = raw_json.get("price_insights", {})
    typ_range = insights.get("typical_price_range", [])
    typ_low = float(typ_range[0]) if len(typ_range) >= 1 else None
    typ_high = float(typ_range[1]) if len(typ_range) >= 2 else None
    history_points = len(insights.get("price_history", []))

    return {
        "unique_option_count": count,
        "nonstop_count": nonstop_total,
        "connecting_count": count - nonstop_total,
        "lowest_price": round(prices[0], 2),
        "p25_price": round(q_slices[0], 2),
        "median_price": round(statistics.median(prices), 2),
        "average_price": round(statistics.mean(prices), 2),
        "p75_price": round(q_slices[2], 2),
        "highest_price": round(prices[-1], 2),
        "google_price_level": insights.get("price_level"),
        "google_typical_low": typ_low,
        "google_typical_high": typ_high,
        "google_history_points": history_points,
        "avg_duration_min": int(round(statistics.mean(durations))) if durations else None,
        "min_duration_min": min(durations) if durations else None,
        "overnight_flight_share": round((sum(1 for f in flights if f["has_overnight"]) / count) * 100, 2),
        "chronic_delay_share": round((sum(1 for f in flights if f["often_delayed"]) / count) * 100, 2),
        "carryon_included_share": round((sum(1 for f in flights if f["carryon_included"]) / count) * 100, 2),
        "wifi_available_share": round((sum(1 for f in flights if f["wifi_available"]) / count) * 100, 2),
        "power_outlet_share": round((sum(1 for f in flights if f["power_available"]) / count) * 100, 2),
        "on_demand_video_share": round((sum(1 for f in flights if f["video_available"]) / count) * 100, 2),
        "avg_carbon_grams": int(round(statistics.mean(carbons))) if carbons else None,
        "typical_route_carbon_grams": int(round(statistics.mean(typ_carbons))) if typ_carbons else None,
        "avg_carbon_diff_percent": round(statistics.mean(diff_carbons), 2) if diff_carbons else None,
    }


def query_provider(provider_name, run_ts):
    start_time = time.perf_counter()
    headers = {"Accept": "application/json"}

    if provider_name == "serpapi":
        url = "https://serpapi.com" + "/search.json"
        params = {
            "engine": "google_flights",
            "departure_id": ORIGIN,
            "arrival_id": DESTINATION,
            "outbound_date": DEPART_DATE,
            "return_date": RETURN_DATE,
            "type": "1",
            "show_hidden": "true",
            "currency": "USD",
            "gl": "us",
            "hl": "en",
            "api_key": SERPAPI_KEY,
        }
    else:
        url = "https://searchapi.io" + "/api/v1/search"
        params = {
            "engine": "google_flights",
            "departure_id": ORIGIN,
            "arrival_id": DESTINATION,
            "outbound_date": DEPART_DATE,
            "return_date": RETURN_DATE,
            "flight_type": "round_trip",
            "currency": "USD",
            "gl": "us",
            "hl": "en",
            "api_key": SEARCHAPI_KEY,
        }

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=45)
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        resp.raise_for_status()

        payload = resp.json()
        metrics = extract_all_safe_metrics(payload)

        if not metrics:
            raise ValueError(f"No flight prices in JSON. Keys: {list(payload.keys())}")

        row = {
            "run_timestamp": run_ts,
            "provider": provider_name,
            "route": f"{ORIGIN}-{DESTINATION}",
            "depart_date": DEPART_DATE,
            "return_date": RETURN_DATE,
            "response_time_ms": elapsed_ms,
            "status": "success",
            **metrics,
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        clean_error = str(exc).split("api_key=")[0]
        row = {
            "run_timestamp": run_ts,
            "provider": provider_name,
            "route": f"{ORIGIN}-{DESTINATION}",
            "depart_date": DEPART_DATE,
            "return_date": RETURN_DATE,
            "response_time_ms": elapsed_ms,
            "status": "error",
            "error_message": clean_error,
        }

    supabase.table("api_benchmark_logs").insert(row).execute()
    print(f"[{provider_name.upper()}] {row['status']} in {elapsed_ms}ms -> Median ${row.get('median_price')} | Level: {row.get('google_price_level')}")


if __name__ == "__main__":
    timestamp = datetime.now(timezone.utc).isoformat()
    query_provider("serpapi", timestamp)
    query_provider("searchapi", timestamp)
