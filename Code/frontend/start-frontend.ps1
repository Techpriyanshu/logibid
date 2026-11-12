# Wrapper script to start Vite dev server on Windows
# This handles ES module loading issues

Set-Location $PSScriptRoot

# Run vite directly with node and ESM support
node --experimental-vm-modules node_modules\vite\bin\vite.js
