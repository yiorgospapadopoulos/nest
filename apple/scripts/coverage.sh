#!/bin/sh
# Runs the NestKit tests with coverage and fails unless every line and function of
# Sources/NestKit (generated tokens excluded) is covered.
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
        if (lines != "100.00%" || functions != "100.00%") {
            print "coverage is below 100%"
            exit 1
        }
    }
    END { if (!found) { print "no coverage total found"; exit 1 } }
'
