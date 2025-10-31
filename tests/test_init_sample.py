from pathlib import Path
from domainup.config import write_sample_config


def test_write_sample_config(tmp_path: Path):
    out = tmp_path / "domainup.yaml"
    write_sample_config(out, email="contact@cirrondly.com")
    text = out.read_text()
    assert "email: contact@cirrondly.com" in text
    # braces must remain intact (no KeyError):
    assert "tls: { enabled: true }" in text
    assert "admin:{SHA}..." in text