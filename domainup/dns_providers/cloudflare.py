from __future__ import annotations

from typing import Dict, List, Optional
import requests


API = "https://api.cloudflare.com/client/v4"


class CloudflareError(RuntimeError):
    pass


def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_zone(token: str, name: str) -> Dict:
    r = requests.get(f"{API}/zones", headers=_headers(token), params={"name": name}, timeout=15)
    if r.status_code != 200:
        raise CloudflareError(f"zones list failed: {r.status_code} {r.text}")
    result = r.json().get("result", [])
    if not result:
        raise CloudflareError(f"zone not found for {name}")
    return result[0]


def _list_records(token: str, zone_id: str, rtype: str, name: str) -> List[Dict]:
    r = requests.get(
        f"{API}/zones/{zone_id}/dns_records",
        headers=_headers(token),
        params={"type": rtype, "name": name},
        timeout=15,
    )
    if r.status_code != 200:
        raise CloudflareError(f"records list failed: {r.status_code} {r.text}")
    return r.json().get("result", [])


def _create_record(token: str, zone_id: str, rtype: str, name: str, content: str, ttl: int = 60) -> None:
    payload = {"type": rtype, "name": name, "content": content, "ttl": ttl}
    r = requests.post(f"{API}/zones/{zone_id}/dns_records", headers=_headers(token), json=payload, timeout=15)
    if r.status_code not in (200, 201):
        raise CloudflareError(f"create {rtype} {name} failed: {r.status_code} {r.text}")


def _update_record(token: str, zone_id: str, rec_id: str, rtype: str, name: str, content: str, ttl: int = 60) -> None:
    payload = {"type": rtype, "name": name, "content": content, "ttl": ttl}
    r = requests.put(f"{API}/zones/{zone_id}/dns_records/{rec_id}", headers=_headers(token), json=payload, timeout=15)
    if r.status_code not in (200, 201):
        raise CloudflareError(f"update {rtype} {name} failed: {r.status_code} {r.text}")


def ensure_dns_records_cloudflare(token: str, host: str, ipv4: Optional[str], ipv6: Optional[str]) -> None:
    # Find zone by walking labels from host to root
    labels = host.rstrip('.').split('.')
    for i in range(len(labels)):
        zone_name = '.'.join(labels[i:])
        try:
            zone = _get_zone(token, zone_name)
            break
        except CloudflareError:
            continue
    else:
        raise CloudflareError(f"No matching zone found in Cloudflare for host {host}")

    zone_id = zone["id"]
    name = host  # Cloudflare expects FQDN in name

    if ipv4:
        existing = _list_records(token, zone_id, "A", name)
        if existing:
            _update_record(token, zone_id, existing[0]["id"], "A", name, ipv4)
        else:
            _create_record(token, zone_id, "A", name, ipv4)
    if ipv6:
        existing = _list_records(token, zone_id, "AAAA", name)
        if existing:
            _update_record(token, zone_id, existing[0]["id"], "AAAA", name, ipv6)
        else:
            _create_record(token, zone_id, "AAAA", name, ipv6)
