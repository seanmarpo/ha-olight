#!/usr/bin/env bash
# Bring up an Android emulator with the Olight app installed and capture the station's device id
# and local key from the Tuya SDK's log. Fully local: no phone, no Tuya cloud account.
#
# The one thing it cannot do for you is sign in — the key is only decrypted after you log into the
# Olight account your station is paired to. The script boots the emulator, installs the app, opens
# it, then sits on the log until the key appears; you sign in inside the emulator window when told.
#
#   ./tools/extract_key.sh              # macOS (Intel or Apple Silicon) or Linux with KVM
#   ANDROID_SDK_ROOT=~/sdk ./tools/extract_key.sh
#   PLAYSTORE=1 ./tools/extract_key.sh                          # install Olight from Google Play
#   OLIGHT_APK=~/Downloads/olight.xapk ./tools/extract_key.sh   # use an app file you downloaded
#
# Output: prints the device id and local key, and writes them to tools/ostation-key.env.
set -euo pipefail

APP_PKG="com.olight.omall"
API_LEVEL="${API_LEVEL:-34}"
PLAYSTORE="${PLAYSTORE:-0}"
OLIGHT_APK="${OLIGHT_APK:-}"
if [ "$PLAYSTORE" = 1 ]; then AVD_NAME="${AVD_NAME:-olight-play}"; else AVD_NAME="${AVD_NAME:-olight}"; fi
SDK="${ANDROID_SDK_ROOT:-$HOME/android-sdk}"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

# --- host / architecture ------------------------------------------------------------------------
case "$(uname -s)" in
  Darwin) HOST=mac ;;
  Linux)  HOST=linux; [ -e /dev/kvm ] || die "no /dev/kvm — the emulator needs hardware virtualisation" ;;
  *) die "unsupported OS $(uname -s)" ;;
esac
case "$(uname -m)" in
  arm64|aarch64) ABI=arm64-v8a ;;
  x86_64)        ABI=x86_64 ;;
  *) die "unsupported CPU $(uname -m)" ;;
esac
if [ "$PLAYSTORE" = 1 ]; then TAG=google_apis_playstore; else TAG=google_apis; fi
IMAGE="system-images;android-${API_LEVEL};${TAG};${ABI}"
say "host=$HOST abi=$ABI image=$IMAGE sdk=$SDK"

# --- Java ---------------------------------------------------------------------------------------
if ! command -v java >/dev/null; then
  say "installing a Java runtime"
  if [ "$HOST" = mac ]; then
    command -v brew >/dev/null || die "install Homebrew first (https://brew.sh) or a JDK 17+"
    brew install --cask temurin
  else
    sudo apt-get update -qq && sudo apt-get install -y -qq default-jre-headless
  fi
fi

# --- Android command-line tools ---------------------------------------------------------------
export ANDROID_SDK_ROOT="$SDK" ANDROID_HOME="$SDK"
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$SDK/emulator:$PATH"
if ! command -v sdkmanager >/dev/null; then
  say "downloading Android command-line tools into $SDK"
  mkdir -p "$SDK/cmdline-tools"
  # Google publishes one zip per host; the build number changes, so resolve it from the index page.
  # macOS zips are per-arch (mac_arm64 / mac_x86_64) on current releases, plain "mac" on older ones.
  case "$HOST-$ABI" in
    mac-arm64-v8a) CLT_HOSTS="mac_arm64 mac" ;;
    mac-x86_64)    CLT_HOSTS="mac_x86_64 mac" ;;
    *)             CLT_HOSTS="$HOST" ;;
  esac
  page=$(curl -fsSL https://developer.android.com/studio) || die "could not reach developer.android.com"
  url=""
  for h in $CLT_HOSTS; do
    url=$(printf '%s' "$page" | grep -oE "https://dl.google.com/android/repository/commandlinetools-${h}-[0-9]+_latest.zip" | head -1 || true)
    [ -n "$url" ] && break
  done
  [ -n "$url" ] || die "could not find the command-line tools download URL (tried: $CLT_HOSTS)"
  curl -fsSL "$url" -o "$WORK/clt.zip"
  unzip -q "$WORK/clt.zip" -d "$WORK/clt"
  rm -rf "$SDK/cmdline-tools/latest" && mv "$WORK/clt/cmdline-tools" "$SDK/cmdline-tools/latest"
fi

say "installing platform-tools, emulator and the system image (a few GB, once)"
yes | sdkmanager --licenses >/dev/null 2>&1 || true
sdkmanager --install "platform-tools" "emulator" "$IMAGE" >/dev/null

# --- AVD ----------------------------------------------------------------------------------------
if ! avdmanager list avd 2>/dev/null | grep -q "Name: ${AVD_NAME}\$"; then
  say "creating emulator '$AVD_NAME'"
  echo no | avdmanager create avd -n "$AVD_NAME" -k "$IMAGE" -d pixel_6 >/dev/null
fi

# --- the app ------------------------------------------------------------------------------------
# Three sources: Google Play inside the emulator (PLAYSTORE=1), a file you downloaded (OLIGHT_APK),
# or an automatic APKPure download (often refused for scripts — it then points at the other two).
mkdir -p "$WORK/xapk"
if [ "$PLAYSTORE" = 1 ]; then
  say "Play Store mode: you will install Olight from Google Play inside the emulator"
elif [ -n "$OLIGHT_APK" ]; then
  [ -f "$OLIGHT_APK" ] || die "OLIGHT_APK=$OLIGHT_APK does not exist"
  case "$OLIGHT_APK" in
    *.apk) cp "$OLIGHT_APK" "$WORK/xapk/base.apk" ;;
    *)     unzip -q "$OLIGHT_APK" -d "$WORK/xapk" ;;   # .xapk / .apks / .apkm bundles are zips
  esac
  ls "$WORK/xapk"/*.apk >/dev/null 2>&1 || die "no .apk found inside $OLIGHT_APK"
else
  say "downloading the Olight app"
  curl -fsSL -A "Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36" \
    "https://d.apkpure.com/b/XAPK/${APP_PKG}?version=latest" -o "$WORK/olight.xapk" \
    || die "the automatic app download was refused. Re-run with PLAYSTORE=1 (install Olight from
       Google Play inside the emulator), or download the app yourself and pass OLIGHT_APK=/path/to/file"
  unzip -q "$WORK/olight.xapk" -d "$WORK/xapk"
  ls "$WORK/xapk"/*.apk >/dev/null 2>&1 || die "the download was not an XAPK bundle; re-run with PLAYSTORE=1 or OLIGHT_APK=/path/to/file"
fi

# --- boot ---------------------------------------------------------------------------------------
say "booting the emulator (this window is where you will sign in)"
emulator -avd "$AVD_NAME" -no-snapshot -no-boot-anim -gpu auto >/dev/null 2>&1 &
EMU_PID=$!
trap 'kill $EMU_PID 2>/dev/null || true; rm -rf "$WORK"' EXIT
adb wait-for-device
until [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do sleep 3; done
sleep 5

if [ "$PLAYSTORE" = 1 ]; then
  echo
  echo "  In the emulator window: open the Play Store, sign in with any Google account,"
  echo "  install \"Olight\" and open it."
else
  say "installing the app"
  # The bundle ships an arm64 split. On an x86_64 image Google's ARM translation layer runs it;
  # install-multiple takes the base plus every split in one go.
  adb install-multiple -r "$WORK"/xapk/*.apk >/dev/null
  adb shell monkey -p "$APP_PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1 || true
fi

# --- capture ------------------------------------------------------------------------------------
cat <<EOF

  ┌──────────────────────────────────────────────────────────────────────────────┐
  │  In the emulator window: sign into the Olight account your station is       │
  │  paired to, and wait for the station to appear in the app.                   │
  │                                                                              │
  │  This terminal is watching the log. When the key shows up it prints here    │
  │  and the script exits. If nothing appears within a minute of the station    │
  │  being listed, force-stop and reopen the app so it re-syncs.                │
  └──────────────────────────────────────────────────────────────────────────────┘

EOF
adb logcat -c
DEVICE_ID=""; LOCAL_KEY=""
while IFS= read -r line; do
  id=$(printf '%s' "$line" | grep -oE 'deviceId[:= ]+[A-Za-z0-9]{22}' | grep -oE '[A-Za-z0-9]{22}$' || true)
  key=$(printf '%s' "$line" | grep -oiE 'localkey[:= ]+[A-Za-z0-9]{16}' | grep -oE '[A-Za-z0-9]{16}$' || true)
  [ -n "$id" ]  && DEVICE_ID="$id"
  [ -n "$key" ] && LOCAL_KEY="$key"
  if [ -n "$DEVICE_ID" ] && [ -n "$LOCAL_KEY" ]; then
    printf 'OSTATION_DEVICE_ID=%s\nOSTATION_LOCAL_KEY=%s\n' "$DEVICE_ID" "$LOCAL_KEY" > "$OUT_DIR/ostation-key.env"
    say "device id : $DEVICE_ID"
    say "local key : $LOCAL_KEY"
    say "saved to $OUT_DIR/ostation-key.env — now find the station's IP and add it in Home Assistant"
    exit 0
  fi
done < <(adb logcat -v raw -s Thing-Network:D)
