#!/usr/bin/env python3
"""Build the physical/underlay model in NetBox from intent/topology.yml."""
import yaml
from nb_common import get_api, slug, get_or_create

TOPO = yaml.safe_load(open("intent/topology.yml"))
nb = get_api()

# --- foundation objects ---
site, _   = get_or_create(nb.dcim.sites, {"slug": slug(TOPO["site"])},
                          {"name": TOPO["site"]})
mfr, _    = get_or_create(nb.dcim.manufacturers, {"slug": "cisco"}, {"name": "Cisco"})
dtype, _  = get_or_create(nb.dcim.device_types, {"slug": "nexus-9000v"},
                          {"model": "Nexus 9000v", "manufacturer": mfr.id})
roles = {}
for r, color in (("spine", "00bcd4"), ("leaf", "4caf50")):
    roles[r], _ = get_or_create(nb.dcim.device_roles, {"slug": r},
                                {"name": r.capitalize(), "color": color})

def ensure_intf(dev, name, itype="1000base-t"):
    obj = nb.dcim.interfaces.get(device_id=dev.id, name=name)
    if not obj:
        obj = nb.dcim.interfaces.create(device=dev.id, name=name, type=itype)
    return obj

def ensure_ip(intf, addr, masklen):
    cidr = f"{addr}/{masklen}"
    obj = nb.ipam.ip_addresses.get(address=cidr)
    if not obj:
        obj = nb.ipam.ip_addresses.create(
            address=cidr,
            assigned_object_type="dcim.interface",
            assigned_object_id=intf.id,
        )
    return obj

# --- devices, mgmt, loopbacks ---
dev_objs = {}
for d in TOPO["devices"]:
    dev, _ = get_or_create(
        nb.dcim.devices, {"name": d["name"]},
        {"device_type": dtype.id, "role": roles[d["role"]].id,
         "site": site.id, "status": "active"})
    dev_objs[d["name"]] = dev

    mgmt = ensure_intf(dev, "mgmt0")
    mgmt_ip = ensure_ip(mgmt, d["mgmt"], 24)
    dev.primary_ip4 = mgmt_ip.id
    dev.save()

    lo0 = ensure_intf(dev, "loopback0", itype="virtual")
    ensure_ip(lo0, d["loopback0"], 32)
    if d.get("loopback1"):
        lo1 = ensure_intf(dev, "loopback1", itype="virtual")
        ensure_ip(lo1, d["loopback1"], 32)

# --- underlay links + IPs (+ optional cabling) ---
for ln in TOPO["links"]:
    a, b = dev_objs[ln["a"]], dev_objs[ln["b"]]
    ai = ensure_intf(a, ln["a_int"]); ensure_ip(ai, ln["a_ip"], ln["mask"])
    bi = ensure_intf(b, ln["b_int"]); ensure_ip(bi, ln["b_ip"], ln["mask"])
    if not ai.cable and not bi.cable:           # idempotent cabling
        nb.dcim.cables.create(
            a_terminations=[{"object_type": "dcim.interface", "object_id": ai.id}],
            b_terminations=[{"object_type": "dcim.interface", "object_id": bi.id}],
            status="connected")

# access ports
for ap in TOPO.get("access_ports", []):
    ensure_intf(dev_objs[ap["device"]], ap["interface"])

# --- compute per-device local_context_data (infra/underlay portion) ---
spine_lo = {d["name"]: d["loopback0"] for d in TOPO["devices"] if d["role"] == "spine"}
leaf_lo  = {d["name"]: d["loopback0"] for d in TOPO["devices"] if d["role"] == "leaf"}

# map device -> list of its underlay links {interface, ip, mask}
under = {d["name"]: [] for d in TOPO["devices"]}
for ln in TOPO["links"]:
    under[ln["a"]].append({"interface": ln["a_int"], "ip": ln["a_ip"], "mask": ln["mask"]})
    under[ln["b"]].append({"interface": ln["b_int"], "ip": ln["b_ip"], "mask": ln["mask"]})

acc = {}
for ap in TOPO.get("access_ports", []):
    acc.setdefault(ap["device"], []).append({"interface": ap["interface"], "vlan": ap["vlan"]})

for d in TOPO["devices"]:
    dev = dev_objs[d["name"]]
    ctx = dev.local_context_data or {}
    ctx.update({
        "role": d["role"],
        "bgp_asn": TOPO["fabric_asn"],
        "router_id": d["loopback0"],
        "loopback0": d["loopback0"],
        "anycast_gw_mac": TOPO["anycast_gw_mac"],
        "underlay_links": under[d["name"]],
    })
    if d["role"] == "leaf":
        ctx["vtep_loopback1"]   = d["loopback1"]
        ctx["route_reflectors"] = sorted(spine_lo.values())
        ctx["access_ports"]     = acc.get(d["name"], [])
    else:  # spine
        ctx["rr_clients"] = sorted(leaf_lo.values())
    dev.local_context_data = ctx
    dev.save()

print("Bootstrap complete: devices, IPAM and underlay context written to NetBox.")
