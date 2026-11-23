"""Derive a GL.iNet subscription with Twitch video over VPN and direct site exceptions."""

import socket
from ipaddress import IPv4Address, ip_network
from pathlib import Path
from tempfile import TemporaryDirectory

from update_xray import route_networks


ROOT = Path(__file__).resolve().parent
TWITCH_VIDEO = {"hls.live-video.net", "hls.ttvnw.net", "playlist.ttvnw.net"}
DIRECT_DOMAINS = {
    "bonga22.com", "bongacams.com", "bcicdn.com", "bcrncdn.com", "bcvcdn.com",
    "bgicdn.com", "i.edge3710.net", "xvideos.com", "xvideos-cdn.com",
    "xv-ru.com", "xvideos-ar.com", "xvideos-india.com",
}
REQUIRED_HOSTS = {"bongacams.com", "rt.bonga22.com", "i.edge3710.net", "xvideos.com", "www.xvideos.com"}
# Addresses returned by the router in Russia. CI may see other CDN locations.
LOCAL_DIRECT_IPV4 = {
    "89.222.127.1/32", "89.222.127.2/31", "89.222.127.4/30", "89.222.127.8/29",
    "185.229.206.218/32", "31.192.114.131/32", "84.38.5.10/32",
    "195.85.23.10/32", "195.85.23.246/32",
}


def suffixes(host):
    parts = host.split(".")
    return (".".join(parts[i:]) for i in range(len(parts)))


def direct_networks(hosts):
    networks = {ip_network(prefix) for prefix in LOCAL_DIRECT_IPV4}
    for host in sorted(hosts):
        try:
            answers = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        except socket.gaierror as error:
            no_address = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", None)}
            if host in REQUIRED_HOSTS or error.errno not in no_address:
                raise
            continue
        public = {IPv4Address(answer[4][0]) for answer in answers if IPv4Address(answer[4][0]).is_global}
        if host in REQUIRED_HOSTS and not public:
            raise ValueError(f"No public IPv4 address for {host}")
        networks.update(ip_network(address) for address in public)
    return networks


def build():
    entries = (ROOT / "routes-xray.txt").read_text(encoding="ascii").splitlines()
    domains = {v for v in entries if "/" not in v}
    networks = [ip_network(v) for v in entries if "/" in v]
    if not networks or not {"anthropic.com", "claude.ai"}.issubset(domains):
        raise ValueError("Incomplete source subscription")

    direct_names = {d for d in domains if not DIRECT_DOMAINS.isdisjoint(suffixes(d))}
    # A positive list also cannot keep a parent rule that captures an excluded child.
    direct_parents = {parent for d in DIRECT_DOMAINS for parent in suffixes(d)}
    routed_domains = (domains - direct_names - direct_parents) | TWITCH_VIDEO
    lookup = DIRECT_DOMAINS | direct_names | REQUIRED_HOSTS | {"www.bongacams.com", "www.bonga22.com"}
    excluded = direct_networks(lookup)
    routed_networks = list(route_networks(networks, excluded))
    print(f"{len(routed_domains)} domains, {len(routed_networks)} IPv4 prefixes; {len(excluded)} direct prefixes checked")
    return "\n".join([*sorted(routed_domains), *map(str, routed_networks)]) + "\n"


if __name__ == "__main__":
    result = build()
    with TemporaryDirectory(dir=ROOT) as temp:
        output = Path(temp) / "routes-xray-twitch.txt"
        output.write_text(result, encoding="ascii", newline="\n")
        output.replace(ROOT / output.name)
