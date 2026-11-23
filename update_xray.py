"""Export selected Runet Freedom categories as a GL.iNet destination list."""

import argparse
from collections import Counter
from ipaddress import IPv4Address, ip_network, summarize_address_range
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
REPO = "runetfreedom/russia-v2ray-rules-dat"
GEOSITES = ("ru-blocked", "youtube", "meta", "twitter", "openai", "discord", "telegram", "whatsapp")
GEOIPS = ("re-filter", "ru-blocked", "ru-blocked-community")
LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
HOST = re.compile(rf"(?:{LABEL}\.)+{LABEL}")


def read_category(binary, directory, revision, kind, name):
    stem = f"{kind}-{name}"
    url = f"https://raw.githubusercontent.com/{REPO}/{revision}/sing-box/rule-set-{kind}/{stem}.srs"
    source = directory / (stem + ".srs")
    with urlopen(url, timeout=60) as response:
        source.write_bytes(response.read())
    target = source.with_suffix(".json")
    subprocess.run([binary, "rule-set", "decompile", str(source), "-o", str(target)], check=True)
    rules = json.loads(target.read_bytes())["rules"]
    if len(rules) != 1 or not rules[0]:
        raise ValueError(f"Unexpected rule structure in {stem}")
    result = {}
    for key, value in rules[0].items():
        values = [value] if isinstance(value, str) else value
        if not isinstance(values, list) or not all(isinstance(v, str) and v for v in values):
            raise ValueError(f"Unexpected {key} entries in {stem}")
        result[key] = values
    print(stem, {key: len(values) for key, values in result.items()})
    return result


def merged_ranges(networks):
    result = []
    for first, last in sorted((int(n.network_address), int(n.broadcast_address)) for n in networks):
        if result and first <= result[-1][1] + 1:
            result[-1][1] = max(result[-1][1], last)
        else:
            result.append([first, last])
    return result


def route_networks(networks, excluded):
    bypass = merged_ranges(excluded)
    for first, last in merged_ranges(networks):
        for left, right in bypass:
            if right < first:
                continue
            if left > last:
                break
            if first < left:
                yield from summarize_address_range(IPv4Address(first), IPv4Address(left - 1))
            first = right + 1
            if first > last:
                break
        if first <= last:
            yield from summarize_address_range(IPv4Address(first), IPv4Address(last))


def read_networks(rule, skipped):
    if set(rule) != {"ip_cidr"} or not rule["ip_cidr"]:
        raise ValueError("Expected a nonempty set of destination IPs")
    result = set()
    for value in rule["ip_cidr"]:
        network = ip_network(value)
        if network.prefixlen == 0:
            raise ValueError("Refusing a default route in a destination list")
        if network.version == 4:
            result.add(network)
        else:
            skipped["IPv6"] += 1
    return result


def build(binary):
    with urlopen(f"https://api.github.com/repos/{REPO}/git/ref/heads/release", timeout=45) as response:
        revision = json.load(response)["object"]["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Invalid upstream revision")
    print(f"Runet Freedom release {revision}")
    domains = {"anthropic.com", "claude.ai"}
    networks = set()
    skipped = Counter()
    with TemporaryDirectory() as temp:
        directory = Path(temp)
        for name in GEOSITES:
            rules = read_category(binary, directory, revision, "geosite", name)
            if not (rules.get("domain") or rules.get("domain_suffix")):
                raise ValueError(f"No literal domains in {name}")
            for key, values in rules.items():
                if key in {"domain_regex", "domain_keyword"}:
                    skipped[key] += len(values)
                    continue
                if key not in {"domain", "domain_suffix"}:
                    raise ValueError(f"Unsupported rule structure in {name}: {key}")
                for value in values:
                    host = value.lower().removeprefix(".").rstrip(".")
                    if "." not in host and re.fullmatch(LABEL, host):
                        skipped["single-label suffix"] += 1
                        continue
                    if len(host) > 253 or not HOST.fullmatch(host):
                        raise ValueError(f"Invalid hostname in {name}: {value!r}")
                    domains.add(host)
        for name in GEOIPS:
            rules = read_category(binary, directory, revision, "geoip", name)
            networks.update(read_networks(rules, skipped))
        private = read_category(binary, directory, revision, "geoip", "private")
        excluded = read_networks(private, Counter())
    domain_list = sorted(domains)
    cidrs = list(route_networks(networks, excluded))
    if not domain_list or not cidrs:
        raise ValueError("Empty export")
    print(f"{len(domain_list)} domains and {len(cidrs)} IPv4 prefixes. Omitted: {dict(skipped)}")
    return "\n".join([*domain_list, *map(str, cidrs)]) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sing-box", default="sing-box", help="Path to the sing-box executable")
    output = build(parser.parse_args().sing_box)
    with TemporaryDirectory(dir=ROOT) as temp:
        target = Path(temp) / "routes-xray.txt"
        target.write_text(output, encoding="utf-8", newline="\n")
        target.replace(ROOT / target.name)
