"""Representative test data shaped like SerpAPI Google Flights / Google Hotels replies.

These are MOCKED fixtures written for tests, not recordings of live API calls.
"""

REQUEST = {
    "origin": "MAD",
    "destination": "AMS",
    "origin_city": "Madrid",
    "destination_city": "Amsterdam",
    "departure_date": "2026-11-24",
    "return_date": "2026-12-01",
    "adults": 2,
    "children": 1,
    "children_ages": [7],
    "rooms": 1,
    "stops": 1,
    "currency": "USD",
    "email": "private.person@example.com",  # must never appear in any export
}

FLIGHTS_RAW = {
    "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?q=MAD-AMS&hl=en"},
    "best_flights": [
        {
            "flights": [
                {
                    "departure_airport": {"name": "Madrid Barajas", "id": "MAD", "time": "2026-11-24 10:25"},
                    "arrival_airport": {"name": "Schiphol", "id": "AMS", "time": "2026-11-24 13:00"},
                    "duration": 155, "airline": "Iberia", "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/IB.png",
                    "flight_number": "IB 3166",
                }
            ],
            "total_duration": 155, "price": 412, "type": "Round trip",
            "airline_logo": "https://www.gstatic.com/flights/airline_logos/70px/IB.png",
        }
    ],
    "other_flights": [
        {   # connecting itinerary with two airlines -> must become ONE row
            "flights": [
                {"departure_airport": {"id": "MAD", "time": "2026-11-24 06:00"}, "arrival_airport": {"id": "CDG", "time": "2026-11-24 08:10"}, "duration": 130, "airline": "Air France", "flight_number": "AF 1301"},
                {"departure_airport": {"id": "CDG", "time": "2026-11-24 09:30"}, "arrival_airport": {"id": "AMS", "time": "2026-11-24 10:55"}, "duration": 85, "airline": "KLM", "flight_number": "KL 1234"},
            ],
            "total_duration": 295, "price": 355, "type": "Round trip",
        },
        {   # sparse option: no price, no logo, no duration
            "flights": [{"departure_airport": {"id": "MAD", "time": "2026-11-24 22:10"}, "arrival_airport": {"id": "AMS", "time": "2026-11-25 00:45"}, "airline": "=HYPERLINK(\"http://evil\",\"x\")", "flight_number": "XX 1"}],
        },
    ],
}

HOTELS_RAW = {
    "properties": [
        {
            "name": "NobleDen Hotel", "type": "hotel", "overall_rating": 4.8, "reviews": 656, "hotel_class": "4-star hotel",
            "description": "Modern hotel with sleek rooms – café & bar (Zürich-style) 東京",
            "rate_per_night": {"lowest": "$537", "extracted_lowest": 537},
            "total_rate": {"lowest": "$3,223", "extracted_lowest": 3223},
            "amenities": ["Free Wi-Fi", "Parking", "Air conditioning"],
            "images": [{"thumbnail": "https://example.com/img1.jpg"}],
            "link": "http://www.nobleden.com/",
        },
        {   # sparse: no rating, no amenities, no images, no link, no prices
            "name": "Budget <b>Inn</b> & Suites",
        },
        {
            "name": "Canal Stay", "overall_rating": 4.2, "reviews": 120,
            "rate_per_night": {"lowest": "$150", "extracted_lowest": 150},
            "amenities": None, "images": [],
            "link": "javascript:alert(1)",
        },
    ]
}


# ---- attractions (SerpAPI google_maps shape) and weather (Open-Meteo shape): MOCKED
ATTRACTIONS_RAW = {
    "local_results": [
        {"title": "Rijksmuseum", "place_id": "ChIJ1", "rating": 4.8, "reviews": 120000, "type": "Art museum",
         "address": "Museumstraat 1, Amsterdam", "thumbnail": "https://encrypted-tbn0.gstatic.com/r.jpg",
         "gps_coordinates": {"latitude": 52.36, "longitude": 4.885}},
        {"title": "Van Gogh Museum", "place_id": "ChIJ2", "rating": 4.7, "reviews": 90000, "types": ["Museum"],
         "gps_coordinates": {"latitude": 52.358, "longitude": 4.881}},
        {"title": "Vondelpark", "rating": 4.6, "reviews": 80000, "type": "Park",
         "gps_coordinates": {"latitude": 52.358, "longitude": 4.868}},
        {"title": "Anne Frank House", "place_id": "ChIJ4", "rating": 4.5, "reviews": 60000, "type": "Museum",
         "gps_coordinates": {"latitude": 52.375, "longitude": 4.884}},
        {"title": "No-rating place", "place_id": "ChIJ5"},
        {"title": "Fake <script> link", "rating": 4.0, "reviews": 5},
    ]
}


def weather_daily(start="2026-11-24", days=8, hi=9.0, lo=3.0, precip=2.0, code=61):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    return {"daily": {
        "time": [(d0 + timedelta(days=i)).isoformat() for i in range(days)],
        "weather_code": [code] * days, "temperature_2m_max": [hi] * days,
        "temperature_2m_min": [lo] * days, "precipitation_sum": [precip] * days}}
