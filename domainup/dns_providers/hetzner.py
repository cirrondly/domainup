from __future__ import annotations

from typing import Dict, List, Optional
import requests


API = "https://dns.hetzner.com/api/v1"


class HetznerError(RuntimeError):
    pass


def _headers(token: str) -> Dict[str, str]:
    return {"Auth-API-Token": token, "Content-Type": "application/json"}


def _list_zones(token: str) -> List[Dict]:
    r = requests.get(f"{API}/zones", headers=_headers(token), timeout=15)
    if r.status_code != 200:
        raise HetznerError(f"zones list failed: {r.status_code} {r.text}")
    return r.json().get("zones", [])


def _list_records(token: str, zone_id: str) -> List[Dict]:
    r = requests.get(f"{API}/records", headers=_headers(token), params={"zone_id": zone_id}, timeout=15)
    if r.status_code != 200:
        raise HetznerError(f"records list failed: {r.status_code} {r.text}")
    return r.json().get("records", [])


def _find_zone_for_host(zones: List[Dict], host: str) -> Optional[Dict]:
    # choose longest matching suffix
    host = host.rstrip('.')
    matches = [z for z in zones if host == z["name"] or host.endswith("." + z["name"]) ]
    if not matches:
        return None
    matches.sort(key=lambda z: len(z["name"]))
    return matches[-1]


def _label_within_zone(host: str, zone_name: str) -> str:
    if host == zone_name:
        return ""
    if host.endswith("." + zone_name):
        return host[: -(len(zone_name) + 1)]
    return host


def _upsert_record(token: str, zone: Dict, records: List[Dict], name: str, rtype: str, value: str, ttl: int = 60) -> None:
    zone_id = zone["id"]
    # find existing record
    existing = next((r for r in records if r["type"] == rtype and r["name"] == name), None)
    payload = {"zone_id": zone_id, "type": rtype, "name": name, "value": value, "ttl": ttl}
    if existing:
        rec_id = existing["id"]
        r = requests.put(f"{API}/records/{rec_id}", headers=_headers(token), json=payload, timeout=15)
        if r.status_code not in (200, 201):
            raise HetznerError(f"update {rtype} {name} failed: {r.status_code} {r.text}")
    else:
        r = requests.post(f"{API}/records", headers=_headers(token), json=payload, timeout=15)
        if r.status_code not in (200, 201):
            raise HetznerError(f"create {rtype} {name} failed: {r.status_code} {r.text}")


def ensure_dns_records_hetzner(token: str, host: str, ipv4: Optional[str], ipv6: Optional[str]) -> None:
    zones = _list_zones(token)
    zone = _find_zone_for_host(zones, host)
    if not zone:
        raise HetznerError(f"No matching zone found in Hetzner for host {host}")
    label = _label_within_zone(host, zone["name"])
    records = _list_records(token, zone["id"])
    if ipv4:
        _upsert_record(token, zone, records, label, "A", ipv4)
    if ipv6:
        _upsert_record(token, zone, records, label, "AAAA", ipv6)
