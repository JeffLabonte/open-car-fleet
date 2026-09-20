#!/usr/bin/env bash
# Install development/deployment prerequisites for Open Car Fleet.
# Supports Linux (apt/dnf/pacman), macOS (Homebrew), and Windows Subsystem for Linux.
set -euo pipefail

REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=12

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() { printf '\033[1;32m[install-prereqs]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[install-prereqs]\033[0m %s\n' "$*" >&2; }
error() { printf '\033[1;31m[install-prereqs]\033[0m %s\n' "$*" >&2; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

python_version_ok() {
  local python_cmd="${1:-python3}"
  if ! command_exists "$python_cmd"; then
    return 1
  fi
  local version
  version="$($python_cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)"
  if [[ -z "$version" ]]; then
    return 1
  fi
  local major minor
  major="${version%%.*}"
  minor="${version#*.}"
  if [[ "$major" -gt "$REQUIRED_PYTHON_MAJOR" ]] || \
     { [[ "$major" -eq "$REQUIRED_PYTHON_MAJOR" ]] && [[ "$minor" -ge "$REQUIRED_PYTHON_MINOR" ]]; }; then
    return 0
  fi
  return 1
}

ensure_sudo() {
  if [[ "$EUID" -eq 0 ]]; then
    return 0
  fi
  if command_exists sudo; then
    log "Commands will use sudo when needed."
  else
    error "This script needs root privileges on Linux. Please install sudo or run as root."
    exit 1
  fi
}

is_wsl() {
  if [[ -f /proc/version ]] && grep -qiE "(microsoft|wsl)" /proc/version; then
    return 0
  fi
  return 1
}

# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------

ensure_brew() {
  if command_exists brew; then
    return 0
  fi
  log "Homebrew not found. Installing ..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  # Try to activate brew in the current shell for the rest of the script.
  if [[ -f /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -f /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
}

install_python_macos() {
  ensure_brew
  log "Installing Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} via Homebrew ..."
  brew install "python@${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}"
  brew link --force --overwrite "python@${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}" 2>/dev/null || true
}

install_poetry_macos() {
  ensure_brew
  if command_exists poetry; then
    return 0
  fi
  log "Installing Poetry via Homebrew ..."
  brew install poetry
}

install_docker_macos() {
  ensure_brew
  if command_exists docker; then
    return 0
  fi
  log "Installing Docker Desktop via Homebrew Cask ..."
  brew install --cask docker
  warn "Docker Desktop was installed. Please open the Docker app once to start the daemon."
}

# ---------------------------------------------------------------------------
# Linux
# ---------------------------------------------------------------------------

detect_linux_distro() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck source=/dev/null
    . /etc/os-release
    echo "$ID"
  else
    echo "unknown"
  fi
}

install_python_linux_apt() {
  log "Installing Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} via apt ..."
  sudo apt-get update
  sudo apt-get install -y "python${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}" "python${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}-venv" python3-pip
}

install_python_linux_dnf() {
  log "Installing Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} via dnf ..."
  sudo dnf install -y "python${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}"
}

install_python_linux_pacman() {
  log "Installing Python via pacman ..."
  sudo pacman -Syu --noconfirm python
}

install_poetry_linux() {
  if command_exists poetry; then
    return 0
  fi
  log "Installing Poetry via the official installer ..."
  if ! command_exists python3; then
    error "python3 is required to install Poetry but was not found."
    exit 1
  fi
  curl -sSL https://install.python-poetry.org | python3 -
  export PATH="$HOME/.local/bin:$PATH"
  if ! command_exists poetry; then
    warn "Poetry was installed to ~/.local/bin. Add it to your PATH or restart your shell."
  fi
}

install_docker_linux_apt() {
  log "Installing Docker Engine (apt) ..."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc >/dev/null
  local distro_id distro_codename
  # shellcheck source=/dev/null
  . /etc/os-release
  distro_id="$ID"
  distro_codename="$VERSION_CODENAME"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${distro_id} ${distro_codename} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable docker
  sudo systemctl start docker || true
}

install_docker_linux_dnf() {
  log "Installing Docker Engine (dnf) ..."
  sudo dnf -y install dnf-plugins-core
  sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
  sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  sudo systemctl enable docker
  sudo systemctl start docker || true
}

install_docker_linux_pacman() {
  log "Installing Docker (pacman) ..."
  sudo pacman -Syu --noconfirm docker docker-compose
  sudo systemctl enable docker
  sudo systemctl start docker || true
}

install_python_linux() {
  local distro
  distro="$(detect_linux_distro)"
  case "$distro" in
    ubuntu|debian|pop)
      install_python_linux_apt
      ;;
    fedora|rhel|centos|almalinux|rocky)
      install_python_linux_dnf
      ;;
    arch|manjaro)
      install_python_linux_pacman
      ;;
    *)
      error "Unsupported Linux distribution: ${distro:-unknown}"
      error "Please install Python >= ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR} manually."
      exit 1
      ;;
  esac
}

install_docker_linux() {
  local distro
  distro="$(detect_linux_distro)"
  case "$distro" in
    ubuntu|debian|pop)
      install_docker_linux_apt
      ;;
    fedora|rhel|centos|almalinux|rocky)
      install_docker_linux_dnf
      ;;
    arch|manjaro)
      install_docker_linux_pacman
      ;;
    *)
      error "Unsupported Linux distribution: ${distro:-unknown}"
      error "Please install Docker Engine with the Compose plugin manually."
      exit 1
      ;;
  esac
}

# ---------------------------------------------------------------------------
# Windows (native) guidance
# ---------------------------------------------------------------------------

print_windows_instructions() {
  cat <<'EOF'
Windows (native) prerequisite setup
-----------------------------------
This bash script supports Windows Subsystem for Linux (WSL2). For native
Windows, install the tools manually:

1. Python >= 3.12
   winget install Python.Python.3.12

2. Poetry
   Open PowerShell and run:
   (Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
   # Then add %APPDATA%\Python\Scripts to your PATH.

3. Docker Desktop
   winget install Docker.DockerDesktop
   # Start Docker Desktop before running make commands.

4. Make (optional but recommended)
   winget install GnuWin32.Make
   # Or use Git Bash / WSL2 for a full Unix toolchain.

EOF
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

usage() {
  cat <<'EOF'
Usage: scripts/install-prereqs.sh [options]

Installs the prerequisites for Open Car Fleet development/deployment:
  - Python >= 3.12
  - Poetry (Python dependency manager)
  - Docker Engine with the Compose plugin

Options:
  -h, --help    Show this help
EOF
}

main() {
  case "${1:-}" in
    -h|--help)
      usage
      exit 0
      ;;
  esac

  local os
  os="$(uname -s)"

  case "$os" in
    Darwin)
      log "Detected macOS."
      if ! python_version_ok python3; then
        install_python_macos
      else
        log "Python $(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') is already installed."
      fi
      install_poetry_macos
      install_docker_macos
      ;;

    Linux)
      if is_wsl; then
        log "Detected Windows Subsystem for Linux (WSL)."
      else
        log "Detected Linux."
      fi
      ensure_sudo
      if ! python_version_ok python3; then
        install_python_linux
      else
        log "Python $(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")') is already installed."
      fi
      install_poetry_linux
      if ! command_exists docker && ! command_exists podman; then
        install_docker_linux
      else
        log "Container runtime already available: $(docker --version 2>/dev/null || podman --version 2>/dev/null)"
      fi
      ;;

    CYGWIN*|MINGW*|MSYS*)
      log "Detected Windows shell environment."
      print_windows_instructions
      ;;

    *)
      error "Unsupported operating system: $os"
      exit 1
      ;;
  esac

  log "Checking installed tools ..."
  python3 --version
  poetry --version || warn "Poetry is installed but not on the current PATH. Restart your shell."
  docker --version || warn "Docker is installed but may need to be started (Docker Desktop / systemctl)."

  log "Prerequisite installation complete."
  log "Next steps:"
  log "  make install    # install Python dependencies with Poetry"
  log "  make run        # start Postgres, migrate, and run the dev server"
}

main "$@"
