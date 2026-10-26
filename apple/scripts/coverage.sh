#!/bin/sh
# Runs the NestKit tests with coverage and prints the coverage of Sources/NestKit
# (generated tokens excluded). Coverage is reported, not a target (D131).
set -eu

cd "$(dirname "$0")/.."

swift test --enable-code-coverage --quiet

bin_path="$(swift build --show-bin-path)"
profdata="$bin_path/codecov/default.profdata"
bundle="$bin_path/NestKitTests.xctest"
binary="$bundle/Contents/MacOS/$(basename "$bundle" .xctest)"
sources="$(pwd)/Sources/NestKit"

report="$(xcrun llvm-cov report "$binary" -instr-profile="$profdata" \
    -ignore-filename-regex="$sources/Generated/" \
    -show-region-summary=false -show-branch-summary=false "$sources")"

echo "$report" | sed "s|$sources/||"

echo "$report" | awk '
    $1 == "TOTAL" {
        found = 1
        lines = $NF; functions = $(NF - 3)
        printf "NestKit coverage: lines %s, functions %s\n", lines, functions
    }
    END { if (!found) { print "no coverage total found"; exit 1 } }
'
