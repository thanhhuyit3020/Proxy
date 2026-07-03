from __future__ import annotations

from proxy_manager.models import ProxyScheme
from proxy_manager.proxy_pool import _looks_like_ip, parse_proxy_file, parse_proxy_line


def test_parse_uri_format_socks5_with_auth():
    p = parse_proxy_line("socks5://user1:pass1@1.2.3.4:1080")
    assert p.scheme == ProxyScheme.SOCKS5
    assert p.host == "1.2.3.4"
    assert p.port == 1080
    assert p.username == "user1"
    assert p.password == "pass1"


def test_parse_uri_format_http_no_auth():
    p = parse_proxy_line("http://5.6.7.8:8080")
    assert p.scheme == ProxyScheme.HTTP
    assert p.username is None
    assert p.password is None


def test_parse_uri_format_https_collapses_to_http():
    p = parse_proxy_line("https://5.6.7.8:8443")
    assert p.scheme == ProxyScheme.HTTP


def test_parse_legacy_colon_format_with_auth():
    p = parse_proxy_line("9.9.9.9:3128:bob:secret")
    assert p.scheme == ProxyScheme.HTTP
    assert p.host == "9.9.9.9"
    assert p.port == 3128
    assert p.username == "bob"
    assert p.password == "secret"


def test_parse_legacy_colon_format_no_auth():
    p = parse_proxy_line("9.9.9.9:3128")
    assert p.username is None
    assert p.password is None


def test_parse_blank_and_comment_lines_ignored():
    assert parse_proxy_line("") is None
    assert parse_proxy_line("   ") is None
    assert parse_proxy_line("# comment") is None


def test_parse_proxy_file(tmp_path):
    content = "\n".join([
        "# header comment",
        "socks5://u:p@1.1.1.1:1080",
        "",
        "http://2.2.2.2:8080",
        "3.3.3.3:3128:x:y",
    ])
    path = tmp_path / "proxies.txt"
    path.write_text(content, encoding="utf-8")

    proxies = parse_proxy_file(path)
    assert len(proxies) == 3
    assert proxies[0].host == "1.1.1.1"
    assert proxies[1].host == "2.2.2.2"
    assert proxies[2].host == "3.3.3.3"


def test_looks_like_ip_v4():
    assert _looks_like_ip("203.0.113.5") is True


def test_looks_like_ip_v6():
    assert _looks_like_ip("2001:db8::1") is True


def test_looks_like_ip_rejects_garbage():
    assert _looks_like_ip("not-an-ip") is False
    assert _looks_like_ip("<html>error</html>") is False
