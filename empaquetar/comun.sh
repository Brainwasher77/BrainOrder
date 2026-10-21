#!/bin/bash
# Funciones compartidas por los scripts que arman los instaladores (los corre GitHub Actions).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VER=$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' "$ROOT/version.json" | head -1)

# Python independiente (python-build-standalone): no depende del Python del computador.
# $1 = triple (aarch64-apple-darwin, x86_64-apple-darwin, x86_64-pc-windows-msvc), $2 = carpeta destino
bajar_python() {
  local triple="$1" dest="$2" repo="astral-sh/python-build-standalone" tag asset tmp
  tag=$(gh release view -R "$repo" --json tagName -q .tagName)
  asset=$(gh release view "$tag" -R "$repo" --json assets -q '.assets[].name' \
          | grep -E "^cpython-3\.12\.[0-9]+\+[0-9]+-${triple}-install_only\.tar\.gz$" | sort -V | tail -1)
  [ -n "$asset" ] || { echo "No encontré Python 3.12 para $triple en $repo $tag"; exit 1; }
  echo "Python: $asset"
  tmp=$(mktemp -d)
  gh release download "$tag" -R "$repo" -p "$asset" -D "$tmp"
  tar -xzf "$tmp/$asset" -C "$tmp"
  rm -rf "$dest"; mkdir -p "$(dirname "$dest")"
  mv "$tmp/python" "$dest"
  rm -rf "$tmp"
}

# Código de la app (lo mismo que baja el actualizador, sin lo que no hace falta)
copiar_codigo() {
  local dest="$1"
  rm -rf "$dest"; mkdir -p "$dest"
  (cd "$ROOT" && tar --exclude='./.git' --exclude='./.github' --exclude='./empaquetar' --exclude='./dist' \
     --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' -cf - .) | tar -xf - -C "$dest"
}
