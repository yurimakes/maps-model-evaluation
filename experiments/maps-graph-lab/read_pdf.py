import io,sys
from pypdf import PdfReader
sys.stdout.reconfigure(encoding='utf8')
print('\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(sys.stdin.buffer.read())).pages))
