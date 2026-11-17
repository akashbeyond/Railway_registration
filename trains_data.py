"""Train timetable generator.

10 stations -> 90 routes (every station to every other station).
Each route has 2 trains that run EVERY DAY: an early-morning one and an evening one.
Total: 180 trains. Because each train runs daily, every date up to the booking
end date (see BOOKING_END in app.py) has 2 trains per route, with its own seat count.

Distance is estimated from the station coordinates, then used for travel time and fare.
"""
from math import asin, cos, radians, sin, sqrt

# name: (latitude, longitude)
STATIONS = {
    "Bengaluru": (12.97, 77.59),
    "Mysuru": (12.30, 76.64),
    "Davanagere": (14.46, 75.92),
    "Hubballi": (15.36, 75.12),
    "Mangaluru": (12.91, 74.86),
    "Belagavi": (15.85, 74.50),
    "Chennai": (13.08, 80.27),
    "Hyderabad": (17.39, 78.49),
    "Pune": (18.52, 73.86),
    "Mumbai": (19.08, 72.88),
}


def _rail_km(a, b):
    """Great-circle distance in km, +25% to approximate real rail routes."""
    (lat1, lon1), (lat2, lon2) = STATIONS[a], STATIONS[b]
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h)) * 1.25


def _hhmm(minutes):
    minutes %= 24 * 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def build_trains():
    """Return rows: (number, name, source, destination, departs, arrives, fare, total_seats)."""
    names = list(STATIONS)
    rows = []
    route_no = 0
    for src in names:
        for dst in names:
            if src == dst:
                continue
            km = _rail_km(src, dst)
            duration = int(km / 60 * 60) + 20            # minutes at ~60 km/h + 20 min halts
            fare = max(100, int(round(km * 0.9 / 10)) * 10)
            morning = 5 * 60 + 30 + (route_no % 5) * 15  # 05:30 - 06:30
            evening = 17 * 60 + (route_no % 7) * 15      # 17:00 - 18:30
            for label, dep, seats, offset in (("Morning", morning, 80, 1), ("Evening", evening, 100, 2)):
                number = str(20000 + route_no * 2 + offset)
                rows.append((number, f"{src} - {dst} {label} Express", src, dst,
                             _hhmm(dep), _hhmm(dep + duration), fare, seats))
            route_no += 1
    return rows


if __name__ == "__main__":      # python trains_data.py  -> prints a summary
    data = build_trains()
    print(len(data), "trains,", len(STATIONS), "stations")
    for row in data[:4]:
        print(row)
