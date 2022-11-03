#!/usr/bin/env bash

DIR="${BASH_SOURCE%/*}"
if [[ ! -d "$DIR" ]]; then DIR="$PWD"; fi

set -a
source $DIR/local.config
set +a

if [[ -d "$CONFIG_ORIGIN" ]]; then
  rm -rf $CONFIG_ORIGIN
fi

if [[ -d "$CONFIG_STORE" ]]; then
  rm -rf $CONFIG_STORE
fi
