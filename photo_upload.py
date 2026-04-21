from flask import Flask, request
from pathlib import Path
import secrets
import os

app = Flask(__name__)

D = Path("/srv/photos")
D.mkdir(parents=True, exist_ok=True)

F = '''
<html>
<body style="font-family:Arial;font-size:22px;margin:40px">
<h1>Upload zdjęcia</h1>

<form method="post" enctype="multipart/form-data">
<input type="file" name="file" required style="font-size:20px"><br><br>
<button type="submit" style="font-size:22px;padding:10px 20px">Wyślij</button>
</form>

%s

<script>
function copyLink() {
  const link = document.getElementById("imglink").innerText;
  navigator.clipboard.writeText(link).then(function() {
    alert("Link skopiowany do schowka");
  });
}
</script>

</body>
</html>
'''

def rn(n):
    e = Path(n).suffix.lower()
    if e not in {".jpg",".jpeg",".png",".webp",".gif"}:
        e = ".jpg"
    return secrets.token_hex(8) + e

@app.route("/upload", methods=["GET","POST","HEAD"])
def u():
    if request.method in ("GET","HEAD"):
        return F % ""

    f = request.files.get("file")
    if not f or not f.filename:
        return F % "<p>Brak pliku</p>",400

    n = rn(f.filename)
    p = D / n
    f.save(p)
    os.chmod(p,0o644)

    r = f"https://hal.taildb8550.ts.net/{n}"

    msg = f'''
<p><b>OK:</b></p>
<p id="imglink" style="font-size:28px">{r}</p>
<p>
<a href="{r}" target="_blank">Otwórz zdjęcie</a>
</p>
<button onclick="copyLink()" style="font-size:20px;padding:10px 20px">
Kopiuj link
</button>
'''

    return F % msg

if __name__ == "__main__":
    app.run(host="127.0.0.1",port=5000)
