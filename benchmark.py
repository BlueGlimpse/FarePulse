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


def extract_flights_and_metrics(raw_json, provider_name, run_ts):
    """Extracts anonymized individual flight lines and calculates summary stats."""
    tagged_items = [
        ("best_flights", item) for item in raw_json.get("best_flights", [])
    ] + [
        ("other_flights", item) for item in raw_json.get("other_flights", [])
    ]

    unique_flights = {}

    for bucket, item in tagged_items:
        price = item.get("price")
        legs = item.get("flights", [])
        if not price or not legs:
            continue

        # Build physical flight key (ignores airline/codeshare brand)
        first_leg = legs[0]
        last_leg = legs[-1]
        dep_time = first_leg.get("departure_airport", {}).get("time", "")
        arr_time = last_leg.get("arrival_airport", {}).get("time", "")
        total_duration = item.get("total_duration", 0)
        stops = len(legs) - 1

        flight_key = f"{dep_time}_{arr_time}_{total_duration}_{stops}"

        # Keep lowest price if same physical plane is listed under multiple codeshares
        if flight_key not in unique_flights or float(price) < unique_flights[flight_key]["price"]:
            unique_flights[flight_key] = {
                "run_timestamp": run_ts,
                "provider": provider_name,
                "route": f"{ORIGIN}-{DESTINATION}",
                "depart_date": DEPART_DATE,
                "return_date": RETURN_DATE,
                "flight_bucket": bucket,
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "total_duration_min": total_duration,
                "stops": stops,
                "price": round(float(price), 2),
            }

    detail_rows = list(unique_flights.values())
    if not detail_rows:
        return None, []

    prices = [r["price"] for r in detail_rows]
    nonstop_total = sum(1 for r in detail_rows if r["stops"] == 0)

    summary_metrics = {
        "unique_option_count": len(prices),
        "nonstop_count": nonstop_total,
        "lowest_price": round(min(prices), 2),
        "median_price": round(statistics.median(prices), 2),
        "average_price": round(statistics.mean(prices), 2),
    }

    return summary_metrics, detail_rows


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
        metrics, detail_rows = extract_flights_and_metrics(payload, provider_name, run_ts)

        if not metrics:
            raise ValueError(f"No flight prices in JSON. Keys: {list(payload.keys())}")

        # Insert detail lines first, then summary row
        supabase.table("api_benchmark_details").insert(detail_rows).execute()

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
    print(f"[{provider_name.upper()}] {row['status']} in {elapsed_ms}ms -> {row.get('median_price') or row.get('error_message')}")


if __name__ == "__main__":
    timestamp = datetime.now(timezone.utc).isoformat()
    query_provider("serpapi", timestamp)
    query_provider("searchapi", timestamp)
