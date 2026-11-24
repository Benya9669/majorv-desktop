#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(tr -d '\r\n' < VERSION)
[[ "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]
test "$(dpkg --print-architecture)" = amd64
test -x dist/majorv-desktop/majorv-desktop
test -x dist/majorv-desktop/majorv-eq

stage=$(mktemp -d)
trap 'rm -rf -- "$stage"' EXIT
mkdir -p "$stage/DEBIAN" "$stage/opt" "$stage/usr/bin" "$stage/usr/share/applications" dist/release
cp -a dist/majorv-desktop "$stage/opt/"
ln -s /opt/majorv-desktop/majorv-desktop "$stage/usr/bin/majorv-desktop"
install -Dm644 majorv/assets/majorv.png "$stage/usr/share/pixmaps/majorv-desktop.png"
cat > "$stage/usr/share/applications/majorv-desktop.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Major V Desktop
Comment=Marshall Major V headphone controls
Comment[ru]=Управление наушниками Marshall Major V
Exec=/opt/majorv-desktop/majorv-desktop
Icon=majorv-desktop
Terminal=false
Categories=AudioVideo;Audio;
EOF
cat > "$stage/DEBIAN/control" <<EOF
Package: majorv-desktop
Version: $version
Section: sound
Priority: optional
Architecture: amd64
Maintainer: Benya9669 <Benya9669@users.noreply.github.com>
Depends: bluez, libc6 (>= 2.39), libdbus-1-3, libegl1, libgl1, libfontconfig1, libglib2.0-0t64, libgssapi-krb5-2, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-keysyms1, libxcb-shape0, libxcb-xinerama0
Description: Desktop controls for Marshall Major V headphones
 Read battery and equalizer settings and manage connected headphones.
EOF
dpkg-deb --root-owner-group -Zgzip -z5 --build "$stage" "dist/release/majorv-desktop_${version}_amd64.deb"
