#!/bin/sh
# Build the 32-bit proxy version.dll with MinGW-w64.
# Override the tools if needed, e.g. in an MSYS2 MINGW32 shell:
#   CC=gcc STRIP=strip ./build.sh
set -e
CC=${CC:-i686-w64-mingw32-gcc}
STRIP=${STRIP:-i686-w64-mingw32-strip}
"$CC" -O2 -Wall -Wno-unused-function -shared -static-libgcc \
  -o version.dll topwd.c -Wl,--kill-at -Wl,--enable-stdcall-fixup \
  -lsetupapi -lole32 -ladvapi32
"$STRIP" version.dll
echo "built version.dll"
