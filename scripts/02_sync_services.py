#!/usr/bin/env python3
"""Sync VRFs/VLANs/VNIs from intent/services.yml into NetBox, then refresh
   the service portion of each leaf's local_context_data."""
import yaml
from nb_common import get_api, slug, get_or_create

SVC  = yaml.safe_load(open("intent/services.yml"))
nb   = get_api()

# --- VRFs (+ L3VNI as an L2VPN of type vxlan, terminated on the VRF) ---
vrf_objs = {}
for v in SVC["vrfs"]:
    vrf, _ = get_or_create(nb.ipam.vrfs, {"name": v["name"]}, {"enforce_unique": True})
    vrf_objs[v["name"]] = vrf
    l2vpn, _ = get_or_create(
        nb.vpn.l2vpns, {"slug": slug(f"l3vni-{v['name']}")},
        {"name": f"L3VNI-{v['name']}", "type": "vxlan", "identifier": v["l3vni"]})
    if not nb.vpn.l2vpn_terminations.get(l2vpn_id=l2vpn.id):
        nb.vpn.l2vpn_terminations.create(
            l2vpn=l2vpn.id, assigned_object_type="ipam.vrf",
            assigned_object_id=vrf.id)

# --- VLANs + VNIs (L2VPN of type vxlan terminated on the VLAN) + prefixes ---
for vl in SVC["vlans"]:
    vlan, _ = get_or_create(nb.ipam.vlans, {"vid": vl["id"]},
                            {"name": vl["name"]})
    l2vpn, _ = get_or_create(
        nb.vpn.l2vpns, {"slug": slug(f"vni-{vl['vni']}")},
        {"name": f"VNI-{vl['vni']}", "type": "vxlan", "identifier": vl["vni"]})
    if not nb.vpn.l2vpn_terminations.get(l2vpn_id=l2vpn.id):
        nb.vpn.l2vpn_terminations.create(
            l2vpn=l2vpn.id, assigned_object_type="ipam.vlan",
            assigned_object_id=vlan.id)
    get_or_create(nb.ipam.prefixes, {"prefix": vl["prefix"]},
                  {"vrf": vrf_objs[vl["vrf"]].id, "status": "active"})

# --- push the service block into every leaf's local_context_data ---
l2vni = [{"vlan": v["id"], "vni": v["vni"], "vrf": v["vrf"],
          "svi_ip": v["svi_ip"], "svi_mask": v["svi_mask"]} for v in SVC["vlans"]]
l3vni = {"vrf": SVC["vrfs"][0]["name"],
         "vlan": SVC["vrfs"][0]["l3vni_vlan"],
         "vni":  SVC["vrfs"][0]["l3vni"]}

for dev in nb.dcim.devices.filter(role="leaf"):
    ctx = dev.local_context_data or {}
    ctx["l2vni"] = l2vni
    ctx["l3vni"] = l3vni
    dev.local_context_data = ctx
    dev.save()

print("Service sync complete: VRFs/VLANs/VNIs in NetBox; leaf contexts refreshed.")
