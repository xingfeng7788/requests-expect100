import requests.adapters
from unittest.mock import MagicMock, patch


def test_request_url_handles_leading_path_separators():
    """See also https://github.com/psf/requests/issues/6643."""
    a = requests.adapters.HTTPAdapter()
    p = requests.Request(method="GET", url="http://127.0.0.1:10000//v:h").prepare()
    assert "//v:h" == a.request_url(p, {})


def _make_urllib3_resp(status, headers=None):
    """构造一个最小化的 urllib3 响应 mock"""
    from requests.structures import CaseInsensitiveDict
    resp = MagicMock()
    resp.status = status
    resp.headers = CaseInsensitiveDict(headers or {})
    resp.reason = {100: "Continue", 200: "OK", 301: "Moved Permanently", 417: "Expectation Failed"}.get(status, "Unknown")
    resp.version = 11
    resp.length_remaining = 0
    resp.read = MagicMock(return_value=b"")
    return resp


def test_expect100_two_phase_on_100_continue():
    """收到 100 Continue 后应发送完整 body（两阶段）"""
    from requests.adapters import HTTPAdapter
    from requests.models import PreparedRequest
    from requests.structures import CaseInsensitiveDict

    adapter = HTTPAdapter()
    req = PreparedRequest()
    req.method = "POST"
    req.url = "http://example.com/upload"
    req.headers = CaseInsensitiveDict({"Expect": "100-continue", "Content-Length": "5"})
    req.body = b"hello"
    req._body_position = None
    req.hooks = {"response": []}

    continue_resp = _make_urllib3_resp(100)
    ok_resp = _make_urllib3_resp(200)

    with patch.object(adapter, "get_connection_with_tls_context") as mock_get_conn, \
         patch.object(adapter, "cert_verify"), \
         patch.object(adapter, "add_headers"):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.urlopen.side_effect = [continue_resp, ok_resp]

        resp = adapter.send(req, expect100=True, timeout=5, verify=False)

    assert mock_conn.urlopen.call_count == 2
    first_kwargs = mock_conn.urlopen.call_args_list[0][1]
    second_kwargs = mock_conn.urlopen.call_args_list[1][1]

    # 第一阶段：body 为 None
    assert first_kwargs["body"] is None
    # 第二阶段：带完整 body
    assert second_kwargs["body"] == b"hello"
    # 第二阶段：不含 Expect header
    second_headers = second_kwargs.get("headers", {})
    assert "Expect" not in second_headers


def test_expect100_returns_on_redirect():
    """收到 3xx 时应直接返回（不发 body）"""
    from requests.adapters import HTTPAdapter
    from requests.models import PreparedRequest
    from requests.structures import CaseInsensitiveDict

    adapter = HTTPAdapter()
    req = PreparedRequest()
    req.method = "POST"
    req.url = "http://example.com/upload"
    req.headers = CaseInsensitiveDict({"Expect": "100-continue", "Content-Length": "5"})
    req.body = b"hello"
    req._body_position = None
    req.hooks = {"response": []}

    redirect_resp = _make_urllib3_resp(301, {"Location": "http://example.com/new"})

    with patch.object(adapter, "get_connection_with_tls_context") as mock_get_conn, \
         patch.object(adapter, "cert_verify"), \
         patch.object(adapter, "add_headers"):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.urlopen.return_value = redirect_resp

        resp = adapter.send(req, expect100=True, timeout=5, verify=False)

    # 只调用一次（只发 headers），body 未发
    assert mock_conn.urlopen.call_count == 1
    first_kwargs = mock_conn.urlopen.call_args_list[0][1]
    assert first_kwargs["body"] is None


def test_expect100_returns_on_417():
    """收到 417 Expectation Failed 时应直接返回"""
    from requests.adapters import HTTPAdapter
    from requests.models import PreparedRequest
    from requests.structures import CaseInsensitiveDict

    adapter = HTTPAdapter()
    req = PreparedRequest()
    req.method = "POST"
    req.url = "http://example.com/upload"
    req.headers = CaseInsensitiveDict({"Expect": "100-continue", "Content-Length": "5"})
    req.body = b"hello"
    req._body_position = None
    req.hooks = {"response": []}

    fail_resp = _make_urllib3_resp(417)

    with patch.object(adapter, "get_connection_with_tls_context") as mock_get_conn, \
         patch.object(adapter, "cert_verify"), \
         patch.object(adapter, "add_headers"):
        mock_conn = MagicMock()
        mock_get_conn.return_value = mock_conn
        mock_conn.urlopen.return_value = fail_resp

        resp = adapter.send(req, expect100=True, timeout=5, verify=False)

    assert mock_conn.urlopen.call_count == 1
    assert resp.status_code == 417
