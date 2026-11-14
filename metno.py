"""Backup forecast source: MET Norway Locationforecast 2.0 (free, no key).

Returns data in the same shape as the Open-Meteo response that render.py expects,
so the renderer doesn't care which source was used.
"""
import datetime as dt
import json
import math
import urllib.request
from collections import defaultdict
from zoneinfo import ZoneInfo

UA = "kindle-weather/1.0 github.com/pauricodonnell/kindle-weather"

# MET Norway symbol (without _day/_night/_polartwilight) -> WMO weather code
SYMBOL_WMO = {
    "clearsky": 0, "fair": 1, "partlycloudy": 2, "cloudy": 3, "fog": 45,
    "lightrain": 61, "rain": 63, "heavyrain": 65,
    "lightrainshowers": 80, "rainshowers": 81, "heavyrainshowers": 82,
    "lightsleet": 66, "sleet": 67, "heavysleet": 67,
    "lightsleetshowers": 85, "sleetshowers": 85, "heavysleetshowers": 86,
    "lightsnow": 71, "snow": 73, "heavysnow": 75,
    "lightsnowshowers": 85, "snowshowers": 85, "heavysnowshowers": 86,
}


def symbol_to_wmo(sym):
    if not sym:
        return 3
    base = sym.split("_")[0]
    if "thunder" in base:
        return 95
    return SYMBOL_WMO.get(base, 3)


def sun_times(day, lat, lon, tz):
    """Sunrise/sunset (local naive datetimes) via the NOAA approximation."""
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_ha = (math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl))
              - math.tan(la) * math.tan(decl))
    ha = math.degrees(math.acos(max(-1, min(1, cos_ha))))
    base = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc)
    rise = base + dt.timedelta(minutes=720 - 4 * (lon + ha) - eqt)
    sset = base + dt.timedelta(minutes=720 - 4 * (lon - ha) - eqt)
    z = ZoneInfo(tz)
    return rise.astimezone(z).replace(tzinfo=None), sset.astimezone(z).replace(tzinfo=None)


def feels_like(t, wind_kmh, rh):
    if t <= 10 and wind_kmh > 4.8:  # wind chill
        v = wind_kmh ** 0.16
        return 13.12 + 0.6215 * t - 11.37 * v + 0.3965 * t * v
    return t


def fetch(lat, lon, tz):
    url = (f"https://api.met.no/weatherapi/locationforecast/2.0/complete"
           f"?lat={lat:.4f}&lon={lon:.4f}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = json.load(r)
    z = ZoneInfo(tz)
    series = raw["properties"]["timeseries"]

    hourly = defaultdict(list)
    times = [dt.datetime.fromisoformat(e["time"].replace("Z", "+00:00")).astimezone(z) for e in series]
    for n, e in enumerate(series):
        t = times[n]
        nxt = e["data"].get("next_1_hours")
        if not nxt:  # beyond ~2.5 days MET gives 6-hourly steps; fill the hours in
            nxt6 = e["data"].get("next_6_hours")
            if not nxt6:
                continue
            gap = int((times[n + 1] - t).total_seconds() // 3600) if n + 1 < len(times) else 6
            steps = max(1, min(6, gap))
            nxt = {"summary": nxt6["summary"],
                   "details": {"precipitation_amount": nxt6["details"].get("precipitation_amount", 0) / 6,
                               "probability_of_precipitation": nxt6["details"].get("probability_of_precipitation")}}
        else:
            steps = 1
        d = e["data"]["instant"]["details"]
        for k in range(steps):
            tt = t + dt.timedelta(hours=k)
            hourly["time"].append(tt.strftime("%Y-%m-%dT%H:%M"))
            hourly["temperature_2m"].append(d["air_temperature"])
            hourly["weather_code"].append(symbol_to_wmo(nxt["summary"]["symbol_code"]))
            hourly["precipitation"].append(nxt["details"].get("precipitation_amount", 0) or 0)
            p = nxt["details"].get("probability_of_precipitation")
            hourly["precipitation_probability"].append(round(p) if p is not None else None)  # Nordic-only
            hourly["wind_speed_10m"].append(d["wind_speed"] * 3.6)
            hourly["wind_gusts_10m"].append(d.get("wind_speed_of_gust", d["wind_speed"] * 1.5) * 3.6)
            hourly["is_day"].append(0)  # set below

    days = sorted({t[:10] for t in hourly["time"]})
    daily = defaultdict(list)
    sun = {}
    for day in days:
        date = dt.date.fromisoformat(day)
        rise, sset = sun_times(date, lat, lon, tz)
        sun[day] = (rise, sset)
        idx = [i for i, t in enumerate(hourly["time"]) if t.startswith(day)]
        temps = [hourly["temperature_2m"][i] for i in idx]
        codes = [hourly["weather_code"][i] for i in idx
                 if 9 <= int(hourly["time"][i][11:13]) <= 18] or [hourly["weather_code"][i] for i in idx]
        daily["time"].append(day)
        daily["temperature_2m_max"].append(max(temps))
        daily["temperature_2m_min"].append(min(temps))
        code = max(codes)  # most significant daytime weather
        if sum(hourly["precipitation"][i] for i in idx) >= 1 and code < 51:
            code = max(hourly["weather_code"][i] for i in idx)  # rain fell outside daytime hours
        daily["weather_code"].append(code)
        daily["precipitation_sum"].append(sum(hourly["precipitation"][i] for i in idx))
        probs = [hourly["precipitation_probability"][i] for i in idx if hourly["precipitation_probability"][i] is not None]
        daily["precipitation_probability_max"].append(max(probs) if probs else None)
        daily["wind_speed_10m_max"].append(max(hourly["wind_speed_10m"][i] for i in idx))
        daily["wind_gusts_10m_max"].append(max(hourly["wind_gusts_10m"][i] for i in idx))
        daily["sunrise"].append(rise.strftime("%Y-%m-%dT%H:%M"))
        daily["sunset"].append(sset.strftime("%Y-%m-%dT%H:%M"))
    for i, t in enumerate(hourly["time"]):
        tt = dt.datetime.fromisoformat(t)
        rise, sset = sun[t[:10]]
        hourly["is_day"][i] = 1 if rise <= tt < sset else 0

    first = series[0]["data"]
    d = first["instant"]["details"]
    wind = d["wind_speed"] * 3.6
    current = {
        "temperature_2m": d["air_temperature"],
        "apparent_temperature": feels_like(d["air_temperature"], wind, d.get("relative_humidity", 80)),
        "weather_code": symbol_to_wmo(first.get("next_1_hours", {}).get("summary", {}).get("symbol_code")),
        "is_day": hourly["is_day"][0],
        "wind_speed_10m": wind,
        "wind_gusts_10m": d.get("wind_speed_of_gust", d["wind_speed"] * 1.5) * 3.6,
        "wind_direction_10m": d["wind_from_direction"],
        "relative_humidity_2m": d.get("relative_humidity", 0),
        "precipitation": first.get("next_1_hours", {}).get("details", {}).get("precipitation_amount", 0),
    }
    return {"current": current, "hourly": dict(hourly), "daily": dict(daily), "source": "MET Norway"}
