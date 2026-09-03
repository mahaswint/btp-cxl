"""Redirect regressions without network requests or model downloads."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch


class ModelDownloadTest(unittest.TestCase):
    def setUp(self):
        self.client = types.ModuleType('huggingface_hub.file_download')
        self.client._request_with_retry = Mock()
        hub = types.ModuleType('huggingface_hub')
        hub.file_download = self.client
        hub.cached_download = Mock()
        hub.hf_hub_url = Mock()
        source = Path(__file__).parents[2] / 'guest/payload/download-models.py'
        spec = importlib.util.spec_from_file_location('model_downloads', source)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'huggingface_hub': hub}):
            spec.loader.exec_module(self.module)

    def test_relative_redirect_becomes_absolute_preserving_query(self):
        response = types.SimpleNamespace(url='https://huggingface.co/google-bert/bert-base-uncased/resolve/main/config.json',
            headers={'Location': '/api/resolve-cache/models/bert/config.json?etag=%22abc%22'})
        original = self.client._request_with_retry
        original.return_value = response
        with self.module.absolute_redirects():
            result = self.client._request_with_retry('HEAD', response.url, allow_redirects=False)
            self.assertEqual(result.headers['Location'],
                             'https://huggingface.co/api/resolve-cache/models/bert/config.json?etag=%22abc%22')
        self.assertIs(self.client._request_with_retry, original)

    def test_absolute_signed_url_is_unchanged(self):
        url = 'https://cdn.example.com/weights?signature=abc%2Fdef&expires=123'
        response = types.SimpleNamespace(url='https://huggingface.co/model/resolve/main/weights',
                                         headers={'Location': url})
        self.client._request_with_retry.return_value = response
        with self.module.absolute_redirects():
            self.assertEqual(self.client._request_with_retry('HEAD', response.url).headers['Location'], url)

    def test_original_client_is_restored_on_error(self):
        original = self.client._request_with_retry
        original.side_effect = OSError('connection failed')
        with self.assertRaises(OSError):
            with self.module.absolute_redirects():
                self.client._request_with_retry('HEAD', 'https://huggingface.co/model')
        self.assertIs(self.client._request_with_retry, original)


if __name__ == '__main__':
    unittest.main()
