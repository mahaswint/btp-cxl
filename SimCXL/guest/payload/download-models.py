"""Stage explicit files using the guest's Python-3.6-compatible Hub API."""
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urljoin

from huggingface_hub import cached_download, hf_hub_url
from huggingface_hub import file_download


@contextmanager
def absolute_redirects():
    """Hub 0.4 forwards HEAD Location directly to requests, even if relative."""
    original = file_download._request_with_retry

    def request(method, url, *args, **kwargs):
        response = original(method, url, *args, **kwargs)
        location = response.headers.get('Location')
        if location:
            response.headers['Location'] = urljoin(response.url or url, location)
        return response

    file_download._request_with_retry = request
    try:
        yield
    finally:
        file_download._request_with_retry = original


def download(repo, filenames, directory):
    Path(directory).mkdir(parents=True, exist_ok=True)
    with absolute_redirects():
        for filename in filenames:
            cached_download(hf_hub_url(repo, filename), cache_dir=directory,
                            force_filename=filename, resume_download=True)


if __name__ == '__main__':
    download('google-bert/bert-base-uncased',
             ['config.json', 'tokenizer_config.json', 'vocab.txt', 'pytorch_model.bin'],
             '/opt/btp/models/bert')
    download('bartowski/Llama-3.2-1B-Instruct-GGUF',
             ['Llama-3.2-1B-Instruct-Q4_K_M.gguf'], '/opt/btp/models/llama')
