#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

action="${1:-install}"
case "$action" in
  install|uninstall) ;;
  *) echo "usage: $0 [install|uninstall]" >&2; exit 2 ;;
esac

py="${PYTHON:-python3}"
staging_dir="${STAGING_DIR:-$repo_root/.build/kb-packaging}"
venv_dir="${VENV_DIR:-$staging_dir/venv}"
build_dir="${BUILD_DIR:-$staging_dir/build}"
dist_dir="${DIST_DIR:-$staging_dir/dist}"
bin_name="${BIN_NAME:-kb}"
install_dir="${INSTALL_DIR:-/usr/local/bin}"
bundle_mode="${BUNDLE_MODE:-onedir}"

payload_dir="${INSTALL_PAYLOAD_DIR:-}"
if [ -z "$payload_dir" ]; then
  case "$install_dir" in
    */bin) payload_dir="${install_dir%/bin}/lib/$bin_name" ;;
    *) payload_dir="$install_dir/$bin_name.payload" ;;
  esac
fi

use_sudo=0
if [ "${NO_SUDO:-}" = "1" ]; then
  use_sudo=0
elif [ -n "${HOME:-}" ] && [ "${install_dir#"$HOME"/}" != "$install_dir" ]; then
  use_sudo=0
elif [ -d "$install_dir" ] && [ -w "$install_dir" ]; then
  use_sudo=0
else
  use_sudo=1
fi

run_mkdir_p() {
  if [ "$use_sudo" = "1" ]; then
    sudo mkdir -p "$@"
  else
    mkdir -p "$@"
  fi
}

run_rm_rf() {
  if [ "$use_sudo" = "1" ]; then
    sudo rm -rf "$@"
  else
    rm -rf "$@"
  fi
}

run_rm_f() {
  if [ "$use_sudo" = "1" ]; then
    sudo rm -f "$@"
  else
    rm -f "$@"
  fi
}

if ! command -v "$py" >/dev/null 2>&1; then
  echo "error: python not found: $py" >&2
  exit 1
fi

case "$bundle_mode" in
  onedir|onefile) ;;
  *) echo "error: invalid BUNDLE_MODE: $bundle_mode (onedir|onefile)" >&2; exit 2 ;;
esac

case "$install_dir" in
  ""|"/") echo "error: unsafe INSTALL_DIR: $install_dir" >&2; exit 1 ;;
esac

case "$payload_dir" in
  ""|"/") echo "error: unsafe INSTALL_PAYLOAD_DIR: $payload_dir" >&2; exit 1 ;;
esac

if [ "$action" = "uninstall" ]; then
  if [ -d "$payload_dir" ]; then
    run_rm_rf "$payload_dir"
    echo "removed: $payload_dir"
  fi

  if [ -e "$install_dir/$bin_name" ] || [ -L "$install_dir/$bin_name" ]; then
    run_rm_f "$install_dir/$bin_name"
    echo "removed: $install_dir/$bin_name"
  fi

  parent_dir="$(dirname "$payload_dir")"
  if [ -d "$parent_dir" ]; then
    if [ "$use_sudo" = "1" ]; then
      sudo rmdir "$parent_dir" 2>/dev/null || true
    else
      rmdir "$parent_dir" 2>/dev/null || true
    fi
  fi

  exit 0
fi

case "$staging_dir" in
  "" | "/" | "$repo_root") echo "error: unsafe STAGING_DIR: $staging_dir" >&2; exit 1 ;;
esac

rm -rf "$staging_dir"
mkdir -p "$staging_dir"

cleanup() {
  status=$?
  if [ "$status" -eq 0 ] && [ "${KEEP_BUILD:-}" != "1" ]; then
    rm -rf "$staging_dir"
    echo "cleaned: $staging_dir"
    default_build_parent="$repo_root/.build"
    case "$staging_dir" in
      "$default_build_parent"/*) rmdir "$default_build_parent" 2>/dev/null || true ;;
    esac
  fi
}
trap cleanup EXIT

export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$staging_dir/pip-cache}"
export PYTHONDONTWRITEBYTECODE=1
export TMPDIR="${TMPDIR:-$staging_dir/tmp}"
mkdir -p "$TMPDIR"

"$py" -m venv "$venv_dir"
"$venv_dir/bin/python" -m pip -q install --upgrade pip
"$venv_dir/bin/python" -m pip -q install --upgrade pyinstaller

mkdir -p "$build_dir" "$dist_dir"

export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$staging_dir/pyinstaller-config}"

if [ "$bundle_mode" = "onefile" ]; then
  "$venv_dir/bin/python" -m PyInstaller \
    --clean \
    --noconfirm \
    --onefile \
    --name "$bin_name" \
    --distpath "$dist_dir" \
    --workpath "$build_dir" \
    --specpath "$build_dir" \
    scripts/pyinstaller_entry.py

  if [ ! -f "$dist_dir/$bin_name" ]; then
    echo "error: build failed, missing: $dist_dir/$bin_name" >&2
    exit 1
  fi

  run_mkdir_p "$install_dir"
  if [ "$use_sudo" = "1" ]; then
    sudo install -m 0755 "$dist_dir/$bin_name" "$install_dir/$bin_name"
  else
    install -m 0755 "$dist_dir/$bin_name" "$install_dir/$bin_name"
  fi

  echo "installed: $install_dir/$bin_name"
  "$install_dir/$bin_name" --help >/dev/null
  echo "ok: $bin_name --help"
  exit 0
fi

"$venv_dir/bin/python" -m PyInstaller \
  --clean \
  --noconfirm \
  --onedir \
  --name "$bin_name" \
  --distpath "$dist_dir" \
  --workpath "$build_dir" \
  --specpath "$build_dir" \
  scripts/pyinstaller_entry.py

if [ ! -d "$dist_dir/$bin_name" ]; then
  echo "error: build failed, missing: $dist_dir/$bin_name" >&2
  exit 1
fi

run_mkdir_p "$(dirname "$payload_dir")"
run_rm_rf "$payload_dir"

if [ "$use_sudo" = "1" ]; then
  sudo cp -R "$dist_dir/$bin_name" "$payload_dir"
else
  cp -R "$dist_dir/$bin_name" "$payload_dir"
fi

run_mkdir_p "$install_dir"
run_rm_f "$install_dir/$bin_name"
if [ "$use_sudo" = "1" ]; then
  sudo ln -s "$payload_dir/$bin_name" "$install_dir/$bin_name"
else
  ln -s "$payload_dir/$bin_name" "$install_dir/$bin_name"
fi

echo "installed: $install_dir/$bin_name -> $payload_dir/$bin_name"
"$install_dir/$bin_name" --help >/dev/null
echo "ok: $bin_name --help"
