from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def public_files():
    return [p for p in ROOT.rglob('*') if p.is_file() and not ({'.venv','.git','.pytest_cache','__pycache__'} & set(p.relative_to(ROOT).parts))]
def test_no_large_files():assert not [p for p in public_files() if p.stat().st_size>5*1024*1024]
def test_no_model_weights():assert not [p for p in public_files() if p.suffix in {'.safetensors','.pt','.pth','.bin','.ckpt','.gguf'}]
def test_no_private_keys():
    text='\n'.join(p.read_text(errors='ignore') for p in public_files() if p.stat().st_size<1_000_000)
    assert ('BEGIN OPENSSH'+' PRIVATE KEY') not in text and ('BEGIN RSA'+' PRIVATE KEY') not in text
def test_no_server_identity():
    text='\n'.join(p.read_text(errors='ignore') for p in public_files() if p.stat().st_size<1_000_000)
    assert ('125.71.'+'97.38') not in text
    assert ('/root/'+'research/') not in text
