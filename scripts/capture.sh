#!/usr/bin/env bash
# capture.sh: one App Store screenshot from the iOS Simulator, rendered by the app itself at native size.
#
#   capture.sh --device "iPhone 17" --bundle-id com.example.app --out shots/en-US/iphone/hero.png \
#              [--app path/to/App.app] [--appearance light|dark] [--language en] [--locale en_US] \
#              [--pref KEY=TYPE:VALUE ...] [--time 9:41|ISO-8601] [--expect 9:41] [--settle 4] \
#              [--reboot] [--keep-overrides] [--no-statusbar-check] [-- APP LAUNCH ARGS ...]
#
#   --udid UDID          instead of --device NAME (first available simulator with that exact name)
#   --pref KEY=TYPE:VAL  written into the APP'S CONTAINER plist (TYPE: bool|int|float|string), e.g.
#                        --pref useSamplePhotos=bool:true. `simctl spawn defaults write <bundle-id>` writes the
#                        simulator's global domain, which a sandboxed app never reads; this path is the one that works.
#   -- ARGS              passed to the app at launch, e.g. -- -ScreenshotScene search  (scene args are DEBUG-only
#                        app code that stages sample content; they must never unlock features or fake results)
#   --time               status bar time; an ISO-8601 timestamp also fixes the date iPad shows next to the time
#   --expect             text the status bar must show (default 9:41). Checked with Vision OCR on the top band;
#                        on failure the simulator is rebooted once and the capture retried (a long-running headless
#                        simulator can draw a black outlined pill instead of the status bar).
#
# Requires Xcode command line tools. Exit codes: 0 ok, 2 usage, 3 simulator/app error, 4 status bar check failed.
set -euo pipefail

DEVICE="" UDID="" BUNDLE="" APP="" OUT="" APPEAR="light" LANG_CODE="" LOCALE_CODE="" TIME="9:41" EXPECT="9:41"
SETTLE=4 REBOOT=0 KEEP=0 CHECK=1
PREFS=() LAUNCH_ARGS=()
die() { echo "capture.sh: $*" >&2; exit "${2:-3}"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) DEVICE="$2"; shift 2;;
    --udid) UDID="$2"; shift 2;;
    --bundle-id) BUNDLE="$2"; shift 2;;
    --app) APP="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --appearance) APPEAR="$2"; shift 2;;
    --language) LANG_CODE="$2"; shift 2;;
    --locale) LOCALE_CODE="$2"; shift 2;;
    --pref) PREFS+=("$2"); shift 2;;
    --time) TIME="$2"; shift 2;;
    --expect) EXPECT="$2"; shift 2;;
    --settle) SETTLE="$2"; shift 2;;
    --reboot) REBOOT=1; shift;;
    --keep-overrides) KEEP=1; shift;;
    --no-statusbar-check) CHECK=0; shift;;
    --) shift; LAUNCH_ARGS=("$@"); break;;
    -h|--help) sed -n '2,24p' "$0"; exit 0;;
    *) die "unknown argument $1" 2;;
  esac
done
[[ -n "$BUNDLE" && -n "$OUT" ]] || die "need --bundle-id and --out" 2
[[ -n "$UDID" || -n "$DEVICE" ]] || die "need --device NAME or --udid UDID" 2
[[ "$APPEAR" == light || "$APPEAR" == dark ]] || die "--appearance light|dark" 2

if [[ -z "$UDID" ]]; then
  UDID=$(xcrun simctl list devices available -j | /usr/bin/python3 -c '
import json, sys
name = sys.argv[1]
devs = [d for rt in json.load(sys.stdin)["devices"].values() for d in rt if d["name"] == name]
devs.sort(key=lambda d: d["state"] != "Booted")
print(devs[0]["udid"] if devs else "")' "$DEVICE")
  [[ -n "$UDID" ]] || die "no available simulator named '$DEVICE' (xcrun simctl list devices available)"
fi
state() { xcrun simctl list devices -j | /usr/bin/python3 -c '
import json, sys
u = sys.argv[1]
print(next((d["state"] for rt in json.load(sys.stdin)["devices"].values() for d in rt if d["udid"] == u), "?"))' "$UDID"; }

boot() {
  [[ "$(state)" == Booted ]] || xcrun simctl boot "$UDID" >/dev/null 2>&1 || true
  xcrun simctl bootstatus "$UDID" -b >/dev/null
}
reboot_sim() { echo "rebooting simulator $UDID" >&2; xcrun simctl shutdown "$UDID" >/dev/null 2>&1 || true; boot; }

overrides() {
  xcrun simctl status_bar "$UDID" override --time "$TIME" --dataNetwork wifi --wifiMode active --wifiBars 3 \
    --cellularMode active --cellularBars 4 --operatorName "" --batteryState charged --batteryLevel 100
  xcrun simctl ui "$UDID" appearance "$APPEAR"
}
cleanup() { [[ $KEEP == 1 ]] || xcrun simctl status_bar "$UDID" clear >/dev/null 2>&1 || true; }
trap cleanup EXIT

write_prefs() {
  [[ ${#PREFS[@]} -gt 0 ]] || return 0
  local container plist kv key tv type val
  container=$(xcrun simctl get_app_container "$UDID" "$BUNDLE" data 2>/dev/null) \
    || die "app $BUNDLE is not installed on $UDID (pass --app, or install it first)"
  plist="$container/Library/Preferences/$BUNDLE"
  xcrun simctl terminate "$UDID" "$BUNDLE" >/dev/null 2>&1 || true
  for kv in "${PREFS[@]}"; do
    key="${kv%%=*}"; tv="${kv#*=}"; type="${tv%%:*}"; val="${tv#*:}"
    [[ "$key" != "$kv" && "$type" != "$tv" ]] || die "--pref wants KEY=TYPE:VALUE, got $kv" 2
    xcrun simctl spawn "$UDID" defaults write "$plist" "$key" "-$type" "$val"
  done
}

launch() {
  local args=()
  [[ -n "$LANG_CODE" ]] && args+=(-AppleLanguages "($LANG_CODE)")
  [[ -n "$LOCALE_CODE" ]] && args+=(-AppleLocale "$LOCALE_CODE")
  xcrun simctl launch --terminate-running-process "$UDID" "$BUNDLE" ${args[@]+"${args[@]}"} \
    ${LAUNCH_ARGS[@]+"${LAUNCH_ARGS[@]}"} >/dev/null
  sleep "$SETTLE"
}

OCR_BIN="${TMPDIR:-/tmp}/app-store-kit-ocr"
ocr_top() {  # prints the text Vision reads in the top band of $1
  if [[ ! -x "$OCR_BIN" ]]; then
    local src="${OCR_BIN}.swift"
    cat >"$src" <<'SWIFT'
import Foundation
import Vision
import AppKit
let a = CommandLine.arguments
guard a.count > 1, let img = NSImage(contentsOfFile: a[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { exit(2) }
let band = max(60, cg.height * 6 / 100)
guard let top = cg.cropping(to: CGRect(x: 0, y: 0, width: cg.width, height: min(band, cg.height))) else { exit(2) }
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false
try VNImageRequestHandler(cgImage: top).perform([req])
print((req.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: " "))
SWIFT
    xcrun swiftc -O -o "$OCR_BIN" "$src" >/dev/null 2>&1 || { echo "(OCR unavailable)"; return 0; }
  fi
  "$OCR_BIN" "$1" || echo "(OCR failed)"
}

shoot() {
  mkdir -p "$(dirname "$OUT")"
  xcrun simctl io "$UDID" screenshot --type=png "$OUT" >/dev/null 2>&1
}

status_ok() {
  [[ $CHECK == 1 ]] || return 0
  local txt; txt=$(ocr_top "$OUT")
  if [[ "$txt" == "(OCR unavailable)" || "$txt" == "(OCR failed)" ]]; then
    echo "warning: could not OCR the status bar; check $OUT by eye" >&2; return 0
  fi
  [[ "$txt" == *"$EXPECT"* ]] || { echo "status bar reads '$txt', expected '$EXPECT'" >&2; return 1; }
}

if [[ $REBOOT == 1 ]]; then reboot_sim; else boot; fi
if [[ -n "$APP" ]]; then xcrun simctl install "$UDID" "$APP"; fi
overrides
write_prefs
launch
shoot
if ! status_ok; then
  reboot_sim; overrides; write_prefs; launch; shoot
  status_ok || die "status bar still wrong after a reboot; see $OUT" 4
fi
size=$(sips -g pixelWidth -g pixelHeight "$OUT" 2>/dev/null | awk '/pixel/{print $2}' | paste -sd x -)
echo "$OUT  ${size}  udid=$UDID appearance=$APPEAR${LANG_CODE:+ lang=$LANG_CODE}${LOCALE_CODE:+ locale=$LOCALE_CODE}"
