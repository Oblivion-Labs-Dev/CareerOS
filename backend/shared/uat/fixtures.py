"""Local ATS-shaped contracts, never mirrors or replicas of employer websites."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


FORM = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>CareerOS UAT</title>
<style>body{font:16px Arial;max-width:720px;margin:40px auto}label{display:block;margin:12px}input,select{margin:8px;padding:8px}</style>
<h1>{portal} form contract</h1><form onsubmit="event.preventDefault();document.getElementById('receipt').hidden=false;document.getElementById('submit').disabled=true">
{names}<label>Email<input type=email name=email required></label>
<label>Phone<input type=tel name=phone required></label>
<label for=country>Country</label><select id=country name=country required><option value="">Choose</option><option value=US>United States</option><option value=CA>Canada</option></select>
<label>LinkedIn<input name=linkedin type=url></label>
<label>Resume<input name=resume type=file accept="application/pdf" required onchange="document.getElementById('upload').textContent=this.files.length?'Document attached':''"></label>
<p id=upload></p><button id=submit type=submit>Submit fixture</button></form><p id=receipt hidden>Fixture application confirmed</p></html>'''


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # No request paths or PII in test logs.

    def do_GET(self):
        path = self.path.split('?',1)[0]
        if path == '/challenge':
            body = '<body data-uat-challenge>Verify you are human</body>'
        elif path == '/expired':
            body = '<body>Your session has expired</body>'
        elif path in ('/greenhouse', '/lever', '/himalayas'):
            names = '<label>First name<input name=firstName required></label><label>Last name<input name=lastName required></label>'
            if path == '/lever':
                names = '<label>Full name<input name=fullName required></label>'
            body = FORM.replace('{portal}',path[1:]).replace('{names}',names)
            if path == '/himalayas':
                body = '<body><h1>Embedded application contract</h1><iframe title="Application" src="/greenhouse" style="width:900px;height:950px"></iframe></body>'
        elif path == '/locked':
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b'<body>Access denied</body>')
            return
        elif path == '/custom':
            body = '''<body><label>First name<input name=firstName required></label>
            <label for=country>Country</label><input id=country role=combobox aria-expanded=false aria-controls=options readonly required onclick="document.getElementById('options').hidden=false;this.setAttribute('aria-expanded','true')">
            <div id=options role=listbox hidden><div role=option onclick="document.getElementById('country').value=this.textContent;this.parentNode.hidden=true">United States</div><div role=option>Canada</div></div></body>'''
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(body.encode())


@contextmanager
def fixture_server():
    server = ThreadingHTTPServer(('127.0.0.1', 0), FixtureHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
