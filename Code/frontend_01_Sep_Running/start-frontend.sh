#!/bin/bash

# Wrapper script to start Vite dev server
# This handles ES module loading issues when running in background

cd "$(dirname "$0")"

# Run vite directly with node and ESM support
exec node --experimental-vm-modules node_modules/vite/bin/vite.js
