#!/bin/bash
# Follow historyHourly pagination to get all data
# Usage: ./scripts/explore_api.sh <access_token> <device_id>

set -e

ACCESS_TOKEN="${1:-$POINTT_ACCESS_TOKEN}"
DEVICE_ID="${2:-$BOSCH_DEVICE_ID}"

if [ -z "$ACCESS_TOKEN" ] || [ -z "$DEVICE_ID" ]; then
    echo "Usage: $0 <access_token> <device_id>"
    exit 1
fi

BASE="https://pointt-api.bosch-thermotechnology.com/pointt-api/api/v1/gateways/${DEVICE_ID}/resource"

echo "Following historyHourly pagination..."
echo "========================================"

next=""
page=0

while true; do
    if [ -z "$next" ]; then
        url="${BASE}/energy/historyHourly"
    else
        url="${BASE}/energy/historyHourly?next=${next}"
    fi

    page=$((page + 1))
    response=$(curl -s -H "Authorization: Bearer $ACCESS_TOKEN" "$url" 2>/dev/null)

    # Get first and last entry dates
    first_date=$(echo "$response" | jq -r '.value[0].entries[0] | "\(.d) h\(.h)"' 2>/dev/null)
    last_date=$(echo "$response" | jq -r '.value[0].entries[-1] | "\(.d) h\(.h)"' 2>/dev/null)
    next_val=$(echo "$response" | jq -r '.value[0].next // empty' 2>/dev/null)
    num_entries=$(echo "$response" | jq -r '.value[0].entries | length' 2>/dev/null)

    echo "Page $page (next=$next): $first_date -> $last_date ($num_entries entries, next=$next_val)"

    # Check if we've reached the end or have no more pages
    if [ -z "$next_val" ] || [ "$next_val" = "null" ]; then
        echo ""
        echo "Reached end of data. Last page:"
        echo "$response" | jq '.value[0].entries'
        break
    fi

    next="$next_val"

    # Safety limit
    if [ $page -ge 20 ]; then
        echo "Stopped at page 20 (safety limit)"
        break
    fi
done

echo "========================================"
echo "Done"
