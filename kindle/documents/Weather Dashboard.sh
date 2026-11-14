#!/bin/sh
# Name: Weather Dashboard
# Starts the weather dashboard. Press the power button to leave it.
cp -f /mnt/us/weatherdash/dash.sh /var/tmp/weatherdash.sh
chmod 755 /var/tmp/weatherdash.sh
nohup /bin/sh /var/tmp/weatherdash.sh >/dev/null 2>&1 &
