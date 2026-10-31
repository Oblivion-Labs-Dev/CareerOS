# Night loop sentinel: every 30 min, pull fresh 24h postings and log.
# Does NOT run the audit (requires agent judgment); agent is woken by sentinel output.
$repo = "D:/1 - Projects/Projects/CareerOS/CareerOS"
$log = "$env:TEMP\careerOS-nightloop.log"
while ($true) {
    $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    "[$ts] AGENT_LOOP_TICK_nightloop" | Out-File -Append -FilePath $log -Encoding utf8
    try {
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:4000/jobs/discover/scrape" -ContentType "application/json" -Body '{"hours":24,"roles":"swe","mode":"ats"}' | Out-Null
        "[$ts] scrape started" | Out-File -Append -FilePath $log -Encoding utf8
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