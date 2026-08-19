#!/usr/bin/env bash

# Fallback copy of accelerator-test/hack/ensure-ginkgo.sh. The wrapper prefers
# the helper from the selected accelerator-test checkout and uses this copy for
# older checkouts that do not contain it yet.

ginkgo_log() {
  printf '[ginkgo-preflight] %s\n' "$*" >&2
}

ginkgo_required_version() {
  local repo_root="$1"
  awk '$1 == "github.com/onsi/ginkgo/v2" { print $2; exit }' "${repo_root}/go.mod"
}

ginkgo_cli_version() {
  local binary="$1"
  "${binary}" version 2>/dev/null | awk '/^Ginkgo Version/ { print $3; exit }'
}

go_cli_version() {
  local binary="$1"
  "${binary}" env GOVERSION 2>/dev/null | sed 's/^go//'
}

resolve_executable() {
  local candidate="$1"
  if [[ "${candidate}" == */* ]]; then
    [[ -x "${candidate}" ]] && printf '%s\n' "${candidate}"
    return
  fi
  command -v "${candidate}" 2>/dev/null || true
}

ensure_go() {
  local candidate="${GO_BIN:-go}"
  local resolved=""
  local actual_version=""
  resolved="$(resolve_executable "${candidate}")"
  if [[ -z "${resolved}" ]]; then
    ginkgo_log "go is not available on PATH; accelerator e2e cannot compile or run"
    return 1
  fi
  actual_version="$(go_cli_version "${resolved}")"
  if [[ -z "${actual_version}" ]]; then
    ginkgo_log "failed to determine Go version from ${resolved}"
    return 1
  fi
  ginkgo_log "using ${resolved} (go${actual_version})"
  printf '%s\n' "${resolved}"
}

ensure_ginkgo() {
  local repo_root="${1:-}"
  if [[ -z "${repo_root}" || ! -f "${repo_root}/go.mod" ]]; then
    ginkgo_log "accelerator-test go.mod not found under: ${repo_root:-<empty>}"
    return 1
  fi

  local required_version
  required_version="$(ginkgo_required_version "${repo_root}")"
  if [[ -z "${required_version}" ]]; then
    ginkgo_log "github.com/onsi/ginkgo/v2 version is missing from ${repo_root}/go.mod"
    return 1
  fi

  local candidate="${GINKGO_BIN:-ginkgo}"
  local resolved=""
  local actual_version=""
  resolved="$(resolve_executable "${candidate}")"
  if [[ -n "${resolved}" ]]; then
    actual_version="$(ginkgo_cli_version "${resolved}")"
    if [[ "v${actual_version#v}" == "${required_version}" ]]; then
      ginkgo_log "using ${resolved} (${required_version})"
      printf '%s\n' "${resolved}"
      return 0
    fi
    if [[ "${E2E_ALLOW_GINKGO_VERSION_MISMATCH:-false}" == "true" ]]; then
      ginkgo_log "using version-mismatched ${resolved} (actual=${actual_version:-unknown}, required=${required_version})"
      printf '%s\n' "${resolved}"
      return 0
    fi
    ginkgo_log "ignoring version-mismatched ${resolved} (actual=${actual_version:-unknown}, required=${required_version})"
  else
    ginkgo_log "ginkgo is not available on PATH (required=${required_version})"
  fi

  local home_dir="${HOME:-/tmp}"
  local cache_root="${E2E_TOOL_CACHE_DIR:-${XDG_CACHE_HOME:-${home_dir}/.cache}/accelerator-test/tools}"
  local bin_dir="${cache_root}/ginkgo/${required_version}"
  local installed_bin="${bin_dir}/ginkgo"
  if [[ -x "${installed_bin}" ]]; then
    actual_version="$(ginkgo_cli_version "${installed_bin}")"
    if [[ "v${actual_version#v}" == "${required_version}" ]]; then
      ginkgo_log "using cached ${installed_bin} (${required_version})"
      printf '%s\n' "${installed_bin}"
      return 0
    fi
  fi

  if [[ "${E2E_AUTO_INSTALL_TOOLS:-true}" != "true" ]]; then
    ginkgo_log "automatic tool installation is disabled; run: GOBIN=<dir> go install github.com/onsi/ginkgo/v2/ginkgo@${required_version}"
    return 1
  fi
  if ! command -v go >/dev/null 2>&1; then
    ginkgo_log "go is required to install Ginkgo ${required_version}, but go was not found on PATH"
    return 1
  fi

  mkdir -p "${bin_dir}"
  ginkgo_log "installing github.com/onsi/ginkgo/v2/ginkgo@${required_version} into ${bin_dir}"
  if ! GOBIN="${bin_dir}" go install "github.com/onsi/ginkgo/v2/ginkgo@${required_version}"; then
    ginkgo_log "Ginkgo installation failed; check GOPROXY/network access and Go toolchain availability"
    return 1
  fi

  actual_version="$(ginkgo_cli_version "${installed_bin}")"
  if [[ "v${actual_version#v}" != "${required_version}" ]]; then
    ginkgo_log "installed Ginkgo version mismatch (actual=${actual_version:-unknown}, required=${required_version})"
    return 1
  fi

  ginkgo_log "installed ${installed_bin} (${required_version})"
  printf '%s\n' "${installed_bin}"
}
