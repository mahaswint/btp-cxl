#!/bin/bash
# Selected explicitly using init=; bypass upstream benchmark autorun scripts.
export PATH=/opt/btp/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
fail() {
    echo "SIMCXL_BOOT_FAILED: $*" >/dev/console
    /opt/btp/bin/m5 --addr fail 1
    while :; do sleep 60; done
}
mount -t proc proc /proc || true
mount -t sysfs sysfs /sys || true
mount -t devtmpfs devtmpfs /dev || true
mkdir -p /dev/pts /run /tmp
mount -t devpts devpts /dev/pts || true
mount -t tmpfs tmpfs /run || true
mount -o remount,rw / || fail 'cannot remount root writable'
exec </dev/console >/dev/console 2>&1
hostname simcxl-btp
# Start device discovery without booting the base image's benchmark services.
for daemon in /lib/systemd/systemd-udevd /usr/lib/systemd/systemd-udevd /sbin/udevd; do
    if [[ -x "$daemon" ]]; then "$daemon" --daemon; break; fi
done
for module in cxl_pci cxl_mem dax_pmem; do modprobe "$module" 2>/dev/null || true; done
udevadm trigger --action=add || true
udevadm settle --timeout=30 || true
for state in /sys/devices/system/memory/memory*/state; do
    [[ -f "$state" ]] || continue
    if [[ "$(cat "$state")" == offline ]]; then echo online_movable > "$state" || true; fi
done
numactl --hardware
/opt/btp/bin/m5 --addr readfile > /run/simcxl-command.sh || fail 'm5 readfile failed'
[[ -s /run/simcxl-command.sh ]] || fail 'no host workload command supplied'
bash /run/simcxl-command.sh
fail 'host command returned without a final simulator exit'
