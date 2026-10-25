from unittest.mock import MagicMock, patch

import httpx

from chaoxing.captcha import CaptchaSolver


def test_missing_ocr_is_loaded_once_and_does_not_request_captcha() -> None:
    solver = CaptchaSolver()
    http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    with patch("chaoxing.captcha.importlib.import_module", side_effect=ImportError) as load:
        assert not solver.solve(http)
        assert not solver.solve(http)
    load.assert_called_once_with("ddddocr")
    http.close()


def test_ocr_uses_same_session_and_accepts_redirect() -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("Png.ac"):
            return httpx.Response(200, content=b"png", headers={"content-type": "image/png"})
        assert request.url.params["ucode"] == "1234"
        return httpx.Response(302, headers={"set-cookie": "verified=yes; Path=/"})

    module = MagicMock()
    module.DdddOcr.return_value.classification.return_value = "1234"
    http = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True)
    with patch("chaoxing.captcha.importlib.import_module", return_value=module):
        assert CaptchaSolver().solve(http)
    assert len(requests) == 2
    assert http.cookies.get("verified") == "yes"
    http.close()
