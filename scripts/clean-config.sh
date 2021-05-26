#!/bin/bash

set -a
source local.config
set +a

if [[ -d "$CONFIG_ORIGIN" ]]; then
  rm -rf $CONFIG_ORIGIN
fi

if [[ -d "$CONFIG_STORE" ]]; then
  rm -rf $CONFIG_STORE
fi
