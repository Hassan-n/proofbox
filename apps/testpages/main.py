from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

app = FastAPI()
PREFIX = "/demo-fixtures-9x7k"
SUBMISSIONS = []

FOOTER = """
<footer style="margin-top:40px;padding:12px;border-top:1px solid #ccc;font-size:12px;color:#555;">
  Proofbox synthetic test page - for sandbox containment testing only. No real institution.
</footer>
"""


@app.middleware("http")
async def add_noindex(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    return response


@app.get(f"{PREFIX}/a1-kingfisher-login", response_class=HTMLResponse)
def a1_phish():
    return f"""<!DOCTYPE html><html><head><meta name="robots" content="noindex">
    <title>Kingfisher Bank - Urgent Account Verification</title></head>
    <body style="font-family:sans-serif;max-width:400px;margin:20px auto;padding:16px;">
      <h2 style="color:#0b4f6c;">Kingfisher Bank Online</h2>
      <p>Your account has been temporarily suspended. Enter your credentials and One-Time PIN to restore access immediately.</p>
      <form action="{PREFIX}/record-submit" method="POST">
        <label>Account / ID Number</label><br><input type="text" name="id_number" placeholder="13-digit ID" style="width:100%;margin-bottom:10px;"><br>
        <label>Online Banking Password</label><br><input type="password" name="password" placeholder="Password" style="width:100%;margin-bottom:10px;"><br>
        <label>One-Time PIN (OTP)</label><br><input type="tel" name="otp_pin" placeholder="6-digit OTP" style="width:100%;margin-bottom:10px;"><br>
        <button type="submit">Verify Account Now</button>
      </form>
      {FOOTER}
    </body></html>"""


@app.get(f"{PREFIX}/a2-containment-test", response_class=HTMLResponse)
def a2_trap():
    return f"""<!DOCTYPE html><html><head><meta name="robots" content="noindex">
    <title>Kingfisher Bank Statement Viewer</title></head>
    <body style="font-family:sans-serif;padding:20px;">
      <h2>Loading your statement...</h2>
      <script>
        const link = document.createElement('a');
        link.href = '{PREFIX}/payload.scr';
        link.download = 'Kingfisher_Statement_Update.scr';
        document.body.appendChild(link);
        link.click();
        fetch('http://169.254.169.254/latest/meta-data/').catch(() => {{}});
        fetch('http://10.0.0.5:8080/internal').catch(() => {{}});
      </script>
      {FOOTER}
    </body></html>"""


@app.get(f"{PREFIX}/payload.scr")
def payload_file():
    return Response(
        content=b"SYNTHETIC_HARMLESS_TEST_FILE_FOR_QUARANTINE_CHECK",
        media_type="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=Kingfisher_Statement_Update.scr"},
    )


@app.get(f"{PREFIX}/a3-karoo-clean", response_class=HTMLResponse)
def a3_clean():
    return f"""<!DOCTYPE html><html><head><meta name="robots" content="noindex">
    <title>Karoo Bay Municipality - Public Library Hours</title></head>
    <body style="font-family:sans-serif;max-width:500px;margin:20px auto;padding:16px;">
      <h2>Karoo Bay Community Notice</h2>
      <p>The municipal public library is open Monday to Friday from 08:30 to 16:30. No login or personal information is required on this page.</p>
      {FOOTER}
    </body></html>"""


@app.get(f"{PREFIX}/a4-hop1")
def a4_hop1():
    return RedirectResponse(url=f"{PREFIX}/a4-hop2", status_code=302)


@app.get(f"{PREFIX}/a4-hop2")
def a4_hop2():
    return RedirectResponse(url=f"{PREFIX}/a4-hop3", status_code=302)


@app.get(f"{PREFIX}/a4-hop3")
def a4_hop3():
    return RedirectResponse(url=f"{PREFIX}/a1-kingfisher-login", status_code=302)


@app.post(f"{PREFIX}/record-submit")
def record_submit():
    SUBMISSIONS.append(True)
    return {"recorded": len(SUBMISSIONS)}


@app.get(f"{PREFIX}/submissions-count")
def get_submissions():
    return {"count": len(SUBMISSIONS)}