# kindle-weather

A Letterkenny weather dashboard for a jailbroken Kindle 7 (600×800 e-ink).

- `render.py` draws the dashboard from the free [Open-Meteo](https://open-meteo.com) forecast.
- `.github/workflows/render.yml` runs it every 30 minutes and publishes the image to the `output` branch:
  `https://raw.githubusercontent.com/pauricodonnell/kindle-weather/output/weather.png`
- `kindle/` holds the files that go on the Kindle: `weatherdash/` in the root of the Kindle drive, and
  `documents/Weather Dashboard.sh` (tap it in the library to start; press the power button to stop).

Change location with the `PLACE`, `LAT`, `LON` environment variables in the workflow.
