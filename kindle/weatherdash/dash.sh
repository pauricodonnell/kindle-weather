#!/bin/sh
# Weather dashboard for a jailbroken Kindle (tested layout: Kindle 7th gen, FW 5.12.2.2, 600x800).
# Downloads a pre-rendered PNG every REFRESH seconds and shows it full screen.
# Press the power button to leave the dashboard and return to the normal Kindle.

# Usage: dash.sh <place>   e.g. dash.sh inver  (matches a name in locations.json, lowercase)
# ---- settings (edit config.sh rather than this file) ----
PLACE="${1:-inver}"
BASE="https://raw.githubusercontent.com/pauricodonnell/kindle-weather/output"
REFRESH=1800          # seconds between updates
WIFI_OFF_BETWEEN=yes  # turn Wi-Fi off between updates to save battery
[ -f /mnt/us/weatherdash/config.sh ] && . /mnt/us/weatherdash/config.sh
URL="$BASE/$PLACE.png"

WORK=/var/tmp/weatherdash
IMG=$WORK/$PLACE.png
PIDFILE=/var/tmp/weatherdash.pid
STOPFILE=/var/tmp/weatherdash.stop
LOG=/mnt/us/weatherdash/dash.log
CA=/mnt/us/koreader/data/ca-bundle.crt

mkdir -p "$WORK"
# Run fbink from /var/tmp so we keep working even if the USB drive is unmounted
for f in /mnt/us/libkh/bin/fbink /mnt/us/koreader/fbink; do
    [ -x "$f" ] && { cp -f "$f" "$WORK/fbink"; chmod 755 "$WORK/fbink"; break; }
done
FBINK=$WORK/fbink

log() { echo "$(date '+%F %T') $*" >> "$LOG" 2>/dev/null; }

show_image() {
    if [ -x "$FBINK" ]; then
        "$FBINK" -q -c -f -g file="$1",halign=CENTER,valign=CENTER
    else
        eips -c; eips -f -g "$1"
    fi
}

show_text() {  # bottom-right status text, e.g. battery
    if [ -x "$FBINK" ]; then
        "$FBINK" -q -S 2 -y -2 -x "$2" "$1"
    else
        eips 24 38 "$1"
    fi
}

wifi_on() {
    lipc-set-prop com.lab126.cmd wirelessEnable 1 2>/dev/null
    i=0
    while [ $i -lt 45 ]; do
        [ "$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)" = "CONNECTED" ] && { sleep 2; return 0; }
        sleep 1; i=$((i + 1))
    done
    return 1
}

wifi_off() {
    [ "$WIFI_OFF_BETWEEN" = "yes" ] && lipc-set-prop com.lab126.cmd wirelessEnable 0 2>/dev/null
}

fetch() {
    rm -f "$IMG.new"
    for opt in "--cacert $CA" ""; do
        if curl -fsSL --max-time 60 $opt -o "$IMG.new" "$URL?t=$(date +%s)" 2>>"$LOG" && [ -s "$IMG.new" ]; then
            mv -f "$IMG.new" "$IMG"; return 0
        fi
    done
    return 1
}

take_over() {
    # Same approach KOReader uses on this firmware: hide the status bar,
    # pause the window manager so it can't draw over us, stop USB-drive mode.
    lipc-set-prop com.lab126.pillow disableEnablePillow disable 2>/dev/null
    killall -STOP awesome 2>/dev/null
    killall -STOP volumd 2>/dev/null
    lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
}

give_back() {
    log "stopping"
    killall -CONT volumd 2>/dev/null
    killall -CONT awesome 2>/dev/null
    lipc-set-prop com.lab126.pillow disableEnablePillow enable 2>/dev/null
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 2>/dev/null
    lipc-set-prop com.lab126.cmd wirelessEnable 1 2>/dev/null
    for f in "$WORK/key.pid" "$WORK/lipc.pid"; do
        [ -f "$f" ] && kill "$(cat "$f")" 2>/dev/null
        rm -f "$f"
    done
    rm -f "$PIDFILE" "$STOPFILE"
    # Ask the Kindle to redraw its home screen
    lipc-set-prop com.lab126.appmgrd start app://com.lab126.booklet.home 2>/dev/null
}

# ---- start ----
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    exit 0  # already running
fi
echo $$ > "$PIDFILE"
rm -f "$STOPFILE"
# keep the log small
[ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 100000 ] && tail -c 20000 "$LOG" > "$LOG.tmp" && mv -f "$LOG.tmp" "$LOG"
log "starting $PLACE (refresh ${REFRESH}s)"

trap 'give_back; exit 0' TERM INT HUP

# Power button = leave the dashboard. Two independent watchers; whichever fires
# first creates $STOPFILE. A watcher that fails to start just never fires.
# 1) The power key itself, read straight from the hardware: any press ends this dd.
KEYDEV=""
for ev in /sys/class/input/event*; do
    if grep -qiE "onkey|power" "$ev/device/name" 2>/dev/null; then KEYDEV="/dev/input/${ev##*/}"; break; fi
done
[ -z "$KEYDEV" ] && KEYDEV=/dev/input/event0
sh -c "echo \$\$ > $WORK/key.pid; exec dd if=$KEYDEV of=/dev/null bs=16 count=1" 2>/dev/null \
    && touch "$STOPFILE" &
# 2) The Kindle's own "going to sleep" signal, as a backup.
sh -c "echo \$\$ > $WORK/lipc.pid; exec lipc-wait-event com.lab126.powerd goingToScreenSaver" >/dev/null 2>&1 \
    && touch "$STOPFILE" &
sleep 1
if kill -0 "$(cat "$WORK/key.pid" 2>/dev/null)" 2>/dev/null; then
    log "watching power key on $KEYDEV"
else
    log "WARNING: could not watch the power key ($KEYDEV)"
fi

take_over
[ -f "$IMG" ] && show_image "$IMG"

while [ ! -f "$STOPFILE" ]; do
    status=""
    if wifi_on && fetch; then
        log "updated"
    else
        log "update failed"
        status="offline "
    fi
    wifi_off
    if [ -f "$IMG" ]; then
        show_image "$IMG"
        batt="$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)"
        [ "$(lipc-get-prop com.lab126.powerd isCharging 2>/dev/null)" = "1" ] && batt="${batt}+"
        txt="${status}${batt}%"
        show_text "$txt" $((37 - ${#txt}))
    fi
    # wait, checking every 5 s whether the power button was pressed
    waited=0
    while [ $waited -lt "$REFRESH" ] && [ ! -f "$STOPFILE" ]; do
        sleep 5; waited=$((waited + 5))
    done
done

give_back
