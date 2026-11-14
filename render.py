#!/usr/bin/env python3
"""Render a weather dashboard PNG for a Kindle e-ink screen.

Data: Open-Meteo (free, no API key). Output: 8-bit greyscale PNG.

    python render.py                 # live forecast -> out/weather.png
    python render.py --sample s.json # render from a saved JSON response
"""
import argparse
import datetime as dt
import json
import math
import os
import urllib.request
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

# ---- settings ---------------------------------------------------------------
PLACE = os.environ.get("PLACE", "Letterkenny")
LAT = float(os.environ.get("LAT", "54.9558"))
LON = float(os.environ.get("LON", "-7.7342"))
TZ = os.environ.get("TZ_NAME", "Europe/Dublin")
W, H = int(os.environ.get("WIDTH", "600")), int(os.environ.get("HEIGHT", "800"))
S = 2  # supersampling factor: draw at 2x, downscale for smooth edges

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")

API = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={LAT}&longitude={LON}&timezone={TZ.replace('/', '%2F')}"
    "&wind_speed_unit=kmh&forecast_days=6"
    "&current=temperature_2m,apparent_temperature,weather_code,is_day,"
    "wind_speed_10m,wind_gusts_10m,wind_direction_10m,relative_humidity_2m,precipitation"
    "&hourly=temperature_2m,weather_code,precipitation_probability,precipitation,is_day"
    "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
    "precipitation_sum,precipitation_probability_max,wind_speed_10m_max,"
    "wind_gusts_10m_max,sunrise,sunset"
)

# ---- weather codes (WMO) -----------------------------------------------------
WMO_TEXT = {
    0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy",
    45: "Fog", 48: "Freezing fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    56: "Freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    66: "Freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Heavy showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunder & hail", 99: "Thunder & hail",
}


def kind(code):
    if code in (0,):
        return "clear"
    if code in (1, 2):
        return "partly"
    if code == 3:
        return "cloudy"
    if code in (45, 48):
        return "fog"
    if 51 <= code <= 57:
        return "drizzle"
    if 61 <= code <= 67 or 80 <= code <= 82:
        return "rain"
    if 71 <= code <= 77 or code in (85, 86):
        return "snow"
    if code >= 95:
        return "thunder"
    return "cloudy"


COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass(deg):
    return COMPASS[int((deg % 360) / 45 + 0.5) % 8]


# ---- drawing helpers --------------------------------------------------------
_fonts = {}


def font(weight, size):
    files = {
        "light": "InterDisplay-Light.otf", "display": "InterDisplay-SemiBold.otf",
        "regular": "Inter-Regular.otf", "medium": "Inter-Medium.otf",
        "semibold": "Inter-SemiBold.otf", "bold": "Inter-Bold.otf",
    }
    key = (weight, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(os.path.join(FONT_DIR, files[weight]), size * S)
    return _fonts[key]


class Canvas:
    def __init__(self):
        self.img = Image.new("L", (W * S, H * S), 255)
        self.d = ImageDraw.Draw(self.img)

    def text(self, xy, s, f, fill=0, anchor="la"):
        self.d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)

    def width(self, s, f):
        return self.d.textlength(s, font=f) / S

    def line(self, pts, fill=0, width=1):
        self.d.line([(x * S, y * S) for x, y in pts], fill=fill, width=int(width * S))

    def rect(self, box, fill=None, outline=None, width=1, radius=0):
        b = [v * S for v in box]
        self.d.rounded_rectangle(b, radius=radius * S, fill=fill, outline=outline, width=int(width * S))

    def ellipse(self, box, fill=None, outline=None, width=1):
        self.d.ellipse([v * S for v in box], fill=fill, outline=outline, width=int(width * S))

    def polygon(self, pts, fill=0):
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=fill)

    def final(self):
        return self.img.resize((W, H), Image.LANCZOS)


def draw_sun(c, cx, cy, r, lw):
    c.ellipse((cx - r * 0.5, cy - r * 0.5, cx + r * 0.5, cy + r * 0.5), outline=0, width=lw)
    for i in range(8):
        a = i * math.pi / 4
        c.line([(cx + math.cos(a) * r * 0.68, cy + math.sin(a) * r * 0.68),
                (cx + math.cos(a) * r * 0.92, cy + math.sin(a) * r * 0.92)], width=lw)


def draw_moon(c, cx, cy, r, lw):
    c.ellipse((cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55), fill=0)
    o = r * 0.32
    c.ellipse((cx - r * 0.55 + o, cy - r * 0.55 - o * 0.6, cx + r * 0.55 + o, cy + r * 0.55 - o * 0.6), fill=255)


def draw_cloud(c, cx, cy, r, lw, fill=255):
    # three overlapping circles + flat base, drawn as outline over white fill
    parts = [(cx - r * 0.42, cy + r * 0.08, r * 0.36), (cx + r * 0.05, cy - r * 0.12, r * 0.48),
             (cx + r * 0.5, cy + r * 0.12, r * 0.32)]
    base = (cx - r * 0.78, cy + r * 0.08, cx + r * 0.82, cy + r * 0.44)
    for px, py, pr in parts:
        c.ellipse((px - pr - lw, py - pr - lw, px + pr + lw, py + pr + lw), fill=0)
    c.rect((base[0] - lw, base[1] - lw, base[2] + lw, base[3] + lw), fill=0, radius=(base[3] - base[1]) / 2 + lw)
    for px, py, pr in parts:
        c.ellipse((px - pr, py - pr, px + pr, py + pr), fill=fill)
    c.rect(base, fill=fill, radius=(base[3] - base[1]) / 2)


def draw_icon(c, k, cx, cy, size, night=False):
    r = size / 2
    lw = max(1.5, size / 26)
    if k == "clear":
        (draw_moon if night else draw_sun)(c, cx, cy, r, lw)
        return
    if k == "partly":
        (draw_moon if night else draw_sun)(c, cx - r * 0.3, cy - r * 0.3, r * 0.75, lw)
        draw_cloud(c, cx + r * 0.12, cy + r * 0.15, r * 0.78, lw)
        return
    if k == "fog":
        for i, dy in enumerate((-0.35, -0.05, 0.25, 0.55)):
            inset = 0.1 if i % 2 else 0.0
            c.line([(cx - r * (0.8 - inset), cy + r * dy), (cx + r * (0.8 - inset * 2), cy + r * dy)], width=lw * 1.3)
        return
    # cloud-based icons: lift the cloud a little to leave room for precipitation
    lift = 0 if k == "cloudy" else r * 0.22
    draw_cloud(c, cx, cy - lift, r * 0.95, lw, fill=255 if k != "thunder" else 200)
    by = cy + r * 0.42
    if k in ("rain", "drizzle"):
        n, ln = (3, 0.32) if k == "rain" else (3, 0.14)
        for i in range(n):
            x = cx + (i - 1) * r * 0.42
            c.line([(x, by), (x - r * 0.12, by + r * ln)], width=lw * 1.2)
            if k == "drizzle":
                c.line([(x - r * 0.18, by + r * 0.28), (x - r * 0.24, by + r * 0.4)], width=lw * 1.2)
    elif k == "snow":
        for i in range(3):
            x, y = cx + (i - 1) * r * 0.42, by + r * 0.18 + (i % 2) * r * 0.12
            for a in range(3):
                ang = a * math.pi / 3
                dx, dy = math.cos(ang) * r * 0.11, math.sin(ang) * r * 0.11
                c.line([(x - dx, y - dy), (x + dx, y + dy)], width=lw)
    elif k == "thunder":
        x, y = cx, by - r * 0.05
        c.polygon([(x + r * 0.05, y), (x - r * 0.18, y + r * 0.3), (x - r * 0.02, y + r * 0.3),
                   (x - r * 0.12, y + r * 0.58), (x + r * 0.2, y + r * 0.2), (x + r * 0.03, y + r * 0.2),
                   (x + r * 0.14, y)])


def rain_drop(c, x, y, h, fill=0):
    """Small droplet glyph, top at (x, y), height h."""
    w = h * 0.62
    c.polygon([(x, y), (x - w / 2, y + h * 0.62), (x + w / 2, y + h * 0.62)], fill=fill)
    c.ellipse((x - w / 2, y + h * 0.38, x + w / 2, y + h * 0.38 + w), fill=fill)


# ---- layout -----------------------------------------------------------------
def render(data, now=None):
    tz = ZoneInfo(TZ)
    now = now or dt.datetime.now(tz)
    cur, hourly, daily = data["current"], data["hourly"], data["daily"]
    c = Canvas()
    M = 28  # margin

    # header
    c.text((M, 26), PLACE, font("bold", 30))
    c.text((M, 64), now.strftime("%A %-d %B"), font("regular", 19), fill=60)
    c.text((W - M, 30), now.strftime("%H:%M"), font("semibold", 26), anchor="ra")
    c.text((W - M, 64), "updated", font("regular", 15), fill=110, anchor="ra")
    c.line([(M, 100), (W - M, 100)], width=2)

    # current conditions
    code = cur["weather_code"]
    draw_icon(c, kind(code), M + 78, 192, 150, night=not cur.get("is_day", 1))
    temp = f"{round(cur['temperature_2m'])}°"
    c.text((205, 122), temp, font("light", 118))
    tx = 205 + c.width(temp, font("light", 118)) + 18
    tx = max(tx, 400)
    c.text((tx, 134), WMO_TEXT.get(code, ""), font("semibold", 22))
    c.text((tx, 166), f"Feels {round(cur['apparent_temperature'])}°", font("regular", 19), fill=50)
    c.text((tx, 194), f"Humidity {round(cur['relative_humidity_2m'])}%", font("regular", 19), fill=50)

    # wind line under the big temperature
    wind = (f"Wind {compass(cur['wind_direction_10m'])} {round(cur['wind_speed_10m'])} km/h"
            f"  ·  gusts {round(cur['wind_gusts_10m'])}")
    c.text((205, 262), wind, font("medium", 20))

    # next hours (every 3h from the next full hour)
    times = [dt.datetime.fromisoformat(t).replace(tzinfo=tz) for t in hourly["time"]]
    start = next(i for i, t in enumerate(times) if t > now)
    idx = [start + 3 * k for k in range(8) if start + 3 * k < len(times)]
    top = 312
    c.rect((M - 8, top - 12, W - M + 8, top + 186), fill=238, radius=14)
    c.text((M + 4, top), "NEXT 24 HOURS", font("semibold", 14), fill=80)
    colw = (W - 2 * M) / len(idx)
    for j, i in enumerate(idx):
        x = M + colw * (j + 0.5)
        c.text((x, top + 28), times[i].strftime("%H:%M"), font("medium", 16), fill=40, anchor="ma")
        draw_icon(c, kind(hourly["weather_code"][i]), x, top + 82, 46, night=not hourly["is_day"][i])
        c.text((x, top + 114), f"{round(hourly['temperature_2m'][i])}°", font("semibold", 22), anchor="ma")
        p = hourly["precipitation_probability"][i] or 0
        ptxt, pf = f"{p}%", font("regular", 15)
        x0 = x - (9 + 5 + c.width(ptxt, pf)) / 2
        rain_drop(c, x0 + 4.5, top + 151, 13, fill=0 if p >= 50 else 120)
        c.text((x0 + 14, top + 147), ptxt, pf, fill=0 if p >= 50 else 90)

    # next days
    top = 530
    c.text((M + 4, top - 14), "NEXT 5 DAYS", font("semibold", 14), fill=80)
    days = [dt.date.fromisoformat(d) for d in daily["time"]]
    today = now.date()
    rows = [i for i, d in enumerate(days) if d >= today][:5]
    rowh = 44
    tmin = min(daily["temperature_2m_min"][i] for i in rows)
    tmax = max(daily["temperature_2m_max"][i] for i in rows)
    span = max(tmax - tmin, 1)
    bar_l, bar_r = 300, 440
    for n, i in enumerate(rows):
        y = top + 10 + n * rowh
        cy = y + rowh / 2
        if n:
            c.line([(M, y), (W - M, y)], fill=200, width=1)
        label = "Today" if days[i] == today else days[i].strftime("%a")
        c.text((M + 4, cy), label, font("semibold", 21), anchor="lm")
        draw_icon(c, kind(daily["weather_code"][i]), 130, cy, 36)
        lo, hi = daily["temperature_2m_min"][i], daily["temperature_2m_max"][i]
        c.text((bar_l - 12, cy), f"{round(lo)}°", font("regular", 19), fill=70, anchor="rm")
        c.text((bar_r + 12, cy), f"{round(hi)}°", font("semibold", 19), anchor="lm")
        c.rect((bar_l, cy - 4, bar_r, cy + 4), fill=220, radius=4)
        x0 = bar_l + (lo - tmin) / span * (bar_r - bar_l)
        x1 = bar_l + (hi - tmin) / span * (bar_r - bar_l)
        c.rect((x0, cy - 4, max(x1, x0 + 8), cy + 4), fill=40, radius=4)
        mm = daily["precipitation_sum"][i] or 0
        gust = round(daily["wind_gusts_10m_max"][i])
        c.text((160, cy), f"{mm:.0f} mm" if mm >= 0.5 else "dry", font("regular", 17),
               fill=0 if mm >= 5 else 90, anchor="lm")
        c.text((W - M, cy), f"{gust}", font("medium", 17), fill=0 if gust >= 60 else 90, anchor="rm")
    c.text((W - M, top - 14), "GUSTS km/h", font("semibold", 12), fill=110, anchor="ra")

    # footer: sunrise/sunset. Bottom-right is left clear for the Kindle's battery readout.
    sr = dt.datetime.fromisoformat(daily["sunrise"][rows[0]]).strftime("%H:%M")
    ss = dt.datetime.fromisoformat(daily["sunset"][rows[0]]).strftime("%H:%M")
    c.line([(M, H - 46), (W - M, H - 46)], width=1, fill=160)
    c.text((M, H - 24), f"Sunrise {sr}   Sunset {ss}", font("regular", 16), fill=60, anchor="lm")
    return c.final()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", help="render from a saved Open-Meteo JSON file")
    ap.add_argument("--now", help="override the current time (ISO), for testing")
    ap.add_argument("--out", default=os.path.join(HERE, "out", "weather.png"))
    args = ap.parse_args()
    if args.sample:
        with open(args.sample) as f:
            data = json.load(f)
    else:
        with urllib.request.urlopen(API, timeout=30) as r:
            data = json.load(r)
    now = dt.datetime.fromisoformat(args.now).replace(tzinfo=ZoneInfo(TZ)) if args.now else None
    img = render(data, now)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    img.save(args.out, optimize=True)
    print("wrote", args.out, img.size)


if __name__ == "__main__":
    main()
