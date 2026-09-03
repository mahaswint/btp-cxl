#!/usr/bin/env bash
# Only for the temporary libguestfs appliance started with the direct backend.
set -euo pipefail
if ! grep -qw guestfs_network=1 /proc/cmdline; then
    echo 'Network preparation requires a libguestfs appliance with --network' >&2
    exit 1
fi
if [[ -z "$(ip -4 route show default)" ]]; then
    # Some host libguestfs packages fail DHCP, leaving eth0 down. The direct
    # backend's QEMU user network has fixed guest/gateway/DNS addresses.
    test -d /sys/class/net/eth0
    echo 'Appliance DHCP did not configure a route; configuring the private QEMU network'
    ip link set eth0 up
    ip addr replace 169.254.2.15/16 dev eth0
    ip route replace default via 169.254.2.2 dev eth0
fi
ip -4 route show default
