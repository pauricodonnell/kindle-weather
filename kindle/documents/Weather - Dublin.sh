#!/bin/sh
# Name: Weather - Dublin
# Shows the Dublin weather dashboard. Press the power button to leave it.
# Stop a dashboard that is already running (e.g. another place) first.
PID="$(cat /var/tmp/weatherdash.pid 2>/dev/null)"
if [ -n "$PID" ] && kill "$PID" 2>/dev/null; then
    i=0
    while kill -0 "$PID" 2>/dev/null && [ $i -lt 15 ]; do sleep 1; i=$((i + 1)); done
fi
cp -f /mnt/us/weatherdash/dash.sh /var/tmp/weatherdash.sh
chmod 755 /var/tmp/weatherdash.sh
nohup /bin/sh /var/tmp/weatherdash.sh dublin >/dev/null 2>&1 &
