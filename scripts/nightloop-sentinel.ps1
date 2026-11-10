# Night loop sentinel: every 30 min, check when last pulled and pull fresh postings to today.
# Does NOT run the audit (requires agent judgment); agent is woken by sentinel output.
$repo = "D:/1 - Projects/Projects/CareerOS/CareerOS"
$log = "$env:TEMP\careerOS-nightloop.log"
while ($true) {
    $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    "[$ts] AGENT_LOOP_TICK_nightloop" | Out-File -Append -FilePath $log -Encoding utf8
    try {
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:4000/jobs/discover/scrape" -ContentType "application/json" -Body '{"roles":"swe","mode":"ats"}' | Out-Null
        "[$ts] scrape started (from last pull to now)" | Out-File -Append -FilePath $log -Encoding utf8
    } catch {
        if ($_.Exception.Response.StatusCode.value__ -eq 409) {
            "[$ts] scrape already running (409); will wait" | Out-File -Append -FilePath $log -Encoding utf8
        } else {
            "[$ts] scrape err: $($_.Exception.Message)" | Out-File -Append -FilePath $log -Encoding utf8
        }
    }
    # wait up to 5 min for scrape to finish
    for ($i=0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 5
        $s = Invoke-RestMethod "http://127.0.0.1:4000/jobs/discover/status"
        if (-not $s.running) { break }
    }
    $st = Invoke-RestMethod "http://127.0.0.1:4000/jobs/discover/status"
    "[$ts] scrape done: $($st.lastResult)" | Out-File -Append -FilePath $log -Encoding utf8
    $rs = Invoke-RestMethod "http://127.0.0.1:4000/application-assistant/autopilot/status"
    "[$ts] runner running=$($rs.running) status=$($rs.status) processed=$($rs.run.processedCount) submitted=$($rs.run.submittedCount)" | Out-File -Append -FilePath $log -Encoding utf8
    Start-Sleep -Seconds 1800
}
