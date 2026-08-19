#!/bin/bash

# Usage:
# export PLATFORM_USERNAME='ACP platform user name'
# export PLATFORM_PASSWORD='ACP platform password'
# export PLATFORM_ADDRESS='ACP platform address'

# Optional, clusters to upload the package, default: global
# export CLUSTERS='集群名,逗号分割'

# Optional, whether to package images
# export SKIP_PACKAGE_IMAGES=false

# Optional, arch of the image, default: dual
# export PACKAGE_PLATFORMS=linux/amd64

#bash violet-sync.sh "chart或bundle的制品"


set -e

ARTIFACT="${1:-}"

if [ -z "${ARTIFACT}" ]; then
  echo "Usage: $0 <artifact>"
  exit 1
fi

if [ -z "${PLATFORM_ADDRESS}" ]; then
  PLATFORM_ADDRESS=$(kubectl get productbases base -o jsonpath='{.spec.platformURL}')
fi

if [ -z "${PLATFORM_USERNAME}" ] || [ -z "${PLATFORM_PASSWORD}" ]; then
  echo "PLATFORM_USERNAME and PLATFORM_PASSWORD are required"
  exit 1
fi

SKIP_PACKAGE_IMAGES="${SKIP_PACKAGE_IMAGES:-true}"

PACKAGE_PLATFORMS="${PACKAGE_PLATFORMS:-dual}"

CLUSTERS="${CLUSTERS:-global}"

VIOLET="/usr/local/bin/violet"

PATH="/tmp/bin:${PATH}"

if ! [ -f "${VIOLET}" ] || ! [ -s "${VIOLET}" ] || ! [ -x "${VIOLET}" ] || ! "${VIOLET}" version > /dev/null 2>&1; then
  case "$(uname -s)" in
    Darwin)  os=darwin ;;
    Linux)   os=linux ;;
    *)       echo "Unsupported OS: $(uname -s)"; exit 1 ;;
  esac
  case "$(uname -m)" in
    amd64|x86_64)  arch=amd64 ;;
    arm64|aarch64) arch=arm64 ;;
    *)       echo "Unsupported arch: $(uname -m)"; exit 1 ;;
  esac

  mkdir -p /tmp/bin

  curl -o "${VIOLET}" "http://package-minio.alauda.cn:9199/packages/violet/latest/violet_${os}_${arch}"
  chmod +x "${VIOLET}"
fi


if [[ "${ARTIFACT}" == build-harbor.alauda.cn* ]]; then
  ARTIFACT="152-231-registry.alauda.cn:60070${ARTIFACT#build-harbor.alauda.cn}"
fi

TMP_DIR=$(mktemp -d)

cd "${TMP_DIR}"
OUTPUT_FILE="output.tgz"

rm -rf "${OUTPUT_FILE}"


if [ "${SKIP_PACKAGE_IMAGES}" = "true" ]; then
  SKIP_PACKAGE_IMAGES_ARG="--skip-package-images"
else
  SKIP_PACKAGE_IMAGES_ARG=""
fi

if [ "${PACKAGE_PLATFORMS}" = "dual" ]; then
  #PLATFORM_ARG="--platforms=linux/amd64 --platforms=linux/arm64"
  PLATFORM_ARG="--platforms=linux/amd64,linux/arm64"
else
  PLATFORM_ARG="--platforms=${PACKAGE_PLATFORMS}"
fi

violet create --debug "output" ${SKIP_PACKAGE_IMAGES_ARG} --default-catalog-source=platform "${PLATFORM_ARG}" --artifact="${ARTIFACT}"

violet package --debug "output" --no-auth --output="${OUTPUT_FILE}"

violet push --debug --force --clusters="${CLUSTERS}" --platform-address="${PLATFORM_ADDRESS}" --platform-username="${PLATFORM_USERNAME}" --platform-password="${PLATFORM_PASSWORD}" "${OUTPUT_FILE}"

cd -
rm -rf "${TMP_DIR}"
